// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
package com.archos.filecorelibrary;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.Closeable;
import java.io.IOException;
import java.io.InputStream;

/**
 * Persistent byte-addressed playback cache for StreamOverHttp.
 *
 * Unlike a PipedInputStream read-ahead wrapper this cache survives localhost HTTP
 * range churn. The producer owns one upstream range at a time while HTTP sessions
 * get lightweight readers at absolute file positions.
 */
final class PlaybackFileCache implements Closeable {
    private static final Logger log = LoggerFactory.getLogger(PlaybackFileCache.class);

    private static final int MIB = 1024 * 1024;
    private static final int IO_CHUNK = 256 * 1024;
    private static final int MAX_RETRIES = 3;
    private static final long RETRY_DELAY_MS = 500;

    interface SourceOpener {
        InputStream open(long offset) throws Exception;
    }

    static PlaybackFileCache create(long length, SourceOpener opener) {
        long maxHeap = Runtime.getRuntime().maxMemory();
        int capacity = (int)Math.max(32L * MIB, Math.min(128L * MIB, maxHeap / 8));
        capacity = Math.max(32 * MIB, (capacity / MIB) * MIB);
        int back = capacity / 4;
        int initial = Math.min(32 * MIB, capacity / 2);
        int low = Math.min(4 * MIB, Math.max(MIB, capacity / 16));
        int high = Math.min(24 * MIB, Math.max(8 * MIB, capacity / 3));
        if (high >= capacity - back) high = Math.max(low + MIB, (capacity - back) / 2);
        return new PlaybackFileCache(length, opener, capacity, back, initial, low, high);
    }

    private final Object lock = new Object();
    private final long length;
    private final SourceOpener opener;
    private final byte[] ring;
    private final int capacity;
    private final int backReserve;
    private final int initialTarget;
    private final int lowWater;
    private final int highWater;
    private final Thread producerThread;

    private boolean closed;
    private boolean producerEnabled;
    private boolean sourceEof;
    private IOException failure;
    private InputStream source;
    private long sourceGeneration;
    private long generation = 1;
    private long windowStart;
    private long writePos;
    private long activeReadPos;
    private int retryCount;
    private long producedSinceRebase;
    private long nextStat = 4L * MIB;

    PlaybackFileCache(long length, SourceOpener opener, int capacity, int backReserve,
                      int initialTarget, int lowWater, int highWater) {
        if (length <= 0) throw new IllegalArgumentException("length");
        if (opener == null) throw new NullPointerException("opener");
        if (capacity < 2 * MIB || backReserve < 0 || backReserve >= capacity)
            throw new IllegalArgumentException("capacity/backReserve");
        if (initialTarget <= 0 || initialTarget > capacity - backReserve)
            throw new IllegalArgumentException("initialTarget");
        if (lowWater <= 0 || highWater <= lowWater || highWater > capacity - backReserve)
            throw new IllegalArgumentException("watermarks");
        this.length = length;
        this.opener = opener;
        this.capacity = capacity;
        this.backReserve = backReserve;
        this.initialTarget = initialTarget;
        this.lowWater = lowWater;
        this.highWater = highWater;
        this.ring = new byte[capacity];
        this.producerThread = new Thread(this::producerLoop, "Nova playback cache");
        this.producerThread.setDaemon(true);
        this.producerThread.start();
        log.info("CACHE_CREATE cap={}MiB back={}MiB initial={}MiB low={}MiB high={}MiB",
                capacity / MIB, backReserve / MIB, initialTarget / MIB,
                lowWater / MIB, highWater / MIB);
    }

    InputStream open(long start, long endInclusive, boolean prefill) throws IOException {
        if (start < 0 || start >= length) throw new IOException("Invalid cache start " + start);
        if (endInclusive < start || endInclusive >= length) endInclusive = length - 1;

        InputStream stale = null;
        long readerGeneration;
        synchronized (lock) {
            checkOpenLocked();
            if (start < windowStart || start > writePos) {
                stale = rebaseLocked(start, "range-miss");
            } else if (sourceEof && start == writePos && start < length) {
                stale = rebaseLocked(start, "resume-after-eof");
            }
            activeReadPos = start;
            producerEnabled = true;
            sourceEof = false;
            readerGeneration = generation;
            lock.notifyAll();
        }
        closeQuietly(stale);
        producerThread.interrupt();

        if (prefill) {
            long remaining = endInclusive - start + 1;
            long target = Math.min((long)initialTarget, remaining);
            awaitLevel(start, target, readerGeneration, "initial");
        }
        return new CacheInputStream(start, endInclusive, readerGeneration);
    }

