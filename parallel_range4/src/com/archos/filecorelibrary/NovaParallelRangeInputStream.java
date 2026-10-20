package com.archos.filecorelibrary;

import android.util.Log;
import java.io.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;
import java.util.regex.*;

/** Ordered, bounded, four-connection WebDAV prefetch. Native demux and Java
 * staging are separate budgets: neither a reservation nor cumulative received
 * bytes is proof that ten seconds of playable data is buffered. */
public final class NovaParallelRangeInputStream extends InputStream {
    public interface Source {
        InputStream openRange(long absoluteOffset) throws IOException;
        boolean cancelled();
    }
    public interface ManagedSource extends Source {
        void publishRange4(InputStream input) throws IOException;
        int capacityPort();
        Object capacityOwner();
    }
    public static final class RequestCancelledException extends IOException {
        public RequestCancelledException(String message, Throwable cause) { super(message, cause); }
    }
    private static final String TAG = "NOVA_RANGE4";
    private static final int CHUNK = 1024 * 1024, CONCURRENCY = 4;
    private static final long MIN_LENGTH = 16L * CHUNK;
    private static final String CAP_PATH = "/data/user/0/org.courville.nova/cache/nova_range4_capacity";
    private static final Pattern ACCESS_STATUS = Pattern.compile(
        "(?i)\\bHTTP(?:\\s+error)?\\s*[:=]?\\s*(401|403)\\b|\\b(401)\\s+Unauthorized\\b|\\b(403)\\s+Forbidden\\b");
    // Proxy ownership survives seeks, but not a different playback session. Weak
    // keys avoid retaining closed players. An accepted budget must survive a seek
    // after the publication file's ten-minute discovery TTL has elapsed.
    private static final Map<Object, long[]> ACCEPTED = new WeakHashMap<Object, long[]>();
    private Object budgetOwner;
    private int budgetPort;
    private final Object lock = new Object();
    private final Source source;
    private final long start, length, segments;
    private final File capacityFile;
    private final ExecutorService executor;
    private final Map<Long, Future<byte[]>> pending = new HashMap<Long, Future<byte[]>>();
    private final ArrayList<InputStream> opened = new ArrayList<InputStream>();
    private final byte[] firstBlock;
    private final AtomicLong networkReceived = new AtomicLong();
    private final long networkStartNs = System.nanoTime();
    private volatile InputStream primary;
    private volatile Thread budgetWatcher;
    private volatile boolean closed, nativeBudgetReceived;
    private volatile long delivered, maxPrefetchBytes = 4L * CHUNK;
    private int firstReady, activeBackground, blockPosition;
    private IOException firstFailure;
    private boolean prefetchFailed, fullWindowReported;
    private long nextSubmit, lastCapacityCheckNs, lastNetworkLogNs = networkStartNs;
    private long lastNetworkLogBytes, lastBadCapacityMtime = Long.MIN_VALUE, lastBadCapacityLength = -1;
    private byte[] block;

    public static InputStream maybeWrap(Source source, InputStream primary, long start, long length) {
        if (source == null || primary == null || start < 0 || length < MIN_LENGTH
                || start > Long.MAX_VALUE - length || source.cancelled()
                || Thread.currentThread().isInterrupted()) {
            Log.i(TAG, "BYPASS start=" + start + " length=" + length);
            return primary;
        }
        int port = source instanceof ManagedSource ? ((ManagedSource) source).capacityPort() : 0;
        // Port is the per-media localhost proxy identity. No global fallback for
        // managed sources: another title's similarly sized file must not match.
        File cap = new File(CAP_PATH + (source instanceof ManagedSource
                ? (port > 0 && port <= 65535 ? "_" + port : "_invalid") : ""));
        Object owner = source instanceof ManagedSource ? ((ManagedSource) source).capacityOwner() : null;
        return new NovaParallelRangeInputStream(source, primary, start, length, cap, owner, port);
    }

