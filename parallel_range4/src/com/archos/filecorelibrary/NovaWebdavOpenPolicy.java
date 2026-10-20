package com.archos.filecorelibrary;

import android.util.Log;
import java.io.*;
import java.net.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;

/** Retry the backend GET only: never parse the localhost request again. */
public final class NovaWebdavOpenPolicy {
    public interface Source {
        InputStream novaOpenOnce(long offset, boolean fresh) throws Exception;
        String novaOrigin();
    }
    private static final String TAG = "NOVA_WEBDAV_OPEN";
    private static final AtomicLong IDS = new AtomicLong();
    private static final ThreadLocal<Trace> CURRENT = new ThreadLocal<Trace>();
    private static final Map<String, Long> REFRESHED = new LinkedHashMap<String, Long>();
    private static final long REFRESH_COOLDOWN_NS = 30_000_000_000L;
    private static final class Trace {
        final long id, offset;
        final String origin;
        int status, redirects;
        String host = "unknown";
        Trace(String origin, long offset) { this.origin = origin; this.offset = offset; id = IDS.incrementAndGet(); }
    }
    private NovaWebdavOpenPolicy() { }

    /** Invoked immediately after the actual HTTP response, before existing validation.
     * Only hostnames/statuses/byte offsets are logged, never credentials, paths or query tokens. */
    public static void response(int status, String finalUrl, int redirects, String range) {
        Trace t = CURRENT.get();
        if (t == null) return;
        t.status = status; t.redirects = redirects; t.host = host(finalUrl);
        if (status >= 400) {
            String safeRange = range != null && range.matches("bytes [0-9* /-]{1,80}") ? range : "absent-or-invalid";
            Log.w(TAG, "HTTP_RESPONSE id=" + t.id + " status=" + status + " offset=" + t.offset
                    + " originHost=" + host(t.origin) + " finalHost=" + t.host
                    + " redirects=" + redirects + " contentRange=" + safeRange);
        }
    }
    static String host(String url) {
        try {
            // java.net.URL accepts raw path characters without rewriting an IPv6 authority.
            String value = new URL(url).getHost();
            return value == null || value.isEmpty() || value.length() > 255
                    || !value.matches("[a-zA-Z0-9.:%_\\[\\]-]+") ? "unknown" : value;
        } catch (Exception invalid) { return "unknown"; }
    }
    private static void checkInterrupted() throws IOException {
        if (Thread.currentThread().isInterrupted())
            throw new NovaParallelRangeInputStream.RequestCancelledException("WebDAV open cancelled", null);
    }
    private static boolean transientFailure(Throwable error) {
        for (int n = 0; error != null && n < 16; n++, error = error.getCause()) {
            if (error instanceof SocketTimeoutException || error instanceof SocketException
                    || error instanceof UnknownHostException) return true;
            if (error.getCause() == error) break;
        }
        return false;
    }
    private static synchronized boolean reserveRefresh(String origin, long now) {
        if (origin == null || origin.length() > 16384) return false;
        Long last = REFRESHED.get(origin);
        if (last != null && now - last >= 0 && now - last < REFRESH_COOLDOWN_NS) return false;
        if (REFRESHED.size() >= 128 && !REFRESHED.containsKey(origin))
            REFRESHED.remove(REFRESHED.keySet().iterator().next());
        REFRESHED.put(origin, now);
        return true;
    }
    public static InputStream open(Source source, long offset) throws Exception {
        if (source == null) throw new NullPointerException("source");
        final String origin = source.novaOrigin();
        boolean fresh = false;
        for (int attempt = 1; attempt <= 3; attempt++) {
            checkInterrupted();
            Trace t = new Trace(origin, offset);
            CURRENT.set(t);
            try {
                InputStream result = source.novaOpenOnce(offset, fresh);
                if (result == null) throw new IOException("WebDAV returned null input");
                if (Thread.currentThread().isInterrupted()) {
                    try { result.close(); } catch (IOException ignored) { }
                    checkInterrupted();
                }
                if (attempt > 1) Log.i(TAG, "OPEN_RECOVERED id=" + t.id + " offset=" + offset
                        + " attempt=" + attempt + " freshOrigin=" + fresh + " status=" + t.status);
                return result; // Existing 206/exact Content-Range validation has already passed.
            } catch (Exception error) {
                checkInterrupted();
                int disposition = NovaParallelRangeInputStream.failureDisposition(error);
                if (disposition == 1) throw error;
                // Do not repeat a direct permission refusal. A redirected resource may
                // have expired: revalidate ORIGINAL origin once, without changing credentials,
                // URL query parameters, TLS checks or the Range offset. Still-denied means fail.
                boolean refresh = attempt < 3 && !fresh && offset >= 0 && t.status == 403
                        && t.redirects > 0 && reserveRefresh(origin, System.nanoTime());
                if (refresh) {
                    fresh = true;
                    Log.w(TAG, "REFRESH_ORIGIN_ONCE id=" + t.id + " offset=" + offset
                            + " reason=redirected403 cacheBypass=1");
                } else {
                    if (offset < 0 || disposition == 2 || attempt >= 3 || !transientFailure(error)) throw error;
                    Log.w(TAG, "OPEN_RETRY id=" + t.id + " offset=" + offset + " attempt=" + (attempt + 1)
                            + " requestReparse=0 error=" + error.getClass().getSimpleName());
                }
            } finally { CURRENT.remove(); }
            try { Thread.sleep(200L * attempt); }
            catch (InterruptedException cancelled) {
                Thread.currentThread().interrupt();
                throw new NovaParallelRangeInputStream.RequestCancelledException("WebDAV retry cancelled", cancelled);
            }
        }
        throw new IOException("WebDAV retry exhausted");
    }
}
