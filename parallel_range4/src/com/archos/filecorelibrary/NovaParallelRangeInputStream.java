package com.archos.filecorelibrary;

import android.util.Log;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.atomic.AtomicLong;

/** A byte-exact, bounded, four-connection prefetcher for StreamOverHttp WebDAV media only. */
public final class NovaParallelRangeInputStream extends InputStream {
    public interface Source {
        InputStream openRange(long absoluteOffset) throws IOException;
        boolean cancelled();
    }

    private static final String TAG = "NOVA_RANGE4";
    private static final int CHUNK = 4 * 1024 * 1024;
    private static final int CONCURRENCY = 4;
    private static final long MIN_LENGTH = 4L * CHUNK;
    // Independent network staging limit. AVOS separately enforces its 10X decoded
    // packet-queue budget; the two budgets must not be represented as identical.
    private static final long MAX_PREFETCH_BYTES = 128L * 1024 * 1024;
    private final Object lock = new Object();
    private final Source source;
    private final long start;
    private final long length;
    private final long segments;
    private final ExecutorService executor;
    private final Map<Long, Future<byte[]>> pending = new HashMap<Long, Future<byte[]>>();
    private final ArrayList<InputStream> opened = new ArrayList<InputStream>();
    private volatile InputStream primary;
    private final byte[] firstBlock;
    private int firstReady;
    private IOException firstFailure;
    private volatile long delivered;
    private long nextSubmit;
    private long currentSegment;
    private byte[] block;
    private int blockPosition;
    private volatile boolean closed;
    private int activeBackground;
    private boolean prefetchFailed;
    private long lastStatsTime;
    private long lastStatsBytes;
    private long lastScheduledCount;
    private boolean fullWindowReported;
    private final AtomicLong networkReceived = new AtomicLong();
    private final AtomicLong lastNetworkLogNs = new AtomicLong();
    private final AtomicLong lastNetworkLogBytes = new AtomicLong();
    private final long networkStartNs = System.nanoTime();

    public static InputStream maybeWrap(Source source, InputStream primary, long start, long length) {
        if (source == null || primary == null || start < 0 || length < MIN_LENGTH || source.cancelled()) {
            Log.i(TAG, "BYPASS start=" + start + " length=" + length + " eligible=" + (source != null && !source.cancelled()));
            return primary;
        }
        try {
            return new NovaParallelRangeInputStream(source, primary, start, length);
        } catch (RuntimeException ex) {
            Log.w(TAG, "BYPASS init failed start=" + start + " length=" + length, ex);
            return primary;
        }
    }

    private NovaParallelRangeInputStream(Source source, InputStream primary, long start, long length) {
        this.source = source;
        this.primary = primary;
        this.start = start;
        this.length = length;
        this.segments = length / CHUNK + (length % CHUNK == 0 ? 0 : 1);
        this.firstBlock = new byte[segmentSize(0)];
        this.nextSubmit = 0;
        this.lastStatsTime = System.nanoTime();
        this.executor = Executors.newFixedThreadPool(CONCURRENCY, new ThreadFactory() {
            private int number;
            @Override public synchronized Thread newThread(Runnable task) {
                Thread t = new Thread(task, "NovaRange4-" + (++number));
                t.setDaemon(true);
                return t;
            }
        });
        // All four segments are produced on background workers. The first
        // worker reuses Nova's original connection and publishes its bytes as
        // they arrive, so the player never waits for a full 4 MiB block.
        refill();
        Log.i(TAG, "START start=" + start + " length=" + length + " lanes=4 chunk=" + CHUNK
                + " first=background-progressive independent=1 windowBytes=" + MAX_PREFETCH_BYTES);
    }

    private int segmentSize(long index) {
        long remaining = length - index * CHUNK;
        return (int) Math.min(CHUNK, remaining);
    }

    // Fetches continue without waiting for playback. Each completed request
    // immediately frees a slot for the next segment until the unread window is full.
    private void refill() {
        synchronized (lock) { refillLocked(); }
    }