    /** Shared production localhost copy loop, also exercised directly by JVM tests.
     * Reconnect only upstream READ errors, at the last successfully written byte.
     * A downstream socket failure must never trigger another upstream GET. */
    public static void copyRecovering(Source source, InputStream input, OutputStream output,
            byte[] buffer, long start, long length) throws IOException {
        if (source == null || input == null || output == null || buffer == null)
            throw new NullPointerException("copy arguments");
        if (buffer.length == 0 || start < 0 || length < 0 || start > Long.MAX_VALUE - length)
            throw new IllegalArgumentException("copy extent/buffer");
        InputStream current = input;
        long offset = start, remaining = length;
        int attempts = 0;
        IOException lastFailure = null;
        try {
            if (!(current instanceof NovaParallelRangeInputStream))
                current = maybeWrap(source, current, offset, remaining);
            publish(source, current);
            while (remaining > 0) {
                if (cancelled(source)) return;
                if (current == null) {
                    if (attempts >= 3) throw lastFailure;
                    if (++attempts > 1) {
                        try { Thread.sleep(500L); }
                        catch (InterruptedException stop) { Thread.currentThread().interrupt(); return; }
                    }
                    if (cancelled(source)) return;
                    try {
                        Log.w(TAG, "RECOVER_RANGE4 byte=" + offset + " attempt=" + attempts);
                        current = source.openRange(offset);
                        if (current == null) throw new IOException("null recovery input");
                        current = maybeWrap(source, current, offset, remaining);
                        publish(source, current);
                    } catch (IOException failure) {
                        closeQuietly(current); current = null;
                        if (cancelled(source) || failureDisposition(failure) == 1) return;
                        if (failureDisposition(failure) == 2) throw failure;
                        lastFailure = failure;
                        continue;
                    }
                }
                final int n;
                try {
                    n = current.read(buffer, 0, (int) Math.min(buffer.length, remaining));
                    if (n < 0) throw new EOFException("WebDAV body ended before expected length");
                    if (n == 0) throw new IOException("WebDAV input made no progress");
                } catch (IOException failure) {
                    if (cancelled(source) || failureDisposition(failure) == 1) {
                        Log.i(TAG, "CANCELLED_COPY byte=" + offset + " reconnect=0"); return;
                    }
                    if (failureDisposition(failure) == 2) {
                        Log.w(TAG, "ACCESS_DENIED_COPY byte=" + offset + " reconnect=0", failure);
                        throw failure;
                    }
                    closeQuietly(current); current = null; lastFailure = failure;
                    continue;
                }
                if (cancelled(source)) return;
                output.write(buffer, 0, n); // intentionally OUTSIDE the reconnect catch
                offset += n; remaining -= n; attempts = 0;
            }
        } finally { closeQuietly(current); }
    }
    private static boolean cancelled(Source source) {
        return source.cancelled() || Thread.currentThread().isInterrupted();
    }
    private static void publish(Source source, InputStream input) throws IOException {
        if (source instanceof ManagedSource) ((ManagedSource) source).publishRange4(input);
        if (cancelled(source)) throw new RequestCancelledException("copy cancelled while publishing", null);
    }
    private static void closeQuietly(InputStream input) {
        if (input != null) try { input.close(); } catch (IOException ignored) { }
    }

