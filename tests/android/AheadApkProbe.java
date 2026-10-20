package nova.test;
import android.net.Uri;
import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** Final APK's real WebDAV backend, HttpSession publication and main copy loop.
 * Loopback/injected account state only: not real cloud or decoder performance. */
public final class AheadApkProbe {
    static final long START=(1L<<32)+12345;
    static final int SIZE=40*1024*1024+37;
    static final String PREFIX="com.archos.filecorelibrary.";
    static void check(boolean b,String m){if(!b)throw new AssertionError(m);}
    static Object field(Object o,String name)throws Exception{Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}
    static void set(Object o,String name,Object v)throws Exception{FourFixApkProbe.field(o,o.getClass(),name,v);}
    static Object call(Object o,String name,Class<?>[] types,Object... values)throws Exception{
        Method m=o.getClass().getDeclaredMethod(name,types);m.setAccessible(true);
        try{return m.invoke(o,values);}catch(InvocationTargetException t){Throwable e=t.getCause();if(e instanceof Exception)throw(Exception)e;throw new AssertionError(e);}
    }
    static long metric(Object o,String name)throws Exception{return ((Number)call(o,name,new Class<?>[0])).longValue();}
    static void waitFull(Object in)throws Exception{
        long until=System.nanoTime()+TimeUnit.SECONDS.toNanos(8);
        while(metric(in,"receivedBytes")<metric(in,"capacityBytes")&&System.nanoTime()<until)Thread.sleep(5);
        check(metric(in,"receivedBytes")==metric(in,"capacityBytes"),"no independent prefetch "+metric(in,"receivedBytes"));
    }
    static void waitDone(Object in)throws Exception{
        long until=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
        while(!(Boolean)call(in,"producerDone",new Class<?>[0])&&System.nanoTime()<until)Thread.sleep(5);
        check((Boolean)call(in,"producerDone",new Class<?>[0]),"old producer not stopped");
    }
    static Object[] session(String url,long offset,long length,boolean media)throws Exception{
        Class<?> o=Class.forName(PREFIX+"StreamOverHttp"),s=Class.forName(PREFIX+"StreamOverHttp$HttpSession");
        Object outer=FourFixApkProbe.allocate(o),inner=FourFixApkProbe.allocate(s);
        set(outer,"mUri",Uri.parse(url.replaceFirst("^http:","webdav:")));set(outer,"mActiveMediaRequestId",1);
        set(outer,"mSessionLock",new Object());set(outer,"mSessions",new HashSet<Object>());
        set(inner,"this$0",outer);set(inner,"requestedStart",offset);set(inner,"requestedEnd",START+SIZE-1);
        set(inner,"length",length);set(inner,"requestId",1);set(inner,"supersedableMediaRequest",media);
        set(inner,"worker",new Thread());set(inner,"cleanupTasks",1);set(inner,"upstreamBufferSize",131072);
        // Unsafe test allocation bypasses the constructor; reproduce its owned socket.
        set(inner,"socket",new Socket());
        return new Object[]{outer,inner};
    }
    static InputStream publish(Object s,InputStream input)throws Exception{
        call(s,"publishInput",new Class<?>[]{InputStream.class},input);
        return(InputStream)field(s,"is");
    }
    static void copy(Object[] pair,InputStream input,OutputStream sink,long length)throws Exception{
        call(pair[0],"copyStream",new Class<?>[]{InputStream.class,OutputStream.class,byte[].class,long.class,pair[1].getClass()},input,sink,new byte[131072],length,pair[1]);
    }
    static final class Server implements Closeable {
        final ServerSocket server=new ServerSocket(0,8,InetAddress.getByName("127.0.0.1"));
        final AtomicInteger gets=new AtomicInteger(),active=new AtomicInteger(),max=new AtomicInteger();
        final List<Long> offsets=Collections.synchronizedList(new ArrayList<Long>());
        volatile boolean stopped;volatile Throwable error;
        Server()throws Exception{
            Thread t=new Thread(()->{while(!stopped)try{Socket c=server.accept();Thread w=new Thread(()->serve(c));w.setDaemon(true);w.start();}catch(IOException e){if(!stopped)error=e;}});
            t.setDaemon(true);t.start();
        }
        String url(){return "http://127.0.0.1:"+server.getLocalPort()+"/movie";}
        void serve(Socket c){int a=active.incrementAndGet();max.accumulateAndGet(a,Math::max);
            try(Socket s=c){s.setSoTimeout(5000);BufferedReader input=new BufferedReader(new InputStreamReader(s.getInputStream(),StandardCharsets.US_ASCII));
                String first=input.readLine(),line,range=null;check(first!=null&&first.startsWith("GET "),"GET expected");
                while((line=input.readLine())!=null&&!line.isEmpty())if(line.toLowerCase(Locale.ROOT).startsWith("range:"))range=line.substring(6).trim();
                check(range!=null&&range.matches("bytes=[0-9]+-"),"partitioned range "+range);
                long offset=Long.parseLong(range.substring(6,range.length()-1));offsets.add(offset);gets.incrementAndGet();
                long remaining=START+SIZE-offset;check(remaining>0,"bad offset");OutputStream out=s.getOutputStream();
                out.write(("HTTP/1.1 206 Partial Content\r\nContent-Length: "+remaining+"\r\nContent-Range: bytes "+offset+"-"+(START+SIZE-1)+"/"+(START+SIZE)+"\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
                byte[] b=new byte[65536];for(long pos=offset;pos<START+SIZE;){int n=(int)Math.min(b.length,START+SIZE-pos);for(int i=0;i<n;i++)b[i]=(byte)((pos+i)%251);out.write(b,0,n);pos+=n;}
            }catch(IOException expectedClose){}catch(Throwable e){error=e;}finally{active.decrementAndGet();}
        }
        public void close()throws IOException{stopped=true;server.close();}
    }
    static OutputStream sink(long start,AtomicLong bytes,boolean fail){return new OutputStream(){
        public void write(int value)throws IOException{write(new byte[]{(byte)value},0,1);}
        public void write(byte[] b,int off,int n)throws IOException{
            long pos=bytes.get();for(int i=0;i<n;i++)check((b[off+i]&255)==(start+pos+i)%251,"corrupt byte "+pos);
            if(fail&&pos>=262144)throw new IOException("injected downstream failure");bytes.addAndGet(n);
        }};
    }
    static void run()throws Exception{
        for(String mode:new String[]{"pause","resumed-publication","cancel","downstream","partial","nonmedia"})try(Server server=new Server()){
            long offset=START+(mode.equals("resumed-publication")?3*1024*1024+113:0);
            Object[] pair=session(server.url(),START,START+SIZE,!mode.equals("nonmedia"));
            long wanted=START+SIZE-offset;
            if(mode.equals("partial")){wanted=1024*1024+33;set(pair[1],"partialResponse",true);set(pair[1],"requestedEnd",offset+wanted-1);}
            InputStream raw=FourFixApkProbe.open(server.url(),offset),in;
            if(mode.equals("resumed-publication")){
                InputStream prepared=(InputStream)call(pair[1],"novaAheadInput",new Class<?>[]{InputStream.class,long.class},raw,offset);
                in=publish(pair[1],prepared);check(in==prepared,"resumed source double wrapped/returned raw");
                set(pair[1],"requestedStart",offset);
            }else in=publish(pair[1],raw);
            boolean ahead=in.getClass().getName().equals(PREFIX+"NovaAheadInputStream");
            if(mode.equals("nonmedia")){
                check(!ahead&&in==raw,"nonmedia altered");in.close();
            }else{
                check(ahead,"actual session failed to own FIFO");waitFull(in);
                long got=metric(in,"receivedBytes");check(metric(in,"deliveredBytes")==0,"consumer was required to fill");
                Thread.sleep(100);check(metric(in,"receivedBytes")==got,"unbounded ahead reads");
                if(mode.equals("cancel")){
                    call(pair[1],"cancel",new Class<?>[0]);waitDone(in);
                    check(field(pair[1],"is")==null,"cancel did not take owned stream");
                    check(((Socket)field(pair[1],"socket")).isClosed(),"cancel did not close downstream socket");
                    try{in.read();throw new AssertionError("closed input readable");}catch(IOException expected){}
                }else{
                    AtomicLong bytes=new AtomicLong();
                    try{copy(pair,in,sink(offset,bytes,mode.equals("downstream")),wanted);check(!mode.equals("downstream"),"downstream fault swallowed");}
                    catch(IOException e){check(mode.equals("downstream"),"unexpected failure "+e);}
                    if(!mode.equals("downstream"))check(bytes.get()==wanted,"short/duplicate bytes "+bytes);
                    in.close();waitDone(in);
                    System.out.println("AHEAD_COPY mode="+mode+" consumed="+bytes.get()+" prefetchWithoutConsumer="+got+" offset="+offset);
                }
            }
            long until=System.nanoTime()+TimeUnit.SECONDS.toNanos(2);while(server.active.get()!=0&&System.nanoTime()<until)Thread.sleep(5);
            check(server.gets.get()==1&&server.max.get()==1,"extra/split upstream request");
            check(server.offsets.get(0)==offset,"offset mismatch");check(server.error==null,"server error "+server.error);
            ((Socket)field(pair[1],"socket")).close();
            System.out.println("AHEAD_APK_PASS mode="+mode+" GETs=1 maxUpstream=1 sessionPublication=1");
        }
        System.out.println("AHEAD_FINAL_APK_PROBE=PASS");
    }
    public static void main(String[] args){try{run();System.exit(0);}catch(Throwable e){e.printStackTrace();System.exit(1);}}
}
