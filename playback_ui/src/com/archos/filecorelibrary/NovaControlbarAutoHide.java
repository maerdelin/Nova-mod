package com.archos.filecorelibrary;

import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;

/** UI-only idle deadline. Never changes playback, seek, pause or decoder state.
 * Owned by one controller and cancelled on reset/stop. All calls use the UI thread.
 * A transient not-playing result delays the deadline; it never loses the request.
 */
public final class NovaControlbarAutoHide implements Runnable {
    public interface Host {
        boolean novaHideActive();
        boolean novaHideReady(boolean allowPaused);
        void novaHideControls();
    }
    public interface Scheduler {
        long now();
        void post(Runnable task, long delayMs);
        void remove(Runnable task);
    }
    private static final String TAG = "NOVA_CONTROLBAR";
    private final Host host;
    private final Scheduler clock;
    private boolean armed, waiting;
    private long lastInput, readySince = -1;
    private int timeout;

    public NovaControlbarAutoHide(Host host) {
        this(host, new Scheduler() {
            private final Handler handler = new Handler(Looper.getMainLooper());
            public long now() { return SystemClock.uptimeMillis(); }
            public void post(Runnable r, long ms) { handler.postDelayed(r, ms); }
            public void remove(Runnable r) { handler.removeCallbacks(r); }
        });
    }
    public NovaControlbarAutoHide(Host host, Scheduler scheduler) {
        if (host == null || scheduler == null) throw new NullPointerException();
        this.host = host; this.clock = scheduler;
    }
    /** Called for a real show/interaction event, NOT for each progress update. */
    public void arm(int timeoutMs) {
        if (timeoutMs <= 0) { cancel(); return; }
        timeout = timeoutMs;
        lastInput = clock.now(); readySince = -1; waiting = false; armed = true;
        clock.remove(this);
        clock.post(this, 0);
        Log.i(TAG, "HIDE_ARM timeoutMs=" + timeoutMs);
    }
    public void cancel() {
        boolean wasArmed = armed;
        armed = false; readySince = -1; waiting = false;
        clock.remove(this);
        if (wasArmed) Log.i(TAG, "HIDE_CANCEL");
    }
    @Override public void run() {
        if (!armed) return;
        if (!host.novaHideActive()) { cancel(); return; }
        long now = clock.now();
        if (!host.novaHideReady(timeout == 5000)) {
            readySince = -1;
            if (!waiting) Log.i(TAG, "HIDE_WAIT interaction_or_playback_state");
            waiting = true;
            clock.post(this, 250);
            return;
        }
        if (readySince < 0) {
            readySince = now; waiting = false;
            Log.i(TAG, "HIDE_READY timeoutMs=" + timeout);
        }
        long idle = Math.min(now - lastInput, now - readySince);
        if (idle >= timeout) {
            armed = false;
            clock.remove(this);
            Log.i(TAG, "HIDE_DONE reason=idle playbackUntouched=1");
            host.novaHideControls();
        } else {
            // Recheck input/menu/pause while the deadline is pending, without
            // moving that deadline on each poll or each frame/progress update.
            clock.post(this, Math.max(1, Math.min(250, timeout - idle)));
        }
    }
}