    // Injectable file only for package-local regression tests; APK uses app-private path.
    NovaParallelRangeInputStream(Source source, InputStream primary, long start, long length, File cap) {
        this(source, primary, start, length, cap, null, 0);
    }
    private NovaParallelRangeInputStream(Source source, InputStream primary, long start, long length,
                                         File cap, Object owner, int port) {
        if (source == null || primary == null || start < 0 || length <= 0 || start > Long.MAX_VALUE - length)
            throw new IllegalArgumentException("invalid Range4 extent");
        this.source = source; this.primary = primary; this.start = start; this.length = length;
        capacityFile = cap;
        budgetOwner = owner; budgetPort = port;
        if (owner != null && port > 0 && port <= 65535) {
            synchronized (ACCEPTED) {
                long[] prior = ACCEPTED.get(owner);
                if (prior != null && prior[0] == port && prior[1] == start + length) {
                    maxPrefetchBytes = prior[2]; nativeBudgetReceived = true;
                    Log.i(TAG, "CAP_SESSION_REUSE capacity=" + maxPrefetchBytes + " sourcePort=" + port);
                }
            }
        }
        segments = length / CHUNK + (length % CHUNK == 0 ? 0 : 1);
        firstBlock = new byte[segmentSize(0)];
        executor = Executors.newFixedThreadPool(CONCURRENCY, new ThreadFactory() {
            private int number;
            public synchronized Thread newThread(Runnable task) {
                Thread t = new Thread(task, "NovaRange4-" + (++number)); t.setDaemon(true); return t;
            }
        });
        refill();
        budgetWatcher = new Thread(new Runnable() {
            public void run() {
                long warningAt = System.nanoTime() + 30_000_000_000L;
                boolean warned = false;
                while (!closed && !nativeBudgetReceived && !source.cancelled()) {
                    try { Thread.sleep(200L); } catch (InterruptedException stop) { return; }
                    refill();
                    if (!warned && !nativeBudgetReceived && System.nanoTime() >= warningAt) {
                        warned = true;
                        Log.w(TAG, "CAP_METADATA_PENDING provisional=" + maxPrefetchBytes + " stillWatching=1");
                    }
                }
                if (source.cancelled()) closeQuietly(NovaParallelRangeInputStream.this);
            }
        }, "NovaRange4-CapWatch");
        budgetWatcher.setDaemon(true);
        if (!closed) budgetWatcher.start();
        Log.i(TAG, "START start=" + start + " length=" + length + " lanes=4 chunk=" + CHUNK
                + " first=background-progressive independent=1 windowBytes=" + maxPrefetchBytes);
    }
    private int segmentSize(long index) { return (int) Math.min(CHUNK, length - index * CHUNK); }
    private long scheduledBytes() { return nextSubmit == segments ? length : nextSubmit * CHUNK; }
    private void refill() { synchronized (lock) { refillLocked(); } }

