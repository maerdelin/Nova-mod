package com.archos.filecorelibrary;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.BooleanSupplier;
import com.sun.net.httpserver.*;

public final class P012Harness {
    static final long M = 1024L * 1024;
    static void require(boolean ok, String why) { if (!ok) throw new AssertionError(why); }
    static void await(BooleanSupplier condition, String why) throws Exception {
        long deadline = System.nanoTime() + 5_000_000_000L;
        while (!condition.getAsBoolean() && System.nanoTime() < deadline) Thread.sleep(5);
        require(condition.getAsBoolean(), why);
    }
    static long field(Object o, String name) throws Exception {
        Field f = o.getClass().getDeclaredField(name); f.setAccessible(true);
        Object value = f.get(o); return value instanceof Boolean ? ((Boolean) value ? 1 : 0) : ((Number) value).longValue();
    }
    static File missing() throws IOException { return new File(Files.createTempDirectory("nova-cap-").toFile(), "capacity"); }
    static void publish(File target, String record) throws Exception {
        Path temp = target.toPath().resolveSibling(target.getName() + ".tmp");
        Files.write(temp, record.getBytes(StandardCharsets.US_ASCII));
        Files.move(temp, target.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
    }
    static final class Synthetic implements NovaParallelRangeInputStream.ManagedSource {
        final long size;
        final AtomicInteger opens = new AtomicInteger(), active = new AtomicInteger(), maximum = new AtomicInteger();
        final AtomicLong received = new AtomicLong();
        final List<InputStream> published = new CopyOnWriteArrayList<InputStream>();
        final List<Long> offsets = new CopyOnWriteArrayList<Long>();
        final AtomicBoolean injected = new AtomicBoolean();
        final AtomicInteger openingFailures = new AtomicInteger();
        volatile boolean cancelled;
        volatile long blockedOffset = -1, failReadAt = -1, failOpenAt = -1;
        volatile boolean returnZero;
        volatile IOException permanent;
        Synthetic(long size) { this.size = size; }
        public int capacityPort() { return 0; }
        public Object capacityOwner() { return this; }
        public boolean cancelled() { return cancelled; }
        public void publishRange4(InputStream in) { published.add(in); }
        public InputStream openRange(final long offset) throws IOException {
            offsets.add(offset); opens.incrementAndGet();
            if (offset == failOpenAt && openingFailures.getAndIncrement() < 3)
                throw new SocketTimeoutException("injected three-attempt segment timeout");
            final int a = active.incrementAndGet();
            maximum.updateAndGet(old -> Math.max(old, a));
            return new InputStream() {
                long next = offset;
                final AtomicBoolean closed = new AtomicBoolean();
                public int read() throws IOException { byte[] one = new byte[1]; int n = read(one, 0, 1); return n < 0 ? -1 : one[0] & 255; }
                public int read(byte[] b, int off, int len) throws IOException {
                    while (offset == blockedOffset && !closed.get()) {
                        try { Thread.sleep(5); }
                        catch (InterruptedException stop) { Thread.currentThread().interrupt(); throw new IOException("interrupted", stop); }
                    }
                    if (closed.get()) throw new IOException("closed connection");
                    if (permanent != null) throw permanent;
                    if (returnZero) return 0;
                    if (len == 0) return 0;
                    if (next >= size) return -1;
                    if (failReadAt >= 0 && next >= failReadAt && injected.compareAndSet(false, true))
                        throw new SocketTimeoutException("injected recoverable timeout");
                    int n = (int) Math.min(Math.min(len, 64*1024), size - next);
                    for (int i = 0; i < n; i++) b[off + i] = (byte) ((next + i) % 251);
                    next += n; received.addAndGet(n);
                    try { Thread.sleep(1); }
                    catch (InterruptedException stop) { Thread.currentThread().interrupt(); throw new IOException("interrupted", stop); }
                    return n;
                }
                public void close() { if (closed.compareAndSet(false, true)) active.decrementAndGet(); }
            };
        }
    }
    static NovaParallelRangeInputStream stream(Synthetic s, long start, long length, File cap) throws IOException {
        return new NovaParallelRangeInputStream(s, s.openRange(start), start, length, cap);
    }
    static void idle(Synthetic s) throws Exception { await(() -> s.active.get() == 0, "leaked connections " + s.active); }
    static class VerifyOutput extends OutputStream {
        final long start;
        long count;
        VerifyOutput(long start) { this.start = start; }
        public void write(int value) { require((value & 255) == (start + count) % 251, "byte mismatch at " + count); count++; }
        public void write(byte[] b, int off, int len) {
            for (int i = 0; i < len; i++) require((b[off+i] & 255) == (start + count + i) % 251, "byte mismatch at " + (count+i));
            count += len;
        }
    }
    static void consume(InputStream input, VerifyOutput output) throws IOException {
        byte[] b = new byte[65536]; int n;
        while ((n = input.read(b)) >= 0) { require(n > 0, "zero read"); output.write(b, 0, n); }
    }
    static void records() throws Exception {
        long[] sizes = {80573952464L, 87096612864L, 87419964619L, 7130000000L, 2509221119L, 2432999422L};
        long[] caps = {119072740L, 124015370L, 102500000L, 13210000L, 8560000L, 8280000L};
        for (int i = 0; i < caps.length; i++) for (String ending : new String[] {"\n", "\r\n", "\\n", "   "}) {
            long[] result = NovaParallelRangeInputStream.parseCapacityRecord(sizes[i] + " " + caps[i] + ending);
            require(result != null && result[0] == sizes[i] && result[1] == caps[i], "capacity parse");
        }
        for (String invalid : new String[] {"", "1", "1 2 3", "x 2", "1 -1", "0 2", "1 0", "1 9999999999999999999999", "1 1073741824", "1 2junk", "1 2\n3", "1 2\\nBAD", "+1 2"})
            require(NovaParallelRangeInputStream.parseCapacityRecord(invalid) == null, "accepted malformed record: " + invalid);
        System.out.println("PASS records: LF/CRLF/legacy-literal terminators and malformed/overflow rejection");
    }
    static void autonomous() throws Exception {
        Synthetic s = new Synthetic(192*M); File cap = missing();
        NovaParallelRangeInputStream in = stream(s, 0, s.size, cap);
        try {
            await(() -> s.received.get() == 4*M && s.active.get() == 0, "provisional window not full/idle");
            require(s.maximum.get() == 4, "not exactly four simultaneous connections");
            Thread.sleep(250); require(s.received.get() == 4*M, "provisional cap exceeded without reads");
            long target = 12*M + 12345;
            publish(cap, s.size + " " + target + "\n");
            await(() -> s.received.get() == 12*M && s.active.get() == 0, "late metadata did not autonomously wake download");
            require(field(in, "maxPrefetchBytes") == target, "not exact native limit");
            require(s.received.get() <= target, "native bound exceeded");
            byte[] b = new byte[(int) M]; long read = 0;
            while (read < 2*M) read += in.read(b, 0, (int) Math.min(b.length, 2*M-read));
            await(() -> s.received.get() >= 14*M, "drain did not resume producers");
            require(s.received.get()-read <= target, "unread bound exceeded after consumption");
        } finally { in.close(); idle(s); }
        System.out.println("PASS autonomous: four connections, 4MiB stop, delayed 12MiB+12345 cap, drain/refill");
    }
    static void invalidAndShrink() throws Exception {
        Synthetic s = new Synthetic(48*M); File cap = missing();
        publish(cap, (s.size+1)+" "+12*M+"\n");
        NovaParallelRangeInputStream in = stream(s, 0, s.size, cap);
        try {
            await(() -> s.received.get() == 4*M && s.active.get() == 0, "wrong-size prefill");
            require(field(in,"nativeBudgetReceived") == 0,"accepted wrong file size");
            publish(cap, s.size+" "+12*M+"\n"); cap.setLastModified(System.currentTimeMillis()-700000);
            Thread.sleep(300); require(field(in,"nativeBudgetReceived") == 0,"accepted stale record");
            publish(cap, s.size+" "+(M/2)+"\n");
            await(() -> { try { return field(in,"nativeBudgetReceived") == 1; } catch(Exception e){throw new RuntimeException(e);} },"shrink not received");
            require(field(in,"maxPrefetchBytes") == M,"minimum one-chunk bound not explicit");
            Thread.sleep(250); require(s.received.get() == 4*M,"scheduled more while old reservation exceeds shrunken cap");
            VerifyOutput output = new VerifyOutput(0); consume(in,output);
            require(output.count == s.size,"shrink lost data");
        } finally { in.close(); idle(s); }
        System.out.println("PASS capacity guards: mismatch, stale record, shrink/floor without deadlock or data loss");
    }
    static void retryAndSeek() throws Exception {
        long start=7*M+67, length=48*M+1337;
        Synthetic s = new Synthetic(start+length); s.failReadAt=start+12*M+512*1024;
        NovaParallelRangeInputStream in=stream(s,start,length,missing());
        VerifyOutput out=new VerifyOutput(start);
        try { consume(in,out); } finally {in.close();idle(s);}
        require(out.count==length && s.injected.get(),"retry/seek extent");
        System.out.println("PASS byte-exact segment retry and nonzero seek: "+out.count+" bytes");
    }
    static void cancel(boolean future, boolean interrupt) throws Exception {
        Synthetic s=new Synthetic(48*M); s.blockedOffset=future?M:0;
        NovaParallelRangeInputStream in=stream(s,0,s.size,missing());
        AtomicReference<Throwable> error=new AtomicReference<Throwable>();
        AtomicBoolean preserved=new AtomicBoolean();
        Thread reader=new Thread(() -> {try {consume(in,new VerifyOutput(0));}catch(Throwable e){error.set(e);preserved.set(Thread.currentThread().isInterrupted());}});
        reader.start();
        if (future) await(() -> {try{return field(in,"delivered")==M;}catch(Exception e){return false;}},"reader did not block on second future");
        else await(() -> s.opens.get()>=4,"workers not opened");
        if(interrupt) reader.interrupt(); else {s.cancelled=true;in.close();}
        reader.join(3000);
        require(!reader.isAlive(),"cancel deadlock");
        require(error.get() instanceof NovaParallelRangeInputStream.RequestCancelledException,"cancel was misclassified: "+error.get());
        if(interrupt) require(preserved.get(),"interrupt status lost");
        in.close();idle(s);
        int opens=s.opens.get();Thread.sleep(100);require(s.opens.get()==opens,"cancel launched extra request");
    }
    static void cancellation() throws Exception {
        for(int i=0;i<8;i++){cancel(false,false);cancel(true,false);cancel(false,true);}
        System.out.println("PASS cancellation stress: 24 first-byte/future/interrupt cases; no deadlock or leak");
    }
    static void recoveryCopy() throws Exception {
        long start=31, length=32*M+1337;
        Synthetic s=new Synthetic(start+length); s.failOpenAt=start+M;
        VerifyOutput out=new VerifyOutput(start);
        NovaParallelRangeInputStream.copyRecovering(s,s.openRange(start),out,new byte[65536],start,length);
        idle(s);
        require(out.count==length,"copy length mismatch");
        require(s.openingFailures.get()>=4,"outer retry not exercised");
        require(s.published.size()>=2,"replacement wrapper not published");
        for(InputStream in:s.published) require(in instanceof NovaParallelRangeInputStream,"recovery degraded to permanent single stream");
        require(s.offsets.contains(start+M),"recovery offset wrong");
        System.out.println("PASS production copy: segment retry exhausted, exact-offset recovery rewraps four lanes");
    }
    static void terminalAndDownstream() throws Exception {
        for(String text:new String[]{"Server returned HTTP 403 instead of 206","HTTP error 401: Unauthorized"}){
            Synthetic s=new Synthetic(32*M);s.permanent=new IOException(text);
            boolean failed=false;
            try {NovaParallelRangeInputStream.copyRecovering(s,s.openRange(0),new VerifyOutput(0),new byte[4096],0,s.size);}
            catch(IOException expected){failed=true;require(NovaParallelRangeInputStream.failureDisposition(expected)==2,"wrong denial type");}
            idle(s);require(failed,"denial swallowed");require(s.published.size()==1,"denial reopened");require(s.opens.get()<=4,"denial was retried");
        }
        Synthetic s=new Synthetic(32*M);
        boolean failed=false;
        try {NovaParallelRangeInputStream.copyRecovering(s,s.openRange(0),new OutputStream(){public void write(int n)throws IOException{throw new IOException("client gone");}public void write(byte[]b,int o,int n)throws IOException{throw new IOException("client gone");}},new byte[4096],0,s.size);}
        catch(IOException expected){failed=true;}
        idle(s);require(failed && s.published.size()==1,"downstream failure reconnected upstream");
        require(NovaParallelRangeInputStream.failureDisposition(new SocketTimeoutException("read timed out"))==0,"socket timeout classified as cancel");
        require(NovaParallelRangeInputStream.failureDisposition(new IOException("wrapper",new IOException("403 Forbidden")))==2,"nested denial missed");
        require(NovaParallelRangeInputStream.failureDisposition(new IOException("byte 403403"))==0,"false HTTP403");
        System.out.println("PASS terminal policy: 401/403 zero reconnect; output failure zero reconnect; timeouts remain recoverable");
    }
    static void copyCancelAndZero() throws Exception {
        Synthetic s=new Synthetic(32*M);
        NovaParallelRangeInputStream.copyRecovering(s,s.openRange(0),new VerifyOutput(0){public void write(byte[]b,int o,int n){super.write(b,o,n);s.cancelled=true;}},new byte[4096],0,s.size);
        idle(s);require(s.published.size()==1,"cancelled copy reopened");
        Synthetic z=new Synthetic(32*M);z.returnZero=true;boolean failed=false;
        try{NovaParallelRangeInputStream.copyRecovering(z,z.openRange(0),new VerifyOutput(0),new byte[4096],0,z.size);}
        catch(IOException expected){failed=true;}
        idle(z);require(failed,"zero-progress input did not terminate");require(z.published.size()<=4,"outer retries unbounded");
        System.out.println("PASS copy cancellation and bounded zero-progress exhaustion");
    }
    static void sidecar() throws Exception {
        Object c=new Object();String a="http://localhost:5244/dav/.video.mkv.0.archos.resume.xml";
        String rotated=a.replace(".0.",".31.");
        NovaWebdavSidecarPolicy.beforePut(c,a,1000);
        NovaWebdavSidecarPolicy.recordFailure(c,a,new IOException("wrapper",new IOException("403 Forbidden")),1000);
        boolean blocked=false;try{NovaWebdavSidecarPolicy.beforePut(c,rotated,2000);}catch(NovaWebdavSidecarPolicy.WriteSuppressedException expected){blocked=true;}
        require(blocked,"rotating resume PUT not suppressed");
        NovaWebdavSidecarPolicy.beforePut(c,a.replace("video.mkv","other.mkv"),2000);
        NovaWebdavSidecarPolicy.beforePut(new Object(),a,2000);
        NovaWebdavSidecarPolicy.beforePut(c,"http://localhost:5244/dav/video.mkv",2000);
        NovaWebdavSidecarPolicy.beforePut(c,a,1000+NovaWebdavSidecarPolicy.BACKOFF_NS);
        for(String code:new String[]{"401 Unauthorized","405 Method Not Allowed","HTTP 500"}){
            Object x=new Object();NovaWebdavSidecarPolicy.recordFailure(x,a,new IOException(code),10);
            NovaWebdavSidecarPolicy.beforePut(x,a,20);
        }
        Object x=new Object();NovaWebdavSidecarPolicy.recordFailure(x,a,new IOException("HTTP 403"),10);
        NovaWebdavSidecarPolicy.recordSuccess(x,a);NovaWebdavSidecarPolicy.beforePut(x,a,20);
        require(NovaWebdavSidecarPolicy.key("http://x/video.archos.resume.xml")==null,"non-hidden resource misclassified");
        System.out.println("PASS sidecar policy: targeted PUT-only, rotated filenames, explicit failure, client/title isolation, expiry, success reset");
    }
    static void bypass() throws Exception {
        Synthetic s=new Synthetic(8*M);InputStream original=s.openRange(0);
        require(NovaParallelRangeInputStream.maybeWrap(s,original,0,s.size)==original,"small-file bypass changed");
        original.close();idle(s);
        System.out.println("PASS small-file bypass");
    }
    static void http() throws Exception {
        final long size=20*M+777;
        AtomicInteger active=new AtomicInteger(),maximum=new AtomicInteger(),requests=new AtomicInteger();
        ExecutorService pool=Executors.newCachedThreadPool();
        HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.setExecutor(pool);
        server.createContext("/media",ex->{
            int a=active.incrementAndGet();maximum.updateAndGet(v->Math.max(v,a));requests.incrementAndGet();
            try{
                String range=ex.getRequestHeaders().getFirst("Range");
                if(range==null||!range.matches("bytes=[0-9]+-")){ex.sendResponseHeaders(400,-1);return;}
                long offset=Long.parseLong(range.substring(6,range.length()-1));
                long count=Math.min(M,size-offset);
                ex.getResponseHeaders().set("Content-Range","bytes "+offset+"-"+(offset+count-1)+"/"+size);
                ex.getResponseHeaders().set("Connection","close");
                ex.sendResponseHeaders(206,count);
                byte[] b=new byte[32768];long sent=0;
                while(sent<count){int n=(int)Math.min(b.length,count-sent);for(int i=0;i<n;i++)b[i]=(byte)((offset+sent+i)%251);ex.getResponseBody().write(b,0,n);sent+=n;try{Thread.sleep(2);}catch(InterruptedException stop){break;}}
            }catch(IOException clientClosed){}finally{ex.close();active.decrementAndGet();}
        });
        server.start();
        final int port=server.getAddress().getPort();
        NovaParallelRangeInputStream.Source src=new NovaParallelRangeInputStream.Source(){
            public boolean cancelled(){return false;}
            public InputStream openRange(long offset)throws IOException{
                HttpURLConnection c=(HttpURLConnection)new URL("http://127.0.0.1:"+port+"/media").openConnection();
                c.setConnectTimeout(3000);c.setReadTimeout(3000);c.setRequestProperty("Range","bytes="+offset+"-");
                if(c.getResponseCode()!=206)throw new IOException("HTTP "+c.getResponseCode());
                require(c.getHeaderField("Content-Range").startsWith("bytes "+offset+"-"),"HTTP offset mismatch");
                return new FilterInputStream(c.getInputStream()){public void close()throws IOException{try{super.close();}finally{c.disconnect();}}};
            }
        };
        VerifyOutput out=new VerifyOutput(0);
        try{NovaParallelRangeInputStream.copyRecovering(src,src.openRange(0),out,new byte[65536],0,size);require(out.count==size,"HTTP body corrupt");require(maximum.get()>=4,"real HTTP requests were not concurrent");}
        finally{server.stop(0);pool.shutdownNow();pool.awaitTermination(3,TimeUnit.SECONDS);}
        System.out.println("PASS loopback HTTP Range integration: bytes="+out.count+" requests="+requests+" maxServerHandlers="+maximum);
    }
    static void sessionBudget() throws Exception {
        File cap = missing(); long size = 48*M, budget = 12*M;
        Object owner = new Object(); int port = 38697;
        Constructor<NovaParallelRangeInputStream> constructor = NovaParallelRangeInputStream.class.getDeclaredConstructor(
                NovaParallelRangeInputStream.Source.class, InputStream.class, long.class, long.class,
                File.class, Object.class, int.class);
        constructor.setAccessible(true);
        publish(cap, size + " " + budget + "\n");
        Synthetic first = new Synthetic(size);
        NovaParallelRangeInputStream initial = constructor.newInstance(first, first.openRange(0), 0L, size, cap, owner, port);
        await(() -> first.received.get() == budget, "initial session budget not applied");
        initial.close(); idle(first);
        cap.setLastModified(System.currentTimeMillis() - 3600000L);
        Synthetic seek = new Synthetic(size);
        NovaParallelRangeInputStream resumed = constructor.newInstance(seek, seek.openRange(M), M, size-M, cap, owner, port);
        try {
            require(field(resumed, "nativeBudgetReceived") == 1, "long-play seek lost accepted budget");
            require(field(resumed, "maxPrefetchBytes") == budget, "seek reused wrong budget");
        } finally { resumed.close(); idle(seek); }
        Synthetic other = new Synthetic(size);
        NovaParallelRangeInputStream isolated = constructor.newInstance(other, other.openRange(0), 0L, size, cap, new Object(), port);
        try { require(field(isolated, "nativeBudgetReceived") == 0, "new owner inherited previous session budget"); }
        finally { isolated.close(); idle(other); }
        System.out.println("PASS session budget: seek after stale file reuses accepted 10X; new proxy owner stays isolated");
    }
    static void nativeCapacity(String[] args) throws Exception {
        File cap = new File(args[1]); long size = Long.parseLong(args[2]), budget = Long.parseLong(args[3]);
        Synthetic source = new Synthetic(size);
        NovaParallelRangeInputStream in = stream(source, 0, size, cap);
        long wholeChunks = budget / M * M;
        try {
            await(() -> source.received.get() == wholeChunks && source.active.get() == 0,
                    "C-published capacity did not drive autonomous Java prefetch");
            require(field(in, "maxPrefetchBytes") == budget, "C/Java budget mismatch");
            require(field(in, "nativeBudgetReceived") == 1, "native record not applied");
            require(source.maximum.get() == 4, "native-sized window lost concurrency");
            require(source.received.get() <= budget, "native window exceeded");
        } finally { in.close(); idle(source); }
        System.out.println("PASS C-to-Java capacity: sourceSize=" + size + " cap=" + budget + " fetched=" + source.received);
    }
    public static void main(String[] args)throws Exception{
        String name=args.length==0?"all":args[0];
        if(name.equals("session")||name.equals("all")) sessionBudget();
        if(name.equals("native")) nativeCapacity(args);
        if(name.equals("records")||name.equals("all"))records();
        if(name.equals("autonomous")||name.equals("all"))autonomous();
        if(name.equals("capacity")||name.equals("all"))invalidAndShrink();
        if(name.equals("retry")||name.equals("all"))retryAndSeek();
        if(name.equals("cancel")||name.equals("all"))cancellation();
        if(name.equals("copy")||name.equals("all"))recoveryCopy();
        if(name.equals("terminal")||name.equals("all"))terminalAndDownstream();
        if(name.equals("zero")||name.equals("all"))copyCancelAndZero();
        if(name.equals("sidecar")||name.equals("all"))sidecar();
        if(name.equals("bypass")||name.equals("all"))bypass();
        if(name.equals("http")||name.equals("all"))http();
    }
}
