package com.archos.filecorelibrary;

import android.util.Log;
import java.util.Map;
import java.util.WeakHashMap;

/** Lifecycle ownership is per IMediaPlayer, not a global close of whichever ISO
 * happens to be active. Opening and native teardown never run under this monitor. */
public final class NovaIsoSessionGuard {
    private static final class State { boolean released; Runnable source, nativeClose; }
    private static final Map<Object, State> OWNERS = new WeakHashMap<Object, State>();
    private NovaIsoSessionGuard() { }
    public static synchronized boolean begin(Object owner) {
        if (owner == null) return false;
        State state = OWNERS.get(owner);
        if (state == null) { state = new State(); OWNERS.put(owner, state); }
        return !state.released;
    }
    public static boolean attachSource(Object owner, Runnable close) {
        boolean cancelled;
        synchronized (NovaIsoSessionGuard.class) {
            cancelled = !begin(owner);
            if (!cancelled) OWNERS.get(owner).source = close;
        }
        if (cancelled) run(close);
        return !cancelled;
    }
    public static boolean attachNative(Object owner, Runnable close) {
        boolean cancelled;
        synchronized (NovaIsoSessionGuard.class) {
            cancelled = !begin(owner);
            if (!cancelled) OWNERS.get(owner).nativeClose = close;
        }
        if (cancelled) async(close);
        return !cancelled;
    }
    public static void release(Object owner) {
        if (owner == null) return;
        Runnable source, nativeClose;
        synchronized (NovaIsoSessionGuard.class) {
            State state = OWNERS.get(owner);
            if (state == null) { state = new State(); OWNERS.put(owner, state); }
            if (state.released) return;
            state.released = true;
            source = state.source; nativeClose = state.nativeClose;
            state.source = state.nativeClose = null;
        }
        // Source.close() cancels the HTTP session and all Range4 lanes immediately;
        // potentially blocking libbluray joins run off the UI thread, generation checked.
        run(source);
        async(nativeClose);
        Log.i("NovaIso", "OWNER_RELEASE sourceCancelled=" + (source != null));
    }
    private static void run(Runnable task) {
        if (task != null) try { task.run(); }
        catch (RuntimeException failed) { Log.w("NovaIso", "SOURCE_CLOSE_FAILED", failed); }
    }
    private static void async(final Runnable task) {
        if (task == null) return;
        Thread worker = new Thread(new Runnable() { public void run() { NovaIsoSessionGuard.run(task); } }, "NovaIso-Close");
        worker.setDaemon(true); worker.start();
    }
}