    static long[] parseCapacityRecord(String record) {
        if (record == null || record.length() > 128) return null;
        String clean = record.trim();
        // Old native code wrote two literal characters, not a newline. trim alone cannot fix it.
        if (clean.endsWith("\\n")) clean = clean.substring(0, clean.length() - 2).trim();
        String[] parts = clean.split("\\s+");
        if (parts.length != 2 || !parts[0].matches("[0-9]+") || !parts[1].matches("[0-9]+")) return null;
        try {
            long size = Long.parseLong(parts[0]), cap = Long.parseLong(parts[1]);
            if (size <= 0 || cap <= 0 || cap > Integer.MAX_VALUE / 2) return null;
            return new long[] {size, cap};
        } catch (NumberFormatException invalid) { return null; }
    }
    private void updateCapacityLocked() {
        if (closed || nativeBudgetReceived) return;
        long now = System.nanoTime();
        if (lastCapacityCheckNs != 0 && now - lastCapacityCheckNs < 200_000_000L) return;
        lastCapacityCheckNs = now;
        long modified = capacityFile.lastModified(), age = System.currentTimeMillis() - modified;
        if (!capacityFile.isFile() || age < -2000L || age > 600_000L) return;
        try (BufferedReader reader = new BufferedReader(new FileReader(capacityFile))) {
            char[] chars = new char[129]; int count = 0;
            while (count < chars.length) {
                int n = reader.read(chars, count, chars.length - count);
                if (n <= 0) break; count += n;
            }
            long[] parsed = parseCapacityRecord(new String(chars, 0, count));
            if (parsed == null) { badCapacity(modified, "CAP_NATIVE_RECORD_REJECTED", null); return; }
            if (parsed[0] != start + length) return;
            maxPrefetchBytes = Math.max(CHUNK, parsed[1]);
            nativeBudgetReceived = true; fullWindowReported = false;
            if (budgetOwner != null && budgetPort > 0 && budgetPort <= 65535) {
                synchronized (ACCEPTED) {
                    if (ACCEPTED.size() >= 32 && !ACCEPTED.containsKey(budgetOwner))
                        ACCEPTED.remove(ACCEPTED.keySet().iterator().next());
                    ACCEPTED.put(budgetOwner, new long[] {budgetPort, parsed[0], maxPrefetchBytes});
                }
            }
            Log.i(TAG, "CAP_NATIVE_10X size=" + parsed[0] + " capacity=" + parsed[1]
                    + " effectiveCapBytes=" + maxPrefetchBytes + " start=" + start
                    + " alreadyReserved=" + (scheduledBytes() - delivered));
        } catch (IOException failure) { badCapacity(modified, "CAP_NATIVE_READ_FAILED", failure); }
    }
    private void badCapacity(long modified, String message, IOException failure) {
        if (modified == lastBadCapacityMtime && capacityFile.length() == lastBadCapacityLength) return;
        lastBadCapacityMtime = modified; lastBadCapacityLength = capacityFile.length();
        Log.w(TAG, message + " retaining=" + maxPrefetchBytes, failure);
    }
    private void refillLocked() {
        if (closed || source.cancelled()) return;
        updateCapacityLocked();
        while (!closed && !prefetchFailed && activeBackground < CONCURRENCY && nextSubmit < segments) {
            final long segment = nextSubmit;
            final long reservedEnd = segment * CHUNK + segmentSize(segment);
            final long unreadReserved = reservedEnd - delivered;
            if (unreadReserved > maxPrefetchBytes) {
                if (!fullWindowReported) {
                    fullWindowReported = true;
                    Log.i(TAG, "CAP reached=1 limitBytes=" + maxPrefetchBytes
                            + " reservedAhead=" + (scheduledBytes() - delivered)
                            + " active=" + activeBackground + " networkBytes=" + networkReceived.get());
                }
                return;
            }
            if (fullWindowReported) {
                fullWindowReported = false;
                Log.i(TAG, "CAP reached=0 resumed=1 pending=" + pending.size());
            }
            ++nextSubmit; ++activeBackground;
            try {
                Future<byte[]> job = executor.submit(new Callable<byte[]>() {
                    public byte[] call() throws Exception {
                        boolean succeeded = false;
                        try { byte[] bytes = download(segment); succeeded = true; return bytes; }
                        catch (Exception failure) {
                            synchronized (lock) {
                                if (segment == 0) {
                                    firstFailure = failure instanceof IOException ? (IOException) failure
                                            : new IOException("First Range4 segment failed", failure);
                                    lock.notifyAll();
                                }
                            }
                            throw failure;
                        } finally {
                            synchronized (lock) {
                                --activeBackground;
                                if (!succeeded) prefetchFailed = true;
                                refillLocked();
                            }
                        }
                    }
                });
                pending.put(segment, job);
                Log.i(TAG, "PUMP segment=" + segment + " running=" + activeBackground
                        + " reservedAhead=" + unreadReserved + " limit=" + maxPrefetchBytes);
            } catch (RejectedExecutionException failure) {
                --activeBackground; prefetchFailed = true;
                Log.e(TAG, "SCHEDULER_FAILED segment=" + segment, failure); return;
            }
        }
    }
    private byte[] download(long segment) throws IOException {
        final long absolute = start + segment * CHUNK, started = System.nanoTime();
        final int expected = segmentSize(segment);
        final byte[] data = segment == 0 ? firstBlock : new byte[expected];
        int position = 0, attempts = 0;
        while (position < expected) {
            checkActive(); InputStream input = null;
            try {
                input = segment == 0 && position == 0 && attempts == 0 ? primary : source.openRange(absolute + position);
                if (input == null) throw new IOException("null WebDAV input");
                synchronized (lock) {
                    if (closed || source.cancelled()) throw new RequestCancelledException("prefetch cancelled", null);
                    opened.add(input);
                }
                Log.i(TAG, "OPEN segment=" + segment + " offset=" + (absolute + position)
                        + " wanted=" + (expected - position) + " thread=" + Thread.currentThread().getName());
                while (position < expected) {
                    checkActive();
                    int amount = input.read(data, position, Math.min(128 * 1024, expected - position));
                    if (amount < 0) throw new EOFException("early end at byte " + (absolute + position));
                    if (amount == 0) throw new IOException("WebDAV segment made no progress");
                    position += amount; recordNetworkBytes(amount);
                    if (segment == 0) { synchronized (lock) { firstReady = position; lock.notifyAll(); } }
                }
            } catch (IOException failure) {
                if (closed || source.cancelled() || failureDisposition(failure) == 1)
                    throw new RequestCancelledException("Range4 producer cancelled", failure);
                if (failureDisposition(failure) == 2) {
                    Log.e(TAG, "RANGE_ACCESS_DENIED segment=" + segment + " reconnect=0", failure); throw failure;
                }
                if (++attempts > 2) { Log.e(TAG, "FAIL segment=" + segment, failure); throw failure; }
                Log.w(TAG, "RETRY segment=" + segment + " byte=" + (absolute + position) + " attempt=" + attempts, failure);
            } finally {
                if (input != null) {
                    synchronized (lock) { opened.remove(input); }
                    closeQuietly(input);
                    if (segment == 0 && input == primary) primary = null;
                }
            }
        }
        long elapsed = Math.max(1, (System.nanoTime() - started) / 1_000_000L);
        Log.i(TAG, "DONE segment=" + segment + " offset=" + absolute + " bytes=" + expected
                + " ms=" + elapsed + " speedKBps=" + ((long) expected * 1000 / elapsed / 1024));
        return data;
    }
    private void recordNetworkBytes(int amount) {
        networkReceived.addAndGet(amount);
        synchronized (lock) {
            long now = System.nanoTime(), total = networkReceived.get();
            if (now - lastNetworkLogNs < 1_000_000_000L) return;
            long elapsed = Math.max(1, (now - lastNetworkLogNs) / 1_000_000L);
            long rate = Math.max(0, total - lastNetworkLogBytes) * 1000 / elapsed / 1024;
            lastNetworkLogNs = now; lastNetworkLogBytes = total;
            Log.i(TAG, "NET4 totalKBps=" + rate + " active=" + activeBackground
                    + " connections=" + opened.size() + " connectionsMax=4 receivedBytes=" + total
                    + " deliveredBytes=" + delivered + " reservedAhead=" + (scheduledBytes() - delivered)
                    + " bufferedBytes=" + Math.max(0, total - delivered) + " stageCapBytes=" + maxPrefetchBytes);
        }
    }
    public static int failureDisposition(Throwable error) {
        if (Thread.currentThread().isInterrupted()) return 1;
        boolean denied = false;
        for (int depth = 0; error != null && depth < 16; depth++, error = error.getCause()) {
            if (error instanceof RequestCancelledException || error instanceof InterruptedException
                    || error instanceof CancellationException) return 1;
            denied |= accessStatus(error) != 0;
            if (error.getCause() == error) break;
        }
        return denied ? 2 : 0;
    }
    static int accessStatus(Throwable error) {
        try {
            Object status = error.getClass().getMethod("getStatusCode").invoke(error);
            if (status instanceof Number) {
                int code = ((Number) status).intValue(); if (code == 401 || code == 403) return code;
            }
        } catch (ReflectiveOperationException | SecurityException ignored) { }
        String message = error.getMessage();
        if (message != null) {
            Matcher m = ACCESS_STATUS.matcher(message);
            if (m.find()) for (int i = 1; i <= 3; i++) if (m.group(i) != null) return Integer.parseInt(m.group(i));
        }
        return 0;
    }
    private void checkActive() throws IOException {
        if (closed || cancelled(source)) {
            close(); throw new RequestCancelledException("WebDAV Range4 request cancelled", null);
        }
    }
    public synchronized int read() throws IOException {
        byte[] one = new byte[1]; int n = read(one, 0, 1); return n < 0 ? -1 : one[0] & 255;
    }
    public synchronized int read(byte[] target, int offset, int count) throws IOException {
        try { return readInternal(target, offset, count); }
        catch (IOException failure) {
            int type = failureDisposition(failure);
            boolean stopped = closed || source.cancelled() || type == 1;
            if (stopped) Log.i(TAG, "CANCELLED delivered=" + delivered + " reconnect=0");
            else if (type == 2) Log.w(TAG, "ACCESS_DENIED delivered=" + delivered + " reconnect=0", failure);
            else Log.w(TAG, "RECOVERY_REQUIRED delivered=" + delivered, failure);
            close();
            if (stopped && !(failure instanceof RequestCancelledException))
                throw new RequestCancelledException("Range4 cancelled while reading", failure);
            throw failure;
        }
    }
    private int readInternal(byte[] target, int offset, int count) throws IOException {
        if (target == null) throw new NullPointerException("target");
        if (offset < 0 || count < 0 || offset > target.length - count) throw new IndexOutOfBoundsException();
        if (count == 0) return 0;
        if (delivered >= length) return -1;
        checkActive(); int n;
        if (delivered < firstBlock.length) {
            synchronized (lock) {
                while (firstReady <= delivered && firstFailure == null && !closed && !source.cancelled()) {
                    try { lock.wait(200L); }
                    catch (InterruptedException stop) {
                        Thread.currentThread().interrupt(); throw new RequestCancelledException("first segment interrupted", stop);
                    }
                }
                if (closed || source.cancelled()) throw new RequestCancelledException("first segment cancelled", null);
                if (firstReady <= delivered) {
                    if (firstFailure != null) throw firstFailure;
                    throw new IOException("first segment unavailable");
                }
                n = Math.min(count, firstReady - (int) delivered);
                System.arraycopy(firstBlock, (int) delivered, target, offset, n);
                delivered += n;
                if (delivered == firstBlock.length) pending.remove(0L);
            }
        } else {
            if (block == null) {
                long segment = delivered / CHUNK;
                Future<byte[]> future;
                synchronized (lock) {
                    if (closed || source.cancelled())
                        throw new RequestCancelledException("Range4 cancelled before segment lookup", null);
                    future = pending.get(segment);
                }
                if (future == null) throw new IOException("Range4 missing segment " + segment);
                try {
                    for (;;) {
                        checkActive();
                        try { block = future.get(200L, TimeUnit.MILLISECONDS); break; }
                        catch (TimeoutException stillWaiting) { }
                    }
                    checkActive();
                    synchronized (lock) { pending.remove(segment); }
                } catch (InterruptedException stop) {
                    Thread.currentThread().interrupt(); throw new RequestCancelledException("segment interrupted", stop);
                } catch (CancellationException stop) {
                    throw new RequestCancelledException("segment future cancelled", stop);
                } catch (ExecutionException failure) {
                    Throwable cause = failure.getCause();
                    if (cause instanceof IOException) throw (IOException) cause;
                    throw new IOException("Range4 segment failed", cause);
                }
                blockPosition = 0;
                if (block.length != segmentSize(segment)) throw new IOException("Range4 corrupt segment size");
            }
            n = Math.min(count, block.length - blockPosition);
            System.arraycopy(block, blockPosition, target, offset, n);
            blockPosition += n; delivered += n;
            if (blockPosition == block.length) { block = null; blockPosition = 0; }
        }
        refill();
        if (delivered >= length) close();
        return n;
    }
    public void close() throws IOException {
        ArrayList<InputStream> closing; InputStream first;
        synchronized (lock) {
            if (closed) return; closed = true;
            for (Future<byte[]> job : pending.values()) job.cancel(true);
            pending.clear(); closing = new ArrayList<InputStream>(opened); opened.clear();
            first = primary; primary = null; lock.notifyAll();
        }
        Thread watcher = budgetWatcher;
        if (watcher != null && watcher != Thread.currentThread()) watcher.interrupt();
        executor.shutdownNow(); closeQuietly(first);
        for (InputStream input : closing) if (input != first) closeQuietly(input);
        long elapsed = Math.max(1, (System.nanoTime() - networkStartNs) / 1_000_000L), bytes = networkReceived.get();
        Log.i(TAG, "NET4_FINAL receivedBytes=" + bytes + " totalKBps=" + bytes * 1000 / elapsed / 1024
                + " deliveredBytes=" + delivered + " elapsedMs=" + elapsed);
        Log.i(TAG, "CLOSE delivered=" + delivered + " length=" + length);
    }
}
