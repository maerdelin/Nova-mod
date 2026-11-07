package com.archos.mediacenter.video.cloud189;

import java.io.IOException;
import java.net.URL;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.CancellationException;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executor;
import java.util.concurrent.FutureTask;

/** Only caches short-lived, signed 189Cloud CDN URLs in the NOVA process.
 * Playback Range bytes always travel through the unchanged native downloader.
 * A seek hits this cache without an API call or Java HTTP redirect probe. */
public final class TianyiDirectLinkCache {
    public interface Clock { long nowMs(); }
    public static final class Result {
        public final String url;
        public final String source;
        Result(String u,String s) { url=u; source=s; }
    }
    private static final long SOFT_MS=12000L;
    private static final long HARD_MS=60000L;
    private static final long ACTIVE_MS=180000L;
    private static final int MAX_FILES=16;
    private final Object mutex=new Object();
    private final Executor refreshExecutor;
    private final Clock clock;
    private final LinkedHashMap<String,Entry> entries=new LinkedHashMap<>(16,0.75f,true);
    private long generation=0;

    private static final class Entry {
        String url;
        long softUntil;
        long hardUntil;
        long lastUsed;
        Callable<String> loader;
        FutureTask<String> running;
    }
    public TianyiDirectLinkCache(Executor executor) {
        this(executor,System::currentTimeMillis);
    }
    TianyiDirectLinkCache(Executor executor,Clock clock) {
        if(executor==null || clock==null)throw new IllegalArgumentException();
        this.refreshExecutor=executor;
        this.clock=clock;
    }

    public Result get(String key,Callable<String> loader) throws Exception {
        if(key==null || key.isEmpty() || loader==null)throw new IllegalArgumentException();
        FutureTask<String> task=null;
        boolean fetchHere=false,refreshAsync=false;
        Result cached=null;
        synchronized(mutex) {
            long now=clock.nowMs();
            Entry entry=entries.get(key);
            if(entry==null) {
                entry=new Entry();
                entries.put(key,entry);
                while(entries.size()>MAX_FILES) {
                    Iterator<Map.Entry<String,Entry>> it=entries.entrySet().iterator();
                    it.next();it.remove();
                }
            }
            entry.lastUsed=now;
            entry.loader=loader;
            if(entry.url!=null && now<entry.hardUntil) {
                cached=new Result(entry.url,now<entry.softUntil?"HIT":"STALE");
                if(now>=entry.softUntil && entry.running==null) {
                    entry.running=newTask(key,entry,generation,loader);
                    task=entry.running;
                    refreshAsync=true;
                }
            } else if(entry.running!=null) {
                task=entry.running;
            } else {
                entry.running=newTask(key,entry,generation,loader);
                task=entry.running;
                fetchHere=true;
            }
        }
        if(refreshAsync) {
            try {refreshExecutor.execute(task);}
            catch(RuntimeException failure) {task.cancel(false);} // old URL is still valid
        }
        if(cached!=null)return cached;
        if(fetchHere)task.run(); // only one cold fetch per file, no thread pool queuing
        try {return new Result(task.get(),fetchHere?"MISS":"WAIT");}
        catch(ExecutionException e) {
            Throwable cause=e.getCause();
            if(cause instanceof Exception)throw (Exception)cause;
            throw new IOException("Cannot resolve cloud CDN link",cause);
        }catch(CancellationException e) {throw new IOException("Cloud link request cancelled",e);}
        catch(InterruptedException e) {Thread.currentThread().interrupt();throw new IOException("Cloud link interrupted",e);}
    }

    // Proactively refresh links used recently, even while the video is paused.
    // This keeps the next remote-control seek on the already-cached CDN URL.
    // Caller must invoke only while NOVA is foreground and its DAV is active.
    public void refreshActive() {
        ArrayList<FutureTask<String>> tasks=new ArrayList<>();
        synchronized(mutex) {
            long now=clock.nowMs();
            for(Map.Entry<String,Entry> pair:entries.entrySet()) {
                Entry e=pair.getValue();
                if(e.url==null || e.loader==null || e.running!=null)continue;
                if(now-e.lastUsed>ACTIVE_MS || now<e.softUntil)continue;
                e.running=newTask(pair.getKey(),e,generation,e.loader);
                tasks.add(e.running);
            }
        }
        for(FutureTask<String> task:tasks) {
            try {refreshExecutor.execute(task);}catch(RuntimeException failure) {task.cancel(false);}
        }
    }

    public void clear() {
        ArrayList<FutureTask<String>> cancel=new ArrayList<>();
        synchronized(mutex) {
            generation++;
            for(Entry e:entries.values())if(e.running!=null)cancel.add(e.running);
            entries.clear();
        }
        for(FutureTask<String> task:cancel)task.cancel(true);
    }

    private FutureTask<String> newTask(String key,Entry entry,long epoch,Callable<String> loader) {
        return new FutureTask<String>(()->{
            String link=loader.call();
            if(link==null || link.isEmpty())throw new IOException("Empty CDN URL");
            URL target=new URL(link);
            String scheme=target.getProtocol();
            if(!"https".equalsIgnoreCase(scheme) && !"http".equalsIgnoreCase(scheme))
                throw new IOException("Invalid CDN URL protocol");
            if(link.indexOf('\r')>=0 || link.indexOf('\n')>=0)
                throw new IOException("Invalid CDN URL header");
            return link;
        }) {
            @Override protected void done() {
                String value=null;
                try {value=get();}catch(Exception ignored) {}
                synchronized(mutex) {
                    if(entries.get(key)!=entry || epoch!=generation || entry.running!=this)return;
                    entry.running=null;
                    long now=clock.nowMs();
                    if(value!=null) {
                        entry.url=value;
                        entry.hardUntil=safeExpiry(value,now);
                        entry.softUntil=Math.min(entry.hardUntil,now+SOFT_MS);
                    } else {
                        // Prevent a failed revalidation from hammering the API.
                        entry.softUntil=Math.min(entry.hardUntil,now+4000L);
                    }
                }
            }
        };
    }

    private static long safeExpiry(String url,long now) {
        long end=now+HARD_MS;
        try {
            String query=new URL(url).getQuery();
            if(query==null)return end;
            for(String pair:query.split("&")) {
                int eq=pair.indexOf('=');
                if(eq<=0)continue;
                String name=pair.substring(0,eq).toLowerCase(java.util.Locale.US);
                if(!name.equals("expires") && !name.equals("expire") &&
                   !name.equals("expiry") && !name.equals("expiration") &&
                   !name.equals("exp") && !name.equals("expirationtime"))continue;
                String value=pair.substring(eq+1);
                if(!value.matches("[0-9]{10,13}"))continue;
                long expiry=Long.parseLong(value);
                if(value.length()<=10)expiry*=1000L;
                if(expiry>now)end=Math.min(end,Math.max(now,expiry-15000L));
            }
        }catch(Exception ignored) {} // unknown provider token format: short max lifetime
        return end;
    }
}