    private void refillLocked() {
        // Four independent producers at all times (including the initial
        // connection); slow or paused playback never holds an HTTP worker.
        while (!closed && !prefetchFailed && activeBackground < CONCURRENCY
                && nextSubmit < segments) {
            final long segment = nextSubmit;
            final long reservedEnd = Math.min(length, (segment + 1) * (long) CHUNK);
            final long unreadReserved = reservedEnd - delivered;
            if (unreadReserved > MAX_PREFETCH_BYTES) {
                if (!fullWindowReported) {
                    fullWindowReported = true;
                    Log.i(TAG, "CAP reached=1 limitBytes=" + MAX_PREFETCH_BYTES
                            + " reservedAhead=" + (reservedEnd - CHUNK - delivered)
                            + " active=" + activeBackground
                            + " networkBytes=" + networkReceived.get());
                }
                return;
            }
            if (fullWindowReported) {
                fullWindowReported = false;
                Log.i(TAG, "CAP reached=0 resumed=1 pending=" + pending.size());
            }
            ++nextSubmit;
            ++activeBackground;
            ++lastScheduledCount;
            try {
                Future<byte[]> job = executor.submit(new Callable<byte[]>() {
                    @Override public byte[] call() throws Exception {
                        boolean succeeded = false;
                        try {
                            byte[] bytes = download(segment);
                            succeeded = true;
                            return bytes;
                        } catch (Exception problem) {
                            synchronized (lock) {
                                if (segment == 0) {
                                    firstFailure = problem instanceof IOException
                                            ? (IOException) problem
                                            : new IOException("First Range4 segment failed", problem);
                                    lock.notifyAll();
                                }
                            }
                            throw problem;
                        } finally {
                            synchronized (lock) {
                                --activeBackground;
                                if (!succeeded) prefetchFailed = true;
                                // Every completed GET replenishes the pool immediately.
                                refillLocked();
                            }
                        }
                    }
                });
                pending.put(segment, job);
                Log.i(TAG, "PUMP segment=" + segment + " running=" + activeBackground
                        + " reservedAhead=" + unreadReserved + " limit=" + MAX_PREFETCH_BYTES);
            } catch (java.util.concurrent.RejectedExecutionException problem) {
                --activeBackground;
                prefetchFailed = true;
                Log.e(TAG, "SCHEDULER_FAILED segment=" + segment, problem);
                return;
            }
        }
    }

    private byte[] download(long segment) throws IOException {
        final long absolute = start + segment * CHUNK;
        final int expected = segmentSize(segment);
        final byte[] data = segment == 0 ? firstBlock : new byte[expected];
        final long started = System.nanoTime();
        int position = 0;
        int attempts = 0;
        while (position < expected) {
            checkActive();
            InputStream input = null;
            try {
                if (segment == 0 && position == 0 && attempts == 0) {
                    input = primary;  // already-open original WebDAV GET
                } else {
                    input = source.openRange(absolute + position);
                }
                if (input == null) throw new IOException("null WebDAV input");
                synchronized (lock) {
                    if (closed) { input.close(); throw new IOException("prefetch closed"); }
                    opened.add(input);
                }
                Log.i(TAG, "OPEN segment=" + segment + " offset=" + (absolute + position)
                        + " wanted=" + (expected - position) + " thread=" + Thread.currentThread().getName());
                while (position < expected) {
                    checkActive();
                    int amount = input.read(data, position, Math.min(128 * 1024, expected - position));
                    if (amount < 0) throw new EOFException("early end at byte " + (absolute + position));
                    if (amount == 0) continue;
                    position += amount;
                    recordNetworkBytes(amount);
                    if (segment == 0) {
                        synchronized (lock) {
                            firstReady = position;
                            lock.notifyAll();
                        }
                    }
                }
            } catch (IOException error) {
                if (closed || source.cancelled()) throw error;
                if (++attempts > 2) {
                    Log.e(TAG, "FAIL segment=" + segment + " offset=" + (absolute + position), error);
                    throw error;
                }
                Log.w(TAG, "RETRY segment=" + segment + " byte=" + (absolute + position)
                        + " attempt=" + attempts, error);
            } finally {
                if (input != null) {
                    synchronized (lock) { opened.remove(input); }
                    try { input.close(); } catch (IOException ignored) { }
                    if (segment == 0 && input == primary) primary = null;
                }
            }
        }
        long elapsedMs = Math.max(1L, (System.nanoTime() - started) / 1000000L);
        Log.i(TAG, "DONE segment=" + segment + " offset=" + absolute + " bytes=" + expected
                + " ms=" + elapsedMs + " speedKBps=" + ((long) expected * 1000 / elapsedMs / 1024));
        return data;
    }

    // Count bytes received from actual upstream InputStream reads, not bytes
    // consumed by the player. NET4 reports simultaneous fetchers and aggregate
    // receive throughput; DELIVER is only localhost/player throughput.
    private void recordNetworkBytes(int amount) {
        long total = networkReceived.addAndGet(amount);
        long now = System.nanoTime();
        long last = lastNetworkLogNs.get();
        if (last == 0L) {
            lastNetworkLogNs.compareAndSet(0L, networkStartNs);
            return;
        }
        if (now - last < 1000000000L ||
                !lastNetworkLogNs.compareAndSet(last, now)) return;
        long previous = lastNetworkLogBytes.getAndSet(total);
        long delta = Math.max(0L, total - previous);
        long elapsed = Math.max(1L, (now - last) / 1000000L);
        int active;
        long reservedAhead;
        synchronized (lock) {
            active = activeBackground;
            reservedAhead = Math.max(0L,
                    Math.min(length, nextSubmit * (long) CHUNK) - delivered);
        }
        Log.i(TAG, "NET4 totalKBps=" + (delta * 1000 / elapsed / 1024)
                + " active=" + active + " connectionsMax=4"
                + " receivedBytes=" + total + " deliveredBytes=" + delivered
                + " reservedAhead=" + reservedAhead
                + " stageCapBytes=" + MAX_PREFETCH_BYTES);
    }