    private InputStream rebaseLocked(long start, String reason) {
        InputStream stale = source;
        source = null;
        sourceGeneration = 0;
        generation++;
        windowStart = start;
        writePos = start;
        activeReadPos = start;
        sourceEof = false;
        failure = null;
        retryCount = 0;
        producedSinceRebase = 0;
        nextStat = 4L * MIB;
        producerEnabled = true;
        log.info("CACHE_REBASE reason={} start={} generation={}", reason, start, generation);
        lock.notifyAll();
        return stale;
    }

    private void producerLoop() {
        byte[] temp = new byte[IO_CHUNK];
        while (true) {
            InputStream current;
            long gen;
            long offset;
            int toRead;
            synchronized (lock) {
                while (true) {
                    if (closed) return;
                    evictLocked();
                    long free = capacity - (writePos - windowStart);
                    if (producerEnabled && !sourceEof && free > 0) {
                        gen = generation;
                        offset = writePos;
                        current = source;
                        toRead = (int)Math.min((long)temp.length, free);
                        break;
                    }
                    waitLocked();
                }
            }

            if (current == null) {
                InputStream opened = null;
                IOException openError = null;
                try {
                    opened = openAt(offset);
                } catch (IOException e) {
                    openError = e;
                }
                synchronized (lock) {
                    if (closed) {
                        closeQuietly(opened);
                        return;
                    }
                    if (gen != generation) {
                        closeQuietly(opened);
                        continue;
                    }
                    if (openError != null) {
                        if (!scheduleRetryLocked(openError, "open", offset, gen)) return;
                        continue;
                    }
                    source = opened;
                    sourceGeneration = gen;
                    retryCount = 0;
                    log.info("CACHE_SOURCE_OPEN offset={} generation={}", offset, gen);
                    lock.notifyAll();
                }
                continue;
            }

            int n;
            try {
                n = current.read(temp, 0, toRead);
            } catch (IOException e) {
                synchronized (lock) {
                    if (gen != generation || current != source) continue;
                    source = null;
                    sourceGeneration = 0;
                    closeQuietly(current);
                    if (!scheduleRetryLocked(e, "read", writePos, gen)) return;
                }
                continue;
            }

            synchronized (lock) {
                if (gen != generation || current != source) continue;
                if (n < 0) {
                    source = null;
                    sourceGeneration = 0;
                    closeQuietly(current);
                    if (writePos < length) {
                        IOException premature = new IOException(
                                "Upstream EOF at " + writePos + " before " + length);
                        if (!scheduleRetryLocked(premature, "eof", writePos, gen)) return;
                    } else {
                        sourceEof = true;
                        producerEnabled = false;
                        log.info("CACHE_SOURCE_EOF pos={} generation={}", writePos, gen);
                        lock.notifyAll();
                    }
                    continue;
                }
                if (n == 0) continue;
                copyIntoRingLocked(temp, n);
                writePos += n;
                producedSinceRebase += n;
                retryCount = 0;
                if (producedSinceRebase >= nextStat) {
                    nextStat += 4L * MIB;
                    log.info("CACHE_STAT start={} read={} write={} forward={}MiB window={}MiB generation={}",
                            windowStart, activeReadPos, writePos,
                            Math.max(0, writePos - activeReadPos) / MIB,
                            (writePos - windowStart) / MIB, generation);
                }
                lock.notifyAll();
            }
        }
    }

