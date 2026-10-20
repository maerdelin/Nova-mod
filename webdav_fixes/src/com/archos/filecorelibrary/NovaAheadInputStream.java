package com.archos.filecorelibrary;

import android.util.Log;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

/** One continuous response, one producer, a bounded FIFO. No HTTP request creation.
 * The owning HttpSession publishes this wrapper and closes it on seek/exit/retry.
 * Native AVOS 2X/5X/10X buffering is separate and remains unchanged.
 */
public final class NovaAheadInputStream extends InputStream {
    private static final String TAG = "NOVA_READAHEAD";
    private static final int WINDOW = 16 * 1024 * 1024;
    private static final int STEP = 64 * 1024;
    private static final long BUDGET = Math.min(32L * 1024 * 1024,
            Math.max(STEP, Runtime.getRuntime().maxMemory() / 4));
    private static long allocated;
    private static final AtomicLong IDS = new AtomicLong();
    private final long id = IDS.incrementAndGet();
    private final InputStream source;
    private final long start, length;
    private final int capacity;
    private final Thread producer;
    private final AtomicBoolean sourceClosed = new AtomicBoolean();
    private final Object lock = new Object();
    private byte[] data;
    private int head, count;
    private long received, consumed;
    private boolean closed, done, released;
    private IOException failure;

    /** Small/nonmedia requests are screened by the session. Unknown bounds bypass.
     * Admission is process-bounded, so rapid seeks cannot allocate unbounded FIFOs.
     */
    public static InputStream wrap(InputStream input, long start, long length) {
        if (input == null || input instanceof NovaAheadInputStream || start < 0 ||
                length < STEP || start > Long.MAX_VALUE - length) return input;
        int cap;
        synchronized (NovaAheadInputStream.class) {
            cap = (int)Math.min(Math.min(WINDOW, length), BUDGET - allocated);
            if (cap < STEP) {
                Log.w(TAG, "BYPASS reason=memory_budget singleResponse=1");
                return input;
            }
            allocated += cap;
        }
        try { return new NovaAheadInputStream(input, start, length, cap); }
        catch (OutOfMemoryError allocation) {
            release(cap);
            Log.w(TAG, "BYPASS reason=allocation singleResponse=1");
            return input;
        } catch (RuntimeException initialization) {
            release(cap);
            Log.w(TAG, "BYPASS reason=initialization singleResponse=1", initialization);
            return input;
        }
    }

    private static synchronized void release(int cap) { allocated -= cap; }

    private NovaAheadInputStream(InputStream input, long start, long length, int cap) {
        this.source = input; this.start = start; this.length = length;
        this.capacity = cap; this.data = new byte[cap];
        producer = new Thread(new Runnable() { public void run() { pump(); } }, "Nova-Ahead-" + id);
        producer.setDaemon(true);
        Log.i(TAG, "START id=" + id + " start=" + start + " length=" + length
                + " workers=1 rangePartitioning=0 capacityBytes=" + cap);
        producer.start();
    }

    private void pump() {
        IOException error = null;
        long previous = 0, sampled = System.nanoTime();
        try {
            for (;;) {
                final int tail, wanted;
                final byte[] target;
                synchronized (lock) {
                    if (!closed && count == capacity && received < length) {
                        Log.i(TAG, stats("FULL"));
                        while (!closed && count == capacity) lock.wait();
                        if (!closed) Log.i(TAG, stats("RESUME"));
                    }
                    if (closed || received == length) break;
                    tail = (head + count) % capacity;
                    wanted = (int)Math.min(length - received,
                            Math.min(STEP, Math.min(capacity - count, capacity - tail)));
                    target = data;
                }
                // There is exactly one source.read caller. No reads under lock.
                int n = source.read(target, tail, wanted);
                if (n < 0) throw new EOFException("Response ended before expected bytes");
                if (n == 0 || n > wanted) throw new IOException("Invalid upstream read count");
                synchronized (lock) {
                    if (closed) break;
                    received += n; count += n; lock.notifyAll();
                    long now = System.nanoTime();
                    if (now - sampled >= 1000000000L) {
                        long ms = Math.max(1L, (now - sampled) / 1000000L);
                        Log.i(TAG, stats("NET") + " totalKiBps=" +
                                ((received - previous) * 1000 / ms / 1024));
                        previous = received; sampled = now;
                    }
                }
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            error = new IOException("Prefetch producer interrupted", interrupted);
        } catch (IOException problem) { error = problem; }
          catch (RuntimeException problem) { error = new IOException("Prefetch producer failed", problem); }
        finally {
            // Close the old response before publishing terminal state to retry logic.
            closeSource();
            synchronized (lock) {
                if (!closed) failure = error;
                done = true;
                if (closed || count == 0) releaseLocked();
                Log.i(TAG, stats("PRODUCER_DONE") + " failed=" + (error != null && !closed));
                lock.notifyAll();
            }
        }
    }

    private String stats(String event) {
        return event + " id=" + id + " start=" + start + " receivedBytes=" + received
                + " deliveredBytes=" + consumed + " bufferedBytes=" + count
                + " capacityBytes=" + capacity + " closed=" + closed;
    }

    private void closeSource() {
        if (sourceClosed.compareAndSet(false, true)) {
            try { source.close(); }
            catch (IOException ignored) { }
            catch (RuntimeException ignored) { }
        }
    }

    private void releaseLocked() {
        if (!released) { data = null; released = true; release(capacity); }
    }

    @Override public int read(byte[] output, int offset, int length) throws IOException {
        if (output == null) throw new NullPointerException("output");
        if (offset < 0 || length < 0 || offset > output.length - length)
            throw new IndexOutOfBoundsException();
        if (length == 0) return 0;
        synchronized (lock) {
            while (count == 0 && !done && !closed) {
                try { lock.wait(); }
                catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    throw new IOException("Prefetch consumer interrupted", interrupted);
                }
            }
            if (closed) throw new IOException("Prefetch session closed");
            if (count == 0) {
                if (failure != null) throw failure;
                return -1;
            }
            int n = Math.min(length, Math.min(count, capacity - head));
            System.arraycopy(data, head, output, offset, n);
            head = (head + n) % capacity; count -= n; consumed += n;
            if (done && count == 0) releaseLocked();
            lock.notifyAll();
            return n;
        }
    }
    @Override public int read() throws IOException {
        byte[] b = new byte[1]; int n = read(b, 0, 1); return n < 0 ? -1 : b[0] & 255;
    }
    @Override public int available() throws IOException {
        synchronized (lock) { if (closed) throw new IOException("Prefetch closed"); return count; }
    }
    @Override public void close() {
        synchronized (lock) {
            if (closed) return;
            closed = true; count = 0; lock.notifyAll();
            if (done) releaseLocked();
            Log.i(TAG, stats("CLOSE"));
        }
        producer.interrupt();
        closeSource();
    }
    // Observability for final-APK/JVM probes; no player state is consulted.
    public long receivedBytes() { synchronized (lock) { return received; } }
    public long deliveredBytes() { synchronized (lock) { return consumed; } }
    public int capacityBytes() { return capacity; }
    public boolean producerDone() { synchronized (lock) { return done; } }
}
