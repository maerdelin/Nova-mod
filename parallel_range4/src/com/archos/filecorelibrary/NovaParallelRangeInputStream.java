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
    private final Object lock = new Object();
    private final Source source;
    private final long start;
    private final long length;
    private final long segments;
    private final ExecutorService executor;
    private final Map<Long, Future<byte[]>> pending = new HashMap<Long, Future<byte[]>>();
    private final ArrayList<InputStream> opened = new ArrayList<InputStream>();
    private InputStream primary;
    private long delivered;
    private long nextSubmit;
    private long currentSegment;
    private byte[] block;
    private int blockPosition;
    private boolean closed;
    private long lastStatsTime;
    private long lastStatsBytes;
    private long lastScheduledCount;

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
        this.nextSubmit = 1;
        this.lastStatsTime = System.nanoTime();
        this.executor = Executors.newFixedThreadPool(CONCURRENCY, new ThreadFactory() {
            private int number;
            @Override public synchronized Thread newThread(Runnable task) {
                Thread t = new Thread(task, "NovaRange4-" + (++number));
                t.setDaemon(true);
                return t;
            }
        });
        // Segment 0 is read directly from Nova's existing input connection so playback
        // can start immediately. Segments 1..3 are fetched on separate connections.
        schedule(0);
        Log.i(TAG, "START start=" + start + " length=" + length + " lanes=4 chunk=" + CHUNK + " first=direct");
    }

    private int segmentSize(long index) {
        long remaining = length - index * CHUNK;
        return (int) Math.min(CHUNK, remaining);
    }

    private void schedule(long readerSegment) {
        synchronized (lock) {
            if (closed) return;
            // Until the direct first segment is consumed, permit only 3
            // background connections; afterwards permit 4 background requests.
            long exclusive = readerSegment + CONCURRENCY;
            if (exclusive > segments) exclusive = segments;
            while (nextSubmit < exclusive) {
                final long segment = nextSubmit++;
                Future<byte[]> job = executor.submit(new Callable<byte[]>() {
                    @Override public byte[] call() throws Exception { return download(segment); }
                });
                pending.put(segment, job);
                lastScheduledCount++;
            }
        }
    }

    private byte[] download(long segment) throws IOException {
        final long absolute = start + segment * CHUNK;
        final int expected = segmentSize(segment);
        final byte[] data = new byte[expected];
        final long started = System.nanoTime();
        int position = 0;
        int attempts = 0;
        while (position < expected) {
            checkActive();
            InputStream input = null;
            try {
                input = source.openRange(absolute + position);
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
                }
            }
        }
        long elapsedMs = Math.max(1L, (System.nanoTime() - started) / 1000000L);
        Log.i(TAG, "DONE segment=" + segment + " offset=" + absolute + " bytes=" + expected
                + " ms=" + elapsedMs + " speedKBps=" + ((long) expected * 1000 / elapsedMs / 1024));
        return data;
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
        if (delivered < Math.min(CHUNK, length)) {
            int allowed = (int) Math.min(count, Math.min(CHUNK, length) - delivered);
            n = primary.read(target, offset, allowed);
            if (n < 0) throw new EOFException("first WebDAV segment ended early");
            if (n == 0) return 0;
            delivered += n;
            if (delivered >= Math.min(CHUNK, length)) {
                try { primary.close(); } catch (IOException ignored) { }
                primary = null;
                currentSegment = 1;
                schedule(currentSegment);
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
                schedule(segment);
            }
            n = Math.min(count, block.length - blockPosition);
            System.arraycopy(block, blockPosition, target, offset, n);
            blockPosition += n;
            delivered += n;
            if (blockPosition == block.length) {
                block = null;
                blockPosition = 0;
                currentSegment = delivered / CHUNK;
                schedule(currentSegment);
            }
        }
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
        }
        executor.shutdownNow();
        InputStream first = primary;
        primary = null;
        if (first != null) try { first.close(); } catch (IOException ignored) { }
        for (InputStream input : closing) {
            try { input.close(); } catch (IOException ignored) { }
        }
        Log.i(TAG, "CLOSE delivered=" + delivered + " length=" + length);
    }
}
