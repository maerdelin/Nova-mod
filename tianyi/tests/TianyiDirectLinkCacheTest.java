package com.archos.mediacenter.video.cloud189;

import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.*;

public final class TianyiDirectLinkCacheTest {
    private static final class Clock implements TianyiDirectLinkCache.Clock {
        volatile long now=1800000000000L;
        @Override public long nowMs() {return now;}
    }
    private static final class QueueExecutor implements Executor {
        final Queue<Runnable> queue=new ArrayDeque<>();
        @Override public synchronized void execute(Runnable task) {queue.add(task);}
        synchronized void drain() {Runnable r;while((r=queue.poll())!=null)r.run();}
        synchronized int size() {return queue.size();}
    }
    private static void check(boolean v,String m) {if(!v)throw new AssertionError(m);}
    public static void main(String[] args) throws Exception {
        Clock clock=new Clock();QueueExecutor ex=new QueueExecutor();
        TianyiDirectLinkCache cache=new TianyiDirectLinkCache(ex,clock);
        AtomicInteger calls=new AtomicInteger();
        Callable<String> load=()->"https://cdn.example.invalid/movie.iso?t="+calls.incrementAndGet();
        String first=cache.get("video",load).url;
        for(int i=0;i<200;i++) {
            TianyiDirectLinkCache.Result res=cache.get("video",load);
            check(res.url.equals(first)&&res.source.equals("HIT"),"Hot seek performed network IO");
        }
        check(calls.get()==1,"200 Range requests must reuse one URL");
        clock.now+=13000;
        check(cache.get("video",load).source.equals("STALE"),"Stale seek should be immediate");
        check(ex.size()==1 && calls.get()==1,"Stale seek should refresh asynchronously once");
        for(int i=0;i<30;i++)check(cache.get("video",load).url.equals(first),"Stale seek blocked");
        ex.drain();
        check(calls.get()==2 && !cache.get("video",load).url.equals(first),"Async refresh unsuccessful");
        clock.now+=13000;
        cache.refreshActive();
        check(ex.size()==1,"Foreground proactive refresh missing");
        ex.drain();check(calls.get()==3,"Proactive revalidation missed");
        cache.clear();
        check(cache.get("video",load).source.equals("MISS")&&calls.get()==4,"Account reset retained URL");
        // An embedded expiry timestamp must limit the lifetime of a signed URL.
        Clock expClock=new Clock();
        TianyiDirectLinkCache expCache=new TianyiDirectLinkCache(ex,expClock);
        AtomicInteger fresh=new AtomicInteger();
        Callable<String> limited=()->"https://cdn.example.invalid/a?Expires=1800000020&x="+fresh.incrementAndGet();
        expCache.get("iso",limited);
        expClock.now+=7000;expCache.get("iso",limited);ex.drain();
        check(fresh.get()>=2,"Near-expiry URL was not refreshed");
        // True concurrent cache misses: one loader call, all readers get the same link.
        ExecutorService pool=Executors.newFixedThreadPool(12);
        TianyiDirectLinkCache many=new TianyiDirectLinkCache(ex,clock);
        AtomicInteger miss=new AtomicInteger();
        CountDownLatch start=new CountDownLatch(1);
        ArrayList<Future<String>> futures=new ArrayList<>();
        for(int i=0;i<12;i++)futures.add(pool.submit(()->{
            start.await();
            return many.get("one-video",()->{
                miss.incrementAndGet();Thread.sleep(80);
                return "https://cdn.example.invalid/single.iso";
            }).url;
        }));
        start.countDown();
        for(Future<String> f:futures)check(f.get(5,TimeUnit.SECONDS).endsWith("/single.iso"),"Concurrent seek failed");
        check(miss.get()==1,"Concurrent seeks issued duplicate API calls: "+miss.get());
        pool.shutdownNow();
        System.out.println("TIANYI_SEEK_CACHE_200_HOT_REQUESTS=PASS");
        System.out.println("TIANYI_SEEK_CACHE_SINGLEFLIGHT_12=PASS");
        System.out.println("TIANYI_SEEK_CACHE_PROACTIVE_REFRESH=PASS");
        System.out.println("TIANYI_SEEK_CACHE_ACCOUNT_INVALIDATION=PASS");
        System.out.println("TIANYI_SEEK_CACHE_SIGNED_EXPIRY=PASS");
    }
}
