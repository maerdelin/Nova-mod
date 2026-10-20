package com.archos.filecorelibrary;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** Runs the production policy/ownership code with real threads and loopback sockets. */
public final class FourFixHarness {
    static void expect(boolean yes, String why) { if (!yes) throw new AssertionError(why); }
    interface Checked { void run() throws Exception; }
    static void failure(Class<?> type, Checked f) throws Exception {
        try { f.run(); } catch (Exception e) { expect(type.isInstance(e), "wrong failure: " + e); return; }
        throw new AssertionError("expected " + type.getName());
    }
    static String root() { return "http://127.0.0.1:5244/dav/" + UUID.randomUUID() + "/"; }
    static void paths() throws Exception {
        for (int i = 0; i < 11; ++i) {
            String folder = root() + "[TrueHD 7.1] \u4e2d\u6587 \u7535\u5f71[6\u96c6]/";
            String raw = folder + ".video \u4e2d\u6587 [HDR].mkv." + i + ".archos.resume.xml";
            String encoded = new URI("http", "127.0.0.1:5244", raw.substring(raw.indexOf('/', 8)), null, null).toASCIIString();
            String a = NovaWebdavSidecarPolicy.key(raw), b = NovaWebdavSidecarPolicy.key(encoded);
            expect(a != null && a.equals(b), "raw/encoded path differs: " + raw);
            String rotated = folder + ".video \u4e2d\u6587 [HDR].mkv.88.archos.resume.xml";
            expect(a.equals(NovaWebdavSidecarPolicy.key(rotated)), "position not canonicalized");
        }
        String base = root();
        expect(NovaWebdavSidecarPolicy.key(base + "movie.mkv") == null, "media GET target admitted");
        expect(NovaWebdavSidecarPolicy.key(base + "note.archos.resume.xml") == null, "visible arbitrary XML admitted");
        expect(!NovaWebdavSidecarPolicy.key(base + ".a%2Fb.0.archos.resume.xml").equals(
                NovaWebdavSidecarPolicy.key(base + "a/.b.0.archos.resume.xml")), "escaped path separator collapsed");
        expect(NovaWebdavSidecarPolicy.key(base + ".A%20B.0.archos.resume.xml").equals(
                NovaWebdavSidecarPolicy.key(base + ".A B.1.archos.resume.xml")), "space encoding differs");
        expect(!NovaWebdavSidecarPolicy.key(base + ".a+b.0.archos.resume.xml").equals(
                NovaWebdavSidecarPolicy.key(base + ".a b.0.archos.resume.xml")), "plus decoded as form space");
        System.out.println("PASS 11 raw/encoded Unicode-bracket filename cases; hidden XML only, rotation and separator isolation");
    }
    static void sidecarConcurrent() throws Exception {
        final Object client = new Object(); final String base = root() + ".movie[HDR].mkv.";
        final CountDownLatch ready = new CountDownLatch(24), go = new CountDownLatch(1);
        final AtomicInteger admitted = new AtomicInteger(), rejected = new AtomicInteger();
        List<Thread> threads = new ArrayList<Thread>();
        final AtomicReference<Throwable> error = new AtomicReference<Throwable>();
        for (int i = 0; i < 24; ++i) {
            final int pos = i;
            Thread t = new Thread(new Runnable() { public void run() {
                ready.countDown(); try {
                    go.await(); NovaWebdavSidecarPolicy.beforePut(client, base+pos+".archos.resume.xml", 1000L);
                    admitted.incrementAndGet();
                } catch (NovaWebdavSidecarPolicy.WriteInProgressException expected) { rejected.incrementAndGet(); }
                catch (Throwable bad) { error.set(bad); }
            }}); threads.add(t); t.start();
        }
        expect(ready.await(3, TimeUnit.SECONDS), "threads did not arrive"); go.countDown();
        for (Thread t : threads) t.join(3000);
        expect(error.get() == null, "thread failure " + error.get());
        expect(admitted.get() == 1 && rejected.get() == 23, "concurrent PUTs not coalesced");
        final String url = base + "0.archos.resume.xml";
        NovaWebdavSidecarPolicy.recordFailure(client, url, new IOException("403 Forbidden"), 2000L);
        for (int i = 0; i < 24; ++i) { final int p=i;
            failure(NovaWebdavSidecarPolicy.WriteSuppressedException.class, () ->
                NovaWebdavSidecarPolicy.beforePut(client, base+p+".archos.resume.xml", 3000L));
        }
        NovaWebdavSidecarPolicy.beforePut(client, url, 2001L + NovaWebdavSidecarPolicy.BACKOFF_NS);
        NovaWebdavSidecarPolicy.recordSuccess(client, url);
        NovaWebdavSidecarPolicy.beforePut(client, url, 2002L + NovaWebdavSidecarPolicy.BACKOFF_NS);
        NovaWebdavSidecarPolicy.recordFailure(client, url, new IllegalStateException("injected unchecked"), 2003L);
        NovaWebdavSidecarPolicy.beforePut(client, url, 2004L);
        NovaWebdavSidecarPolicy.recordSuccess(client, url);
        NovaWebdavSidecarPolicy.beforePut(new Object(), url, 3000L);
        System.out.println("PASS 24 concurrent writes: one admitted; 24 cooldown rejects; expiry, unchecked failure and client isolation");
    }
    static final class Opening implements NovaWebdavOpenPolicy.Source {
        final String url = root() + "media.mkv";
        final List<Long> offsets = new ArrayList<Long>();
        final List<Boolean> fresh = new ArrayList<Boolean>();
        int mode;
        Opening(int m) { mode=m; }
        public String novaOrigin() { return url; }
        public InputStream novaOpenOnce(long offset, boolean force) throws Exception {
            offsets.add(offset); fresh.add(force); int n=offsets.size();
            if (mode == 1 && n <= 2 || mode == 2) throw new SocketTimeoutException("injected upstream timeout");
            if (mode == 3 || mode == 4 || mode == 5 || mode == 6) {
                int status = mode == 4 ? 401 : 403;
                NovaWebdavOpenPolicy.response(status, "https://cdn.example/media?secret=never-log", mode >= 5 ? 1 : 0, null);
                if (mode != 5 || !force) throw new IOException("Server returned HTTP " + status + " instead of 206");
            }
            if (mode == 7) { Thread.currentThread().interrupt(); throw new SocketTimeoutException("cancelled"); }
            if (mode == 8) throw new IOException("Content-Range missing or invalid");
            NovaWebdavOpenPolicy.response(206, url, 0, "bytes " + offset + "-99999/100000");
            return new ByteArrayInputStream(new byte[] {4,5,6});
        }
    }
    static void retry() throws Exception {
        Opening src = new Opening(1);
        try (InputStream in=NovaWebdavOpenPolicy.open(src, 12345)) { expect(in.read()==4,"wrong bytes"); }
        expect(src.offsets.equals(Arrays.asList(12345L,12345L,12345L)), "retry changed offset");
        expect(src.fresh.equals(Arrays.asList(false,false,false)), "timeout should not force cache");
        Opening bad = new Opening(2);
        failure(SocketTimeoutException.class, () -> NovaWebdavOpenPolicy.open(bad,12345));
        expect(bad.offsets.size()==3, "unbounded retry");
        Opening metadata = new Opening(2);
        failure(SocketTimeoutException.class, () -> NovaWebdavOpenPolicy.open(metadata,-1));
        expect(metadata.offsets.size()==1,"metadata behavior expanded");
        System.out.println("PASS backend-only timeout recovery: three attempts, identical offset; metadata unchanged");
    }
    static void denied() throws Exception {
        for (int mode : new int[] {3,4,6,8}) {
            Opening bad=new Opening(mode);
            failure(IOException.class, () -> NovaWebdavOpenPolicy.open(bad, 54321));
            expect(bad.offsets.size()==(mode==6 ? 2 : 1), "wrong denial/validation attempt count: "+mode);
        }
        Opening fresh = new Opening(5);
        try (InputStream in=NovaWebdavOpenPolicy.open(fresh, 54321)) { expect(in.read()==4,"fresh read wrong"); }
        expect(fresh.fresh.equals(Arrays.asList(false,true)),"redirected denial did not refresh origin exactly once");
        Opening cancelled = new Opening(7);
        try { failure(IOException.class, () -> NovaWebdavOpenPolicy.open(cancelled,0)); }
        finally { Thread.interrupted(); }
        expect(cancelled.offsets.size()==1, "cancelled GET retried");
        expect(NovaWebdavOpenPolicy.host("https://user:password@[::1]:443/path?q=token").equals("[::1]"), "host sanitization IPv6");
        System.out.println("PASS direct 401/403 terminal; redirected 403 one revalidation; invalid Range and cancellation never retried");
    }
    static void refreshConcurrent() throws Exception {
        final String origin = root()+"concurrent.mkv";
        final AtomicInteger forced = new AtomicInteger(), total = new AtomicInteger();
        final AtomicReference<Throwable> failed=new AtomicReference<Throwable>();
        List<Thread> all=new ArrayList<Thread>();
        for(int i=0;i<4;i++) { final long offset=100L+i*1048576L; Thread t=new Thread(() -> {
            NovaWebdavOpenPolicy.Source s=new NovaWebdavOpenPolicy.Source() {
                public String novaOrigin() { return origin; }
                public InputStream novaOpenOnce(long o,boolean f) throws Exception {
                    total.incrementAndGet(); if(f)forced.incrementAndGet();
                    NovaWebdavOpenPolicy.response(403,"https://cdn.example/denied",1,null);
                    throw new IOException("HTTP 403");
                }
            };
            try { NovaWebdavOpenPolicy.open(s,offset); failed.set(new AssertionError("denial accepted")); }
            catch(IOException expected) { } catch(Throwable e) {failed.set(e);}
        }); all.add(t);t.start(); }
        for(Thread t:all)t.join(4000);
        expect(failed.get()==null,"worker failure "+failed.get());
        expect(total.get()==8&&forced.get()==4,"refresh storm: "+total+" forced="+forced);
        System.out.println("PASS four denied lanes: at most one revalidation per offset and four per origin cooldown");
    }
    static void allLanesRecover() throws Exception {
        final String origin=root()+"recovery.mkv";
        final CountDownLatch failedTogether=new CountDownLatch(4);
        final AtomicInteger successes=new AtomicInteger(), refreshed=new AtomicInteger();
        final AtomicReference<Throwable> error=new AtomicReference<Throwable>();
        List<Thread> all=new ArrayList<Thread>();
        for(int i=0;i<4;i++) { final long offset=61_210_871_773L+i*1048576;
            Thread t=new Thread(() -> {
                NovaWebdavOpenPolicy.Source src=new NovaWebdavOpenPolicy.Source() {
                    public String novaOrigin(){return origin;}
                    public InputStream novaOpenOnce(long actual,boolean fresh)throws Exception {
                        expect(actual==offset,"refresh changed 64-bit offset");
                        if(!fresh){failedTogether.countDown();expect(failedTogether.await(2,TimeUnit.SECONDS),"lanes not concurrent");
                            NovaWebdavOpenPolicy.response(403,"https://cdn.example/expired",1,null);throw new IOException("HTTP 403");}
                        refreshed.incrementAndGet();
                        NovaWebdavOpenPolicy.response(206,"https://cdn.example/current",1,null);
                        return new ByteArrayInputStream(new byte[]{(byte)(offset%251)});
                    }
                };
                try(InputStream in=NovaWebdavOpenPolicy.open(src,offset)){expect(in.read()==offset%251,"wrong refreshed data");successes.incrementAndGet();}
                catch(Throwable bad){error.set(bad);}
            });all.add(t);t.start();
        }
        for(Thread t:all)t.join(4000);
        expect(error.get()==null&&successes.get()==4&&refreshed.get()==4,"one repaired lane stranded the others: "+error.get());
        System.out.println("PASS all four simultaneously expired lanes recover at unchanged 64-bit offsets");
    }
    static void guard() throws Exception {
        for(int repeat=0;repeat<120;repeat++) {
            final Object owner=new Object(); final AtomicInteger source=new AtomicInteger(), nativeCount=new AtomicInteger();
            final CountDownLatch go=new CountDownLatch(1), nativeDone=new CountDownLatch(1);
            expect(NovaIsoSessionGuard.begin(owner),"new owner refused");
            Thread a=new Thread(() -> {try{go.await();}catch(InterruptedException e){throw new RuntimeException(e);}
                NovaIsoSessionGuard.attachSource(owner,()->source.incrementAndGet());
                NovaIsoSessionGuard.attachNative(owner,()->{nativeCount.incrementAndGet();nativeDone.countDown();});});
            Thread b=new Thread(() -> {try{go.await();}catch(InterruptedException e){throw new RuntimeException(e);} NovaIsoSessionGuard.release(owner);});
            a.start();b.start();go.countDown();a.join(2000);b.join(2000);
            expect(nativeDone.await(2,TimeUnit.SECONDS),"native close lost");
            NovaIsoSessionGuard.release(owner);
            expect(source.get()==1&&nativeCount.get()==1,"double/lost close");
            expect(!NovaIsoSessionGuard.begin(owner),"released owner revived");
        }
        Object old=new Object(), current=new Object(); AtomicInteger fresh=new AtomicInteger();
        NovaIsoSessionGuard.attachSource(current,()->fresh.incrementAndGet());
        NovaIsoSessionGuard.release(old);expect(fresh.get()==0,"old owner closed new source");
        NovaIsoSessionGuard.release(current);expect(fresh.get()==1,"new owner source not closed");
        System.out.println("PASS 120 ISO release/open races: source closed once, native task once, owner isolation");
    }
    static void noBlockingJoin() throws Exception {
        Object owner=new Object(); CountDownLatch entered=new CountDownLatch(1), unblock=new CountDownLatch(1), done=new CountDownLatch(1);
        AtomicInteger closed=new AtomicInteger();
        NovaIsoSessionGuard.attachSource(owner,()->closed.incrementAndGet());
        NovaIsoSessionGuard.attachNative(owner,()->{entered.countDown();try{unblock.await();}catch(InterruptedException e){Thread.currentThread().interrupt();}finally{done.countDown();}});
        long before=System.nanoTime();NovaIsoSessionGuard.release(owner);
        expect((System.nanoTime()-before)<1_000_000_000L,"release blocked on native teardown");
        expect(closed.get()==1&&entered.await(2,TimeUnit.SECONDS),"close ordering wrong");
        unblock.countDown();expect(done.await(2,TimeUnit.SECONDS),"native cleanup unfinished");
        System.out.println("PASS source cancellation precedes asynchronous native join; UI caller not blocked by join");
    }
    public static void main(String[] args) throws Exception {
        switch(args[0]) {
            case "paths": paths();break;
            case "concurrent":sidecarConcurrent();break;
            case "retry":retry();break;
            case "denied":denied();break;
            case "refresh":refreshConcurrent();break;
            case "alllanes":allLanesRecover();break;
            case "guard":guard();break;
            case "nonblocking":noBlockingJoin();break;
            default:throw new IllegalArgumentException(args[0]);
        }
    }
}