    private boolean scheduleRetryLocked(IOException error, String phase, long offset, long gen) {
        if (closed || gen != generation) return true;
        if (++retryCount > MAX_RETRIES) {
            failure = error;
            producerEnabled = false;
            log.warn("CACHE_SOURCE_FAIL phase={} offset={} attempts={}", phase, offset, MAX_RETRIES, error);
            lock.notifyAll();
            return true;
        }
        log.warn("CACHE_SOURCE_RETRY phase={} offset={} attempt={}", phase, offset, retryCount, error);
        long retryGeneration = generation;
        lock.notifyAll();
        try {
            lock.wait(RETRY_DELAY_MS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        return !closed && retryGeneration == generation;
    }

    private InputStream openAt(long offset) throws IOException {
        try {
            return opener.open(offset);
        } catch (IOException e) {
            throw e;
        } catch (Exception e) {
            throw new IOException("Unable to open upstream at " + offset, e);
        }
    }

    private void evictLocked() {
        long used = writePos - windowStart;
        if (used < capacity) return;
        long keepFrom = Math.max(windowStart, activeReadPos - backReserve);
        if (keepFrom > windowStart) {
            windowStart = Math.min(keepFrom, writePos);
            lock.notifyAll();
        }
    }

    private void copyIntoRingLocked(byte[] src, int len) {
        int index = index(writePos);
        int first = Math.min(len, capacity - index);
        System.arraycopy(src, 0, ring, index, first);
        if (first < len) System.arraycopy(src, first, ring, 0, len - first);
    }

    private void copyOutLocked(long position, byte[] dst, int off, int len) {
        int index = index(position);
        int first = Math.min(len, capacity - index);
        System.arraycopy(ring, index, dst, off, first);
        if (first < len) System.arraycopy(ring, 0, dst, off + first, len - first);
    }

    private int index(long absolutePosition) {
        return (int)(absolutePosition % capacity);
    }

    private void awaitLevel(long position, long target, long expectedGeneration, String reason)
            throws IOException {
        boolean logged = false;
        synchronized (lock) {
            for (;;) {
                checkReaderStateLocked(position, expectedGeneration);
                long available = writePos - position;
                if (available >= target || sourceEof || position + available >= length) {
                    if (logged || "initial".equals(reason)) {
                        log.info("CACHE_{}_READY pos={} buffered={}MiB target={}MiB generation={}",
                                reason.toUpperCase(), position, available / MIB, target / MIB, generation);
                    }
                    return;
                }
                if (failure != null && available == 0) throw failure;
                if (!logged) {
                    log.info("CACHE_{}_WAIT pos={} buffered={}KiB target={}MiB generation={}",
                            reason.toUpperCase(), position, available / 1024, target / MIB, generation);
                    logged = true;
                }
                waitReaderLocked();
            }
        }
    }

    private void checkReaderStateLocked(long position, long expectedGeneration) throws IOException {
        checkOpenLocked();
        if (expectedGeneration != generation)
            throw new IOException("Playback cache generation changed");
        if (position < windowStart)
            throw new IOException("Playback cache reader fell behind window");
    }

    private void checkOpenLocked() throws IOException {
        if (closed) throw new IOException("Playback cache closed");
    }

    private void waitReaderLocked() throws IOException {
        try {
            lock.wait();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IOException("Interrupted waiting for playback cache", e);
        }
    }

    private void waitLocked() {
        try {
            lock.wait();
        } catch (InterruptedException ignored) {
            // Re-check state. Rebase/close deliberately interrupts the producer.
        }
    }

    @Override
    public void close() {
        InputStream stale;
        synchronized (lock) {
            if (closed) return;
            closed = true;
            generation++;
            stale = source;
            source = null;
            producerEnabled = false;
            lock.notifyAll();
        }
        closeQuietly(stale);
        producerThread.interrupt();
        log.info("CACHE_CLOSE");
    }

    private static void closeQuietly(InputStream input) {
        if (input == null) return;
        try {
            input.close();
        } catch (Exception ignored) {
        }
    }

    private final class CacheInputStream extends InputStream {
        private long position;
        private final long endInclusive;
        private final long readerGeneration;
        private boolean streamClosed;
        private boolean started;
        private boolean rebuffering;

        CacheInputStream(long start, long endInclusive, long readerGeneration) {
            this.position = start;
            this.endInclusive = endInclusive;
            this.readerGeneration = readerGeneration;
        }

        @Override
        public int read() throws IOException {
            byte[] one = new byte[1];
            int n = read(one, 0, 1);
            return n < 0 ? -1 : one[0] & 0xff;
        }

        @Override
        public int read(byte[] b, int off, int len) throws IOException {
            if (b == null) throw new NullPointerException("b");
            if (off < 0 || len < 0 || len > b.length - off) throw new IndexOutOfBoundsException();
            if (len == 0) return 0;
            synchronized (lock) {
                if (streamClosed) throw new IOException("Cache reader closed");
                if (position > endInclusive) return -1;

                for (;;) {
                    checkReaderStateLocked(position, readerGeneration);
                    long available = writePos - position;
                    long remaining = endInclusive - position + 1;
                    if (available > 0) {
                        long target = Math.min((long)highWater, remaining);
                        if (started && available < lowWater && remaining > available && !sourceEof) {
                            if (!rebuffering) {
                                rebuffering = true;
                                log.info("CACHE_LOW_WATER pos={} buffered={}KiB refill={}MiB generation={}",
                                        position, available / 1024, target / MIB, generation);
                            }
                            if (available < target) {
                                waitReaderLocked();
                                continue;
                            }
                            log.info("CACHE_REFILLED pos={} buffered={}MiB generation={}",
                                    position, available / MIB, generation);
                            rebuffering = false;
                        }

                        int count = (int)Math.min((long)len, Math.min(available, remaining));
                        copyOutLocked(position, b, off, count);
                        position += count;
                        activeReadPos = position;
                        started = true;
                        lock.notifyAll();
                        return count;
                    }
                    if (sourceEof || position >= length) return -1;
                    if (failure != null) throw failure;
                    waitReaderLocked();
                }
            }
        }

        @Override
        public int available() throws IOException {
            synchronized (lock) {
                if (streamClosed) return 0;
                checkReaderStateLocked(position, readerGeneration);
                long available = Math.min(writePos - position, endInclusive - position + 1);
                return (int)Math.max(0, Math.min(Integer.MAX_VALUE, available));
            }
        }

        @Override
        public void close() {
            synchronized (lock) {
                streamClosed = true;
                lock.notifyAll();
            }
        }
    }
}
