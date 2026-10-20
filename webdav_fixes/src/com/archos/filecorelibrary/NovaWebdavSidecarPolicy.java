package com.archos.filecorelibrary;

import android.util.Log;
import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Optional resume-XML PUTs only. The real URL is never rewritten. Remote write
 * suppression is an IOException, not successful synchronization; local DB is untouched. */
public final class NovaWebdavSidecarPolicy {
    static final long BACKOFF_NS = 300_000_000_000L;
    private static final String SUFFIX = ".archos.resume.xml";
    private static final class Entry { long deniedAt; boolean denied, inFlight; }
    private static final Map<Object, LinkedHashMap<String, Entry>> STATES =
            new WeakHashMap<Object, LinkedHashMap<String, Entry>>();
    private NovaWebdavSidecarPolicy() { }
    public static class WriteSuppressedException extends IOException {
        public WriteSuppressedException() { super("Remote resume XML not saved: backoff after HTTP 403"); }
    }
    public static final class WriteInProgressException extends IOException {
        public WriteInProgressException() { super("Remote resume XML not saved: same-title write already in progress"); }
    }
    private static boolean unreserved(int c) {
        return c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9'
                || c == '-' || c == '.' || c == '_' || c == '~';
    }
    /** Canonicalize raw/encoded UTF-8 equally while preserving encoded path separators. */
    static String canonicalPath(String path) {
        StringBuilder out = new StringBuilder();
        final char[] hex = "0123456789ABCDEF".toCharArray();
        byte[] bytes = path.getBytes(StandardCharsets.UTF_8);
        for (int i = 0; i < bytes.length; i++) {
            int c = bytes[i] & 255;
            if (c == '%' && i + 2 < bytes.length) {
                int hi = Character.digit((char) bytes[i + 1], 16), lo = Character.digit((char) bytes[i + 2], 16);
                if (hi >= 0 && lo >= 0) {
                    c = hi * 16 + lo; i += 2;
                    if (unreserved(c)) out.append((char)c);
                    else out.append('%').append(hex[c >>> 4]).append(hex[c & 15]);
                    continue;
                }
            }
            if (unreserved(c) || c == '/' || c == ':' || c == '@' || "!$&'()*+,;=".indexOf(c) >= 0)
                out.append((char)c);
            else out.append('%').append(hex[c >>> 4]).append(hex[c & 15]);
        }
        return out.toString();
    }
    static String key(String url) {
        if (url == null || url.length() > 16384) return null;
        try {
            int sep = url.indexOf("://");
            if (sep < 0) return null;
            String scheme = url.substring(0, sep).toLowerCase(Locale.ROOT);
            if (scheme.equals("webdav")) scheme = "http";
            if (scheme.equals("webdavs")) scheme = "https";
            if (!scheme.equals("http") && !scheme.equals("https")) return null;
            int slash = url.indexOf('/', sep + 3);
            if (slash < 0) return null;
            String authority = url.substring(sep + 3, slash);
            URI origin = new URI(scheme + "://" + authority + "/");
            if (origin.getHost() == null) return null;
            String path = url.substring(slash);
            int q = path.indexOf('?'), h = path.indexOf('#');
            int end = Math.min(q < 0 ? path.length() : q, h < 0 ? path.length() : h);
            path = canonicalPath(path.substring(0, end));
            if (!path.endsWith(SUFFIX)) return null;
            int last = path.lastIndexOf('/');
            if (last + 1 >= path.length() || path.charAt(last + 1) != '.') return null;
            String base = path.substring(0, path.length() - SUFFIX.length()).replaceFirst("\\.[0-9]+$", "");
            return scheme + "://" + authority + base + SUFFIX;
        } catch (Exception malformed) { return null; }
    }
    private static LinkedHashMap<String, Entry> entries(Object client) {
        LinkedHashMap<String, Entry> map = STATES.get(client);
        if (map == null) { map = new LinkedHashMap<String, Entry>(); STATES.put(client, map); }
        return map;
    }
    public static void beforePut(Object client, String url) throws IOException { beforePut(client, url, System.nanoTime()); }
    static synchronized void beforePut(Object client, String url, long now) throws IOException {
        String key = key(url);
        if (client == null || key == null) return;
        LinkedHashMap<String, Entry> map = entries(client);
        Entry entry = map.get(key);
        if (entry == null) {
            if (map.size() >= 128) {
                Iterator<Entry> it = map.values().iterator(); boolean freed = false;
                while (it.hasNext()) { if (!it.next().inFlight) { it.remove(); freed = true; break; } }
                if (!freed) throw new IOException("Remote resume XML not saved: write queue capacity");
            }
            entry = new Entry(); map.put(key, entry);
        }
        if (entry.denied && now - entry.deniedAt >= 0 && now - entry.deniedAt < BACKOFF_NS) {
            Log.i("NOVA_WEBDAV_SIDECAR", "SIDECAR_PUT_SUPPRESSED reason=403-backoff remoteSaved=0");
            throw new WriteSuppressedException();
        }
        if (entry.inFlight) {
            Log.i("NOVA_WEBDAV_SIDECAR", "SIDECAR_PUT_SUPPRESSED reason=in-flight remoteSaved=0");
            throw new WriteInProgressException();
        }
        entry.inFlight = true; entry.denied = false;
    }
    public static void recordFailure(Object client, String url, Throwable failure) {
        recordFailure(client, url, failure, System.nanoTime());
    }
    static synchronized void recordFailure(Object client, String url, Throwable failure, long now) {
        String key = key(url);
        if (client == null || key == null) return;
        LinkedHashMap<String, Entry> map = entries(client);
        Entry entry = map.get(key);
        boolean forbidden = false;
        for (int i = 0; failure != null && i < 16; i++, failure = failure.getCause()) {
            forbidden |= NovaWebdavErrors.accessStatus(failure) == 403;
            if (failure.getCause() == failure) break;
        }
        if (entry != null) entry.inFlight = false;
        if (!forbidden) { if (entry != null && !entry.denied) map.remove(key); return; }
        if (entry == null) { entry = new Entry(); if (map.size() >= 128) return; map.put(key, entry); }
        entry.denied = true; entry.deniedAt = now;
        Log.w("NOVA_WEBDAV_SIDECAR", "SIDECAR_PUT_DENIED status=403 backoffMs=300000 remoteSaved=0");
    }
    public static synchronized void recordSuccess(Object client, String url) {
        String key = key(url); LinkedHashMap<String, Entry> map = STATES.get(client);
        if (key != null && map != null) { map.remove(key); if (map.isEmpty()) STATES.remove(client); }
    }
}
