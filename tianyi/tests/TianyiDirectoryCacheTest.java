package com.archos.mediacenter.video.cloud189;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

public final class TianyiDirectoryCacheTest {
    private static void check(boolean actual, String reason) {
        if (!actual) throw new AssertionError(reason);
    }
    private static List<String> entries(String... values) {
        return new ArrayList<>(Arrays.asList(values));
    }
    private static void expectError(String label, Callable<?> operation) throws Exception {
        try {
            operation.call();
            throw new AssertionError("Expected failure: " + label);
        } catch (IOException expected) {
            System.out.println("PASS: rejected " + label);
        }
    }
    public static void main(String[] args) throws Exception {
        TianyiDirectoryCache<String> cache=new TianyiDirectoryCache<>(5000,2,4);
        AtomicInteger calls=new AtomicInteger();
        List<String> original=entries("root","child");
        List<String> first=cache.get("folder-1",()->{
            calls.incrementAndGet();
            return original;
        });
        original.add("late");
        check(first.size()==2,"Cache snapshot was not copied");
        List<String> second=cache.get("folder-1",()->{
            calls.incrementAndGet();
            throw new IOException("Unexpected refetch");
        });
        check(first.equals(second)&&calls.get()==1,"Repeated navigation refetched ancestor");
        try {
            second.add("not-allowed");
            throw new AssertionError("Cached directory snapshot was mutable");
        } catch(UnsupportedOperationException expected) {
            System.out.println("PASS: cached directory snapshot is immutable");
        }

        cache.clear();
        List<String> changed=cache.get("folder-1",()->{
            calls.incrementAndGet();
            return entries("different-account");
        });
        check(changed.equals(Collections.singletonList("different-account"))
                && calls.get()==2,"Account reset leaked cached directory");

        AtomicInteger empties=new AtomicInteger();
        cache.get("empty",()->{empties.incrementAndGet();return entries();});
        cache.get("empty",()->{empties.incrementAndGet();return entries();});
        check(empties.get()==2,"Empty directory was cached as permanently complete");

        AtomicInteger retry=new AtomicInteger();
        expectError("incomplete listing",()->cache.get("flaky",()->{
            retry.incrementAndGet();
            throw new IOException("Cloud directory pagination stopped advancing");
        }));
        List<String> recovered=cache.get("flaky",()->{
            retry.incrementAndGet();
            return entries("all-files");
        });
        check(retry.get()==2&&recovered.size()==1,"Partial listing was cached");

        TianyiDirectoryCache<String> lru=new TianyiDirectoryCache<>(5000,2,4);
        lru.get("A",()->entries("a"));
        lru.get("B",()->entries("b"));
        lru.get("A",()->{throw new IOException("Should be cached");});
        lru.get("C",()->entries("c"));
        AtomicInteger reloaded=new AtomicInteger();
        lru.get("B",()->{reloaded.incrementAndGet();return entries("b2");});
        check(reloaded.get()==1,"LRU folder bound was not enforced");

        TianyiDirectoryCache<String> expiry=new TianyiDirectoryCache<>(60,2,4);
        AtomicInteger refresh=new AtomicInteger();
        expiry.get("E",()->{refresh.incrementAndGet();return entries("old");});
        Thread.sleep(120);
        List<String> fresh=expiry.get("E",()->{refresh.incrementAndGet();return entries("new");});
        check(refresh.get()==2&&fresh.contains("new"),"TTL failed to refresh complete snapshot");

        final TianyiDirectoryCache<String> concurrent=new TianyiDirectoryCache<>(5000,2,4);
        final CountDownLatch started=new CountDownLatch(1),release=new CountDownLatch(1);
        final AtomicInteger concurrentCalls=new AtomicInteger();
        ExecutorService pool=Executors.newFixedThreadPool(7);
        try {
            List<Future<List<String>>> future=new ArrayList<>();
            for(int i=0;i<7;i++) {
                future.add(pool.submit(()->concurrent.get("bulk",()->{
                    concurrentCalls.incrementAndGet();
                    started.countDown();
                    if(!release.await(5,TimeUnit.SECONDS))
                        throw new IOException("Timed out waiting to release test loader");
                    return entries("complete-1","complete-2");
                })));
            }
            check(started.await(5,TimeUnit.SECONDS),"Single-flight loader did not start");
            release.countDown();
            for(Future<List<String>> f:future)
                check(f.get(5,TimeUnit.SECONDS).size()==2,"Concurrent reader saw partial rows");
            check(concurrentCalls.get()==1,"Seven concurrent DAV readers performed duplicate downloads");
        } finally {pool.shutdownNow();}

        final TianyiDirectoryCache<String> invalidated=new TianyiDirectoryCache<>(5000,2,4);
        final CountDownLatch reading=new CountDownLatch(1),done=new CountDownLatch(1);
        ExecutorService one=Executors.newSingleThreadExecutor();
        try {
            Future<Boolean> old=one.submit(()->{
                try {
                    invalidated.get("account-folder",()->{
                        reading.countDown();
                        if(!done.await(5,TimeUnit.SECONDS))throw new IOException("Blocked");
                        return entries("previous-account-file");
                    });
                    return false;
                }catch(IOException revoked){return true;}
            });
            check(reading.await(5,TimeUnit.SECONDS),"Account-change read did not start");
            invalidated.clear();
            done.countDown();
            check(old.get(5,TimeUnit.SECONDS),"In-flight prior-account data was exposed");
            List<String> newest=invalidated.get("account-folder",()->entries("new-account-file"));
            check(newest.size()==1&&newest.contains("new-account-file"),"Invalidated cache did not recover");
        } finally {one.shutdownNow();}

        System.out.println("ALL TIANYI DIRECTORY CACHE TESTS PASS");
    }
}