    private void checkActive() throws IOException {
        if (closed || source.cancelled()) {
            close();
            throw new IOException("WebDAV Range4 request cancelled");
        }
    }

    @Override public synchronized int read() throws IOException {
        byte[] one = new byte[1];
        int n = read(one, 0, 1);
        return n < 0 ? -1 : one[0] & 0xff;
    }

    @Override public synchronized int read(byte[] target, int offset, int count) throws IOException {
        try {
            return readInternal(target, offset, count);
        } catch (IOException problem) {
            Log.w(TAG, "FALLBACK to legacy single-stream recovery delivered=" + delivered, problem);
            close();
            throw problem;
        }
    }

    private int readInternal(byte[] target, int offset, int count) throws IOException {
        if (target == null) throw new NullPointerException("target");
        if (offset < 0 || count < 0 || offset > target.length - count)
            throw new IndexOutOfBoundsException();
        if (count == 0) return 0;
        if (delivered >= length) return -1;
        checkActive();
        int n;
        if (delivered < firstBlock.length) {
            // Reader only consumes already-produced bytes. Producer runs even
            // when this method is never called.
            synchronized (lock) {
                while (firstReady <= delivered && firstFailure == null && !closed) {
                    try {
                        lock.wait();
                    } catch (InterruptedException interrupted) {
                        Thread.currentThread().interrupt();
                        throw new IOException("Interrupted waiting for first Range4 bytes", interrupted);
                    }
                }
                if (firstReady <= delivered) {
                    if (firstFailure != null) throw firstFailure;
                    throw new IOException("Range4 first segment closed before data available");
                }
                n = Math.min(count, firstReady - (int) delivered);
                System.arraycopy(firstBlock, (int) delivered, target, offset, n);
                delivered += n;
                if (delivered == firstBlock.length) pending.remove(0);
            }
        } else {
            if (block == null || blockPosition >= block.length) {
                long segment = delivered / CHUNK;
                currentSegment = segment;
                Future<byte[]> future;
                synchronized (lock) { future = pending.remove(segment); }
                if (future == null) throw new IOException("Range4 missing segment " + segment);
                try {
                    block = future.get();
                } catch (InterruptedException ex) {
                    Thread.currentThread().interrupt();
                    throw new IOException("Range4 interrupted", ex);
                } catch (ExecutionException ex) {
                    Throwable cause = ex.getCause();
                    Log.e(TAG, "FALLBACK segment=" + segment + " delivered=" + delivered, cause);
                    throw new IOException("Range4 segment download failed", cause);
                }
                blockPosition = 0;
                if (block.length != segmentSize(segment)) throw new IOException("Range4 corrupt segment size");
                refill();
            }
            n = Math.min(count, block.length - blockPosition);
            System.arraycopy(block, blockPosition, target, offset, n);
            blockPosition += n;
            delivered += n;
            if (blockPosition == block.length) {
                block = null;
                blockPosition = 0;
                currentSegment = delivered / CHUNK;
                refill();
            }
        }
        // Reader progress releases prefetch capacity; it does not gate producers.
        refill();
        if (delivered - lastStatsBytes >= 8L * 1024 * 1024) {
            long now = System.nanoTime();
            long dt = Math.max(1L, (now - lastStatsTime) / 1000000L);
            Log.i(TAG, "DELIVER bytes=" + delivered + " speedKBps="
                    + ((delivered - lastStatsBytes) * 1000 / dt / 1024)
                    + " queued=" + pending.size() + " issued=" + lastScheduledCount);
            lastStatsBytes = delivered;
            lastStatsTime = now;
        }
        if (delivered >= length) close();
        return n;
    }

    @Override public void close() throws IOException {
        ArrayList<InputStream> closing;
        synchronized (lock) {
            if (closed) return;
            closed = true;
            for (Future<byte[]> future : pending.values()) future.cancel(true);
            pending.clear();
            closing = new ArrayList<InputStream>(opened);
            opened.clear();
            lock.notifyAll();
        }
        executor.shutdownNow();
        InputStream first = primary;
        primary = null;
        if (first != null) try { first.close(); } catch (IOException ignored) { }
        for (InputStream input : closing) {
            try { input.close(); } catch (IOException ignored) { }
        }
        long dt = Math.max(1L, (System.nanoTime() - networkStartNs) / 1000000L);
        long net = networkReceived.get();
        Log.i(TAG, "NET4_FINAL receivedBytes=" + net + " totalKBps="
                + (net * 1000 / dt / 1024) + " deliveredBytes=" + delivered
                + " elapsedMs=" + dt);
        Log.i(TAG, "CLOSE delivered=" + delivered + " length=" + length);
    }
}
