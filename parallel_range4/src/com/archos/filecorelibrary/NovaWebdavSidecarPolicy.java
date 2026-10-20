package com.archos.filecorelibrary;

import android.util.Log;
import java.io.IOException;
import java.net.URI;
import java.net.URISyntaxException;
import java.util.*;

/** Only optional remote resume-XML PUTs are throttled; media GETs never call this class.
 * Suppression throws IOException: do not report remote sync success. Local database
 * bookmark writes are not intercepted. Cooldown expires, and new clients are independent. */
public final class NovaWebdavSidecarPolicy {
    static final long BACKOFF_NS = 300_000_000_000L;
    private static final String SUFFIX = ".archos.resume.xml";
    private static final Map<Object, LinkedHashMap<String, Long>> DENIED =
            new WeakHashMap<Object, LinkedHashMap<String, Long>>();
    private NovaWebdavSidecarPolicy() { }
    public static final class WriteSuppressedException extends IOException {
        public WriteSuppressedException() { super("Remote resume XML not saved: backoff after HTTP 403"); }
    }
    static String key(String url) {
        if (url == null) return null;
        try {
            URI uri = new URI(url); String scheme = uri.getScheme();
            if (scheme == null || uri.getRawAuthority() == null) return null;
            scheme = scheme.toLowerCase(Locale.ROOT);
            if (!scheme.equals("http") && !scheme.equals("https") && !scheme.equals("webdav") && !scheme.equals("webdavs")) return null;
            String path = uri.getPath();
            if (path == null || !path.endsWith(SUFFIX)) return null;
            int slash = path.lastIndexOf('/');
            if (slash + 1 >= path.length() || path.charAt(slash + 1) != '.') return null;
            String base = path.substring(0, path.length() - SUFFIX.length()).replaceFirst("\\.[0-9]+$", "");
            return scheme + "://" + uri.getRawAuthority() + base + SUFFIX;
        } catch (URISyntaxException malformed) { return null; }
    }
    public static void beforePut(Object client, String url) throws IOException { beforePut(client, url, System.nanoTime()); }
    static synchronized void beforePut(Object client, String url, long now) throws IOException {
        String key = key(url);
        if (client == null || key == null) return;
        LinkedHashMap<String, Long> titles = DENIED.get(client);
        if (titles == null) return;
        Long since = titles.get(key);
        if (since == null) return;
        long age = now - since;
        if (age >= 0 && age < BACKOFF_NS) throw new WriteSuppressedException();
        titles.remove(key);
        if (titles.isEmpty()) DENIED.remove(client);
    }
    public static void recordFailure(Object client, String url, Throwable failure) {
        recordFailure(client, url, failure, System.nanoTime());
    }
    static synchronized void recordFailure(Object client, String url, Throwable failure, long now) {
        String key = key(url);
        if (client == null || key == null) return;
        boolean forbidden = false;
        for (int i = 0; failure != null && i < 16; i++, failure = failure.getCause()) {
            forbidden |= NovaParallelRangeInputStream.accessStatus(failure) == 403;
            if (failure.getCause() == failure) break;
        }
        if (!forbidden) return;
        LinkedHashMap<String, Long> titles = DENIED.get(client);
        if (titles == null) {
            if (DENIED.size() >= 32) DENIED.remove(DENIED.keySet().iterator().next());
            titles = new LinkedHashMap<String, Long>(); DENIED.put(client, titles);
        }
        if (titles.size() >= 128 && !titles.containsKey(key)) titles.remove(titles.keySet().iterator().next());
        titles.put(key, now);
        Log.w("NOVA_WEBDAV_SIDECAR", "SIDECAR_PUT_DENIED status=403 backoffMs=300000 remoteSaved=0");
    }
    public static synchronized void recordSuccess(Object client, String url) {
        String key = key(url); LinkedHashMap<String, Long> titles = DENIED.get(client);
        if (key != null && titles != null) {
            titles.remove(key); if (titles.isEmpty()) DENIED.remove(client);
        }
    }
}
