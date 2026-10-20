package nova.test;

import com.archos.filecorelibrary.NovaSingleStreamInputStream;
import java.io.*;
import java.net.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** The same production copier is tested on JVM and loaded from the final APK in
 * ART. This harness is never included in the installation APK. */
public final class SingleStreamHarness {
    static final long BASE = 5000000123L;
    static int cases;
    static void check(boolean yes, String reason) { if (!yes) throw new AssertionError(reason); }
    static void passed(String name) { cases++; System.out.println("SINGLE_PASS=" + name); }
    static final class TestSource implements NovaSingleStreamInputStream.ManagedSource {
        final long start, length;
        final List<Long> offsets = new ArrayList<Long>();
        int opens, active, maxActive, publications;
        volatile boolean cancelled;
        volatile InputStream owned;
        int fault; // 1 early EOF, 2 timeout once, 3 persistent I/O, 4 403, 5 zero, 6 401
        long firstLimit = Long.MAX_VALUE;
        TestSource(long start, long length) { this.start = start; this.length = length; }
        public synchronized InputStream openRange(long offset) {
            check(active == 0, "new body opened before old body closed");
            check(offset >= start && offset <= start + length, "offset out of range");
            offsets.add(offset); final int serial = ++opens; active++; maxActive = Math.max(maxActive, active);
            return new InputStream() {
                long position = offset;
                boolean closed;
                public int read() throws IOException { byte[] b = new byte[1]; int n = read(b,0,1); return n < 0 ? -1 : b[0] & 255; }
                public int read(byte[] b, int off, int count) throws IOException {
                    check(!closed, "read after close");
                    if (fault == 3) throw new IOException("injected read failure");
                    if (fault == 4) throw new IOException("HTTP 403 Forbidden");
                    if (fault == 6) throw new IOException("HTTP 401 Unauthorized");
                    if (fault == 5) return 0;
                    if (serial == 1 && position >= start + firstLimit) {
                        if (fault == 1) return -1;
                        if (fault == 2) throw new SocketTimeoutException("injected transient timeout");
                    }
                    long end = start + length;
                    if (serial == 1 && (fault == 1 || fault == 2)) end = Math.min(end, start + firstLimit);
                    int n = (int)Math.min(count, end - position);
                    if (n <= 0) return -1;
                    for (int i=0;i<n;i++) b[off+i] = (byte)((position+i)%251);
                    position += n; return n;
                }
                public void close() { if (!closed) { closed = true; synchronized(TestSource.this) { active--; } } }
            };
        }
        public boolean cancelled() { return cancelled; }
        public void publishSingle(InputStream in) { owned = in; publications++; }
        void cancel() throws IOException { cancelled = true; InputStream in = owned; if (in != null) in.close(); }
    }
    static class VerifyOutput extends OutputStream {
        final long start;
        long count;
        VerifyOutput(long start) { this.start=start; }
        public void write(int b) { check((b&255)==(start+count)%251,"wrong byte at "+count); count++; }
        public void write(byte[] b,int off,int n) { for(int i=0;i<n;i++) check((b[off+i]&255)==(start+count+i)%251,"corrupt/duplicate/gap at "+(count+i));count+=n; }
    }
    static void copy(TestSource s, VerifyOutput out) throws IOException {
        InputStream first=s.openRange(s.start);
        NovaSingleStreamInputStream.copyRecovering(s,first,out,new byte[65536],s.start,s.length);
    }
    static void basic() throws Exception {
        TestSource s=new TestSource(BASE,32L*1024*1024+37);VerifyOutput out=new VerifyOutput(BASE);copy(s,out);
        check(out.count==s.length&&s.opens==1&&s.maxActive==1&&s.active==0,"continuous one-body mismatch");
        passed("32MiB+37 exact bytes above 4GiB offset; one open, one active body");
        for(int fault:new int[]{1,2}) {
            s=new TestSource(BASE,3*1024*1024+79);s.fault=fault;s.firstLimit=234567;
            out=new VerifyOutput(BASE);copy(s,out);
            check(out.count==s.length&&s.opens==2&&s.offsets.get(1)==BASE+234567&&s.maxActive==1&&s.active==0,"bad exact resume");
            passed(fault==1?"EOF exact-offset recovery, close-before-open":"timeout exact-offset recovery, close-before-open");
        }
        for(int fault:new int[]{3,5}) {
            s=new TestSource(BASE,100000);s.fault=fault;
            try {copy(s,new VerifyOutput(BASE));throw new AssertionError("persistent failure accepted");} catch(IOException expected){}
            check(s.opens==4&&s.active==0&&s.maxActive==1,"unbounded/no-progress retry");
            passed(fault==3?"persistent read failure bounded to three reopens":"zero progress bounded to three reopens");
        }
        for(int fault:new int[]{4,6}) {
            s=new TestSource(BASE,100000);s.fault=fault;
            try {copy(s,new VerifyOutput(BASE));throw new AssertionError("access failure accepted");} catch(IOException expected){}
            check(s.opens==1&&s.active==0,"access denial reopened");passed(fault==4?"403 does not reconnect":"401 does not reconnect");
        }
        final TestSource cancelling=new TestSource(BASE,1000000);
        out=new VerifyOutput(BASE){public void write(byte[] b,int off,int n){super.write(b,off,n);cancelling.cancelled=true;}};
        copy(cancelling,out);check(out.count==65536&&cancelling.opens==1&&cancelling.active==0,"cancel continued reading");
        passed("cancellation stops copy without another request");
        final TestSource failing=new TestSource(BASE,1000000);
        InputStream first=failing.openRange(BASE);
        try {NovaSingleStreamInputStream.copyRecovering(failing,first,new OutputStream(){public void write(int b)throws IOException{throw new IOException("downstream closed");}},new byte[65536],BASE,failing.length);throw new AssertionError("write error swallowed");}catch(IOException expected){}
        check(failing.opens==1&&failing.active==0,"downstream write retried upstream");passed("downstream failure never reconnects upstream");
        s=new TestSource(BASE,100000);out=new VerifyOutput(BASE);first=s.openRange(BASE);
        NovaSingleStreamInputStream.copyRecovering(s,first,out,new byte[65536],BASE,12345);
        check(out.count==12345&&s.active==0,"copy read past requested tail");passed("short final extent never overreads");
        s=new TestSource(BASE,100000);out=new VerifyOutput(BASE);first=s.openRange(BASE);
        NovaSingleStreamInputStream.copyRecovering(s,first,out,new byte[1],BASE,0);
        check(out.count==0&&s.active==0,"zero-length extent");passed("zero-length body closes cleanly");
        s=new TestSource(BASE,100000);first=s.openRange(BASE);
        Thread.currentThread().interrupt();
        try {NovaSingleStreamInputStream.copyRecovering(s,first,new VerifyOutput(BASE),new byte[17],BASE,s.length);check(Thread.currentThread().isInterrupted(),"interrupt flag lost");}finally{Thread.interrupted();}
        check(s.opens==1&&s.active==0,"interrupted copy not closed");passed("interruption preserved and no request restarted");
        final TestSource noReadAhead=new TestSource(BASE,100000);
        out=new VerifyOutput(BASE){public void write(byte[] b,int off,int n){check(noReadAhead.opens==1,"background opens during write");super.write(b,off,n);}};
        copy(noReadAhead,out);check(noReadAhead.opens==1,"extra opens");passed("consumer copy has no background prefetch requests");
        check(NovaSingleStreamInputStream.failureDisposition(new SocketTimeoutException("timeout"))==0,"timeout treated as cancellation");
        check(NovaSingleStreamInputStream.failureDisposition(new IOException("wrapper",new IOException("HTTP 403 Forbidden")))==2,"wrapped403");
        passed("existing timeout and nested access-denial classification preserved");
    }
    static void blockedCancel() throws Exception {
        final CountDownLatch entered=new CountDownLatch(1),closed=new CountDownLatch(1);
        final AtomicInteger requests=new AtomicInteger();final AtomicReference<Throwable> problem=new AtomicReference<Throwable>();
        final AtomicReference<InputStream> owner=new AtomicReference<InputStream>();final AtomicBoolean cancel=new AtomicBoolean();
        NovaSingleStreamInputStream.ManagedSource src=new NovaSingleStreamInputStream.ManagedSource(){
            public InputStream openRange(long p){requests.incrementAndGet();throw new AssertionError("cancelled read reopened");}
            public boolean cancelled(){return cancel.get();}
            public void publishSingle(InputStream in){owner.set(in);}
        };
        InputStream blocking=new InputStream(){public int read()throws IOException{entered.countDown();try{closed.await();}catch(InterruptedException e){Thread.currentThread().interrupt();}throw new IOException("closed");}public void close(){closed.countDown();}};
        Thread t=new Thread(()->{try{NovaSingleStreamInputStream.copyRecovering(src,blocking,new ByteArrayOutputStream(),new byte[16],0,100);}catch(Throwable e){problem.set(e);}});
        t.start();check(entered.await(3,TimeUnit.SECONDS),"did not enter read");cancel.set(true);owner.get().close();t.join(3000);
        check(!t.isAlive()&&problem.get()==null&&requests.get()==0,"blocked cancel leaked or retried");passed("published body closes blocked read promptly");
    }
    static final class HttpServer implements Closeable {
        final ServerSocket server=new ServerSocket(0,4,InetAddress.getByName("127.0.0.1"));
        final AtomicInteger requests=new AtomicInteger();final AtomicReference<Throwable> failure=new AtomicReference<Throwable>();
        final long start=12345,length=32L*1024*1024+37;
        volatile boolean stop;
        HttpServer()throws IOException {
            Thread t=new Thread(()->{while(!stop)try(Socket s=server.accept()){
                requests.incrementAndGet();s.setSoTimeout(10000);BufferedReader in=new BufferedReader(new InputStreamReader(s.getInputStream(),StandardCharsets.US_ASCII));
                String line=in.readLine();check(line!=null&&line.startsWith("GET /media "),"unexpected HTTP request");String range=null;
                while((line=in.readLine())!=null&&!line.isEmpty())if(line.toLowerCase(Locale.ROOT).startsWith("range:"))range=line.substring(6).trim();
                check(("bytes="+start+"-").equals(range),"not one continuous Range: "+range);
                OutputStream out=s.getOutputStream();String h="HTTP/1.1 206 Partial Content\r\nConnection: close\r\nContent-Length: "+length+"\r\nContent-Range: bytes "+start+"-"+(start+length-1)+"/"+(start+length)+"\r\n\r\n";
                out.write(h.getBytes(StandardCharsets.US_ASCII));byte[] b=new byte[65536];
                for(long p=0;p<length;){int n=(int)Math.min(b.length,length-p);for(int i=0;i<n;i++)b[i]=(byte)((start+p+i)%251);out.write(b,0,n);p+=n;}out.flush();
            }catch(Throwable e){if(!stop)failure.set(e);}});t.setDaemon(true);t.start();
        }
        String url(){return "http://127.0.0.1:"+server.getLocalPort()+"/media";}
        public void close()throws IOException{stop=true;server.close();}
    }
    static void http(boolean apk) throws Exception {
        try(HttpServer server=new HttpServer()) {
            final AtomicInteger opens=new AtomicInteger();
            NovaSingleStreamInputStream.Source source=new NovaSingleStreamInputStream.Source(){
                public boolean cancelled(){return false;}
                public InputStream openRange(long offset)throws IOException {
                    opens.incrementAndGet();
                    if(apk)try {
                        Class<?> c=Class.forName("nova.test.FourFixApkProbe");Method m=c.getDeclaredMethod("open",String.class,long.class);m.setAccessible(true);
                        return (InputStream)m.invoke(null,server.url(),offset);
                    }catch(Exception e){throw new IOException("final APK backend failed",e);}
                    final HttpURLConnection c=(HttpURLConnection)new URL(server.url()).openConnection();c.setRequestProperty("Range","bytes="+offset+"-");c.setConnectTimeout(10000);c.setReadTimeout(10000);
                    check(c.getResponseCode()==206,"HTTP 206 required");
                    return new FilterInputStream(c.getInputStream()){public void close()throws IOException{try{super.close();}finally{c.disconnect();}}};
                }
            };
            VerifyOutput out=new VerifyOutput(server.start);InputStream first=source.openRange(server.start);
            NovaSingleStreamInputStream.copyRecovering(source,first,out,new byte[65536],server.start,server.length);
            check(out.count==server.length&&opens.get()==1&&server.requests.get()==1&&server.failure.get()==null,"HTTP body was partitioned or corrupted: "+server.failure.get());
            passed("HTTP32MiB+37 one GET, exact bytes, backend="+(apk?"final-APK-WebdavFileEditor":"JVM-HTTP"));
        }
    }
    static void apkShape()throws Exception {
        try{Class.forName("com.archos.filecorelibrary.NovaParallelRangeInputStream");throw new AssertionError("old parallel class shipped");}catch(ClassNotFoundException expected){}
        Class<?> c=Class.forName("com.archos.filecorelibrary.StreamOverHttp$HttpSession");
        check(NovaSingleStreamInputStream.ManagedSource.class.isAssignableFrom(c),"real HTTP session not wired to single source");
        for(Method m:c.getDeclaredMethods())check(!m.getName().equals("novaWrapRange4"),"old wrapper remains");
        passed("final APK has single-session interface and no parallel helper/wrapper");
    }
    public static void main(String[] args) {
        try {boolean apk=args.length>0&&args[0].equals("--apk");basic();blockedCancel();http(apk);if(apk)apkShape();System.out.println("SINGLE_STREAM_CASES="+cases);System.out.println("SINGLE_STREAM_PROBE=PASS");}
        catch(Throwable e){e.printStackTrace();System.exit(1);}
    }
}
