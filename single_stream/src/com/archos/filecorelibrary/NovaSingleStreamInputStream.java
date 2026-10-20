package com.archos.filecorelibrary;

import android.util.Log;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.concurrent.CancellationException;
import java.util.concurrent.atomic.AtomicLong;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Continuous, ordered upstream body copy. No partitioning, worker pool or staging
 * window. The player's native buffer and the existing HTTP/socket buffers remain.
 * All opens occur on the owning HTTP session thread, only after its old body closes.
 */
public final class NovaSingleStreamInputStream {
    public interface Source {
        InputStream openRange(long absoluteOffset) throws IOException;
        boolean cancelled();
    }
    public interface ManagedSource extends Source {
        void publishSingle(InputStream input) throws IOException;
    }
    public static final class RequestCancelledException extends IOException {
        public RequestCancelledException(String message, Throwable cause) { super(message, cause); }
    }
    private static final String TAG = "NOVA_SINGLE";
    private static final AtomicLong IDS = new AtomicLong();
    private static final Pattern ACCESS_STATUS = Pattern.compile(
        "(?i)\\bHTTP(?:\\s+error)?\\s*[:=]?\\s*(401|403)\\b|\\b(401)\\s+Unauthorized\\b|\\b(403)\\s+Forbidden\\b");
    private NovaSingleStreamInputStream() { }

    public static void copyRecovering(Source source, InputStream input, OutputStream output,
            byte[] buffer, long start, long length) throws IOException {
        if (source == null || input == null || output == null || buffer == null)
            throw new NullPointerException("copy arguments");
        if (buffer.length == 0 || start < 0 || length < 0 || start > Long.MAX_VALUE - length)
            throw new IllegalArgumentException("copy extent/buffer");
        final long id = IDS.incrementAndGet(), began = System.nanoTime();
        long lastLog = began, lastRead = 0, readBytes = 0, delivered = 0;
        long offset = start, remaining = length;
        int attempts = 0, reopens = 0;
        String result = "failed";
        InputStream current = input;
        IOException lastFailure = null;
        Log.i(TAG, "START id=" + id + " start=" + start + " length=" + length
                + " mode=continuous connectionsMax=1 rangePartitioning=0");
        try {
            if (cancelled(source)) { result = "cancelled"; return; }
            publish(source, current);
            while (remaining > 0) {
                if (cancelled(source)) { result = "cancelled"; return; }
                if (current == null) {
                    if (attempts >= 3) throw lastFailure;
                    if (++attempts > 1) {
                        try { Thread.sleep(500L); }
                        catch (InterruptedException stop) {
                            Thread.currentThread().interrupt(); result = "cancelled"; return;
                        }
                    }
                    if (cancelled(source)) { result = "cancelled"; return; }
                    try {
                        Log.w(TAG, "REOPEN id=" + id + " byte=" + offset + " attempt=" + attempts);
                        ++reopens;
                        current = source.openRange(offset);
                        if (current == null) throw new IOException("null recovery input");
                        publish(source, current);
                    } catch (IOException failure) {
                        closeQuietly(current); current = null;
                        if (cancelled(source) || failureDisposition(failure) == 1) {
                            result = "cancelled"; return;
                        }
                        if (failureDisposition(failure) == 2) throw failure;
                        lastFailure = failure;
                        continue;
                    }
                }
                final int n;
                try {
                    // This is only a copy buffer size, NOT an HTTP Range/chunk boundary.
                    n = current.read(buffer, 0, (int) Math.min(Math.min(buffer.length, 65536), remaining));
                    if (n < 0) throw new EOFException("WebDAV body ended before expected length at " + offset);
                    if (n == 0) throw new IOException("WebDAV input made no progress");
                } catch (IOException failure) {
                    if (cancelled(source) || failureDisposition(failure) == 1) {
                        result = "cancelled"; return;
                    }
                    if (failureDisposition(failure) == 2) throw failure;
                    // Close before reopen: never a second upstream body for this session.
                    closeQuietly(current); current = null; lastFailure = failure;
                    continue;
                }
                readBytes += n;
                if (cancelled(source)) { result = "cancelled"; return; }
                // A downstream write failure is terminal, not an upstream retry trigger.
                output.write(buffer, 0, n);
                delivered += n; offset += n; remaining -= n; attempts = 0;
                long now = System.nanoTime();
                if (now - lastLog >= 1_000_000_000L) {
                    long elapsedMs = Math.max(1L, (now - lastLog) / 1_000_000L);
                    Log.i(TAG, "NET1 id=" + id + " totalKBps="
                            + ((readBytes - lastRead) * 1000L / elapsedMs / 1024L)
                            + " readBytes=" + readBytes + " deliveredBytes=" + delivered
                            + " connectionsMax=1 includesDownstreamWait=1");
                    lastLog = now; lastRead = readBytes;
                }
            }
            result = "complete";
        } finally {
            closeQuietly(current);
            long elapsedMs = Math.max(1L, (System.nanoTime() - began) / 1_000_000L);
            Log.i(TAG, "NET1_FINAL id=" + id + " result=" + result + " readBytes=" + readBytes
                    + " deliveredBytes=" + delivered + " elapsedMs=" + elapsedMs
                    + " totalKBps=" + (readBytes * 1000L / elapsedMs / 1024L)
                    + " reopens=" + reopens + " connectionsMax=1 includesDownstreamWait=1");
        }
    }
    private static boolean cancelled(Source source) {
        return source.cancelled() || Thread.currentThread().isInterrupted();
    }
    private static void publish(Source source, InputStream input) throws IOException {
        if (source instanceof ManagedSource) ((ManagedSource) source).publishSingle(input);
        if (cancelled(source)) throw new RequestCancelledException("copy cancelled while publishing", null);
    }
    private static void closeQuietly(InputStream input) {
        if (input != null) try { input.close(); } catch (IOException ignored) { }
    }
    // Same access/cancellation classification as the previously verified transport.
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
            if (m.find()) for (int i = 1; i <= 3; i++)
                if (m.group(i) != null) return Integer.parseInt(m.group(i));
        }
        return 0;
    }
}
