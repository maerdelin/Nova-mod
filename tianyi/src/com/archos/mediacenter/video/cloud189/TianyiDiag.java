package com.archos.mediacenter.video.cloud189;

import java.lang.reflect.Method;
import java.util.Locale;

/**
 * All Tianyi diagnostics MUST go through the same existing NOVA global gate:
 * NovaGlobalLogs.enabled() and NovaGlobalLogs.i(String,String).
 *
 * This module is compiled as a separate DEX and cannot link the original
 * Smali-only NovaGlobalLogs at javac time; resolve it once by reflection.
 *
 * OFF (including an unavailable/failed gate) causes zero logcat output.
 * No URLs, cookies, UUIDs, user IDs, folder names or tokens may be supplied.
 */
public final class TianyiDiag {
    public static final String TAG = "NOVA_TIANYI_DIAG";
    private static volatile boolean resolved;
    private static volatile Method gate;
    private static volatile Method writer;

    private TianyiDiag() {}

    private static void resolve() {
        if (resolved) return;
        synchronized (TianyiDiag.class) {
            if (resolved) return;
            try {
                Class<?> cls = Class.forName("com.archos.mediacenter.video.NovaGlobalLogs");
                Method enabled = cls.getMethod("enabled");
                Method log = cls.getMethod("i", String.class, String.class);
                gate = enabled;
                writer = log;
            } catch (Throwable ignored) {
                gate = null;
                writer = null;
            }
            resolved = true;
        }
    }

    public static boolean enabled() {
        resolve();
        Method m = gate;
        if (m == null) return false;
        try {
            return Boolean.TRUE.equals(m.invoke(null));
        } catch (Throwable ignored) {
            return false; // fail closed, never fall back to android.util.Log
        }
    }

    /** Avoid a high-frequency clock read when the global checkbox is OFF. */
    public static long tick() {
        return enabled() ? System.nanoTime() : 0L;
    }

    private static long durationMs(long startNanos) {
        if (startNanos <= 0L) return -1L;
        long diff = System.nanoTime() - startNanos;
        return diff >= 0L ? diff / 1000000L : -1L;
    }

    private static String safeLabel(String s) {
        if (s == null || s.isEmpty()) return "UNKNOWN";
        StringBuilder b = new StringBuilder(Math.min(s.length(), 32));
        for (int i = 0; i < s.length() && b.length() < 32; i++) {
            char c = s.charAt(i);
            if (c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_') {
                b.append(c);
            } else {
                return "INVALID";
            }
        }
        return b.toString();
    }

    /**
     * Event/status labels are code-owned ASCII constants, not user input.
     * Numeric fields: response code, elapsed milliseconds, item/byte count.
     * Never pass the original exception message or a remote URL.
     */
    public static void event(String event, String result, int code, long startNanos, long count) {
        if (!enabled()) return;
        String message = "NOVA_TIANYI_DIAG_V1 event=" + safeLabel(event)
                + " result=" + safeLabel(result)
                + " code=" + code
                + " elapsedMs=" + durationMs(startNanos)
                + " count=" + count;
        Method sink = writer;
        if (sink == null) return;
        try {
            // The existing wrapper checks the same global gate again, making
            // an OFF transition between message creation and Log.i safe.
            sink.invoke(null, TAG, message);
        } catch (Throwable ignored) {
            // Diagnostics must never affect login, navigation or playback.
        }
    }

    public static void event(String event, String result, int code) {
        event(event, result, code, 0L, 0L);
    }
}
