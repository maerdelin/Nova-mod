package nova.test;
import android.net.Uri;
import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** Invokes the final APK's original main copyStream, not a substitute helper.
 * Account/network discovery is injected; all HTTP data remains on loopback. */
public final class MainTransportApkProbe {
    static final long START=(1L<<32)+12345;
    static final int SIZE=32*1024*1024+37;
    static void check(boolean ok,String msg){if(!ok)throw new AssertionError(msg);}
    static final class Server implements Closeable {
        final ServerSocket listener=new ServerSocket(0,8,InetAddress.getByName("127.0.0.1"));
        final AtomicInteger gets=new AtomicInteger();
        volatile boolean stopped;
        volatile Throwable failure;
        Server()throws Exception {
            Thread t=new Thread(()->{while(!stopped)try{Socket s=listener.accept();new Thread(()->serve(s)).start();}catch(IOException e){if(!stopped)failure=e;}});
            t.setDaemon(true);t.start();
        }
        String url(){return "http://127.0.0.1:"+listener.getLocalPort()+"/media";}
        void serve(Socket socket){try(Socket s=socket){
            s.setSoTimeout(5000);
            BufferedReader in=new BufferedReader(new InputStreamReader(s.getInputStream(),StandardCharsets.US_ASCII));
            String first=in.readLine();check(first!=null&&first.startsWith("GET "),"not a GET");gets.incrementAndGet();
            String line,range=null;while((line=in.readLine())!=null&&!line.isEmpty())if(line.toLowerCase(Locale.ROOT).startsWith("range:"))range=line.substring(6).trim();
            check(("bytes="+START+"-").equals(range),"wrong/partitioned Range: "+range);
            OutputStream out=s.getOutputStream();
            out.write(("HTTP/1.1 206 Partial Content\r\nContent-Length: "+SIZE+"\r\nContent-Range: bytes "+START+"-"+(START+SIZE-1)+"/"+(START+SIZE)+"\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
            byte[] block=new byte[65536];
            for(int pos=0;pos<SIZE;){int n=Math.min(block.length,SIZE-pos);for(int i=0;i<n;i++)block[i]=(byte)((START+pos+i)%251);out.write(block,0,n);pos+=n;}
        }catch(IOException expectedClientClose){}catch(Throwable e){failure=e;}}
        public void close()throws IOException{stopped=true;listener.close();}
    }
    static Object[] session()throws Exception{
        Class<?> outer=Class.forName("com.archos.filecorelibrary.StreamOverHttp");
        Class<?> inner=Class.forName("com.archos.filecorelibrary.StreamOverHttp$HttpSession");
        Object o=FourFixApkProbe.allocate(outer),s=FourFixApkProbe.allocate(inner);
        FourFixApkProbe.field(o,outer,"mUri",Uri.parse("webdav://127.0.0.1/media"));
        FourFixApkProbe.field(o,outer,"mActiveMediaRequestId",1);
        FourFixApkProbe.field(s,inner,"this$0",o);FourFixApkProbe.field(s,inner,"requestedStart",START);
        FourFixApkProbe.field(s,inner,"requestId",1);FourFixApkProbe.field(s,inner,"supersedableMediaRequest",true);
        return new Object[]{o,s};
    }
    static void copy(Object[] pair,InputStream in,OutputStream out)throws Exception{
        Method method=pair[0].getClass().getDeclaredMethod("copyStream",InputStream.class,OutputStream.class,byte[].class,long.class,pair[1].getClass());
        method.setAccessible(true);
        try{method.invoke(pair[0],in,out,new byte[128*1024],(long)SIZE,pair[1]);}
        catch(InvocationTargetException failure){Throwable t=failure.getCause();if(t instanceof Exception)throw(Exception)t;throw new AssertionError(t);}
    }
    static void run()throws Exception{
        for(String name:new String[]{"NovaParallel"+"RangeInputStream","NovaSingle"+"StreamInputStream"}){
            try{Class.forName("com.archos.filecorelibrary."+name);throw new AssertionError("removed class still shipped "+name);}
            catch(ClassNotFoundException expected){}
        }
        for(String mode:new String[]{"complete","cancel","downstream"})try(Server server=new Server()){
            Object[] pair=session();AtomicInteger count=new AtomicInteger();
            OutputStream sink=new OutputStream(){
                public void write(int v)throws IOException{write(new byte[]{(byte)v},0,1);}
                public void write(byte[] b,int off,int n)throws IOException{
                    int pos=count.get();for(int i=0;i<n;i++)check((b[off+i]&255)==(START+pos+i)%251,"byte mismatch "+(pos+i));
                    if(mode.equals("downstream")&&pos>=262144)throw new IOException("test downstream disconnected");
                    count.addAndGet(n);
                    if(mode.equals("cancel")&&count.get()>=262144)try{FourFixApkProbe.field(pair[1],pair[1].getClass(),"forceClosed",true);}catch(Exception e){throw new IOException(e);}
                }};
            try(InputStream input=FourFixApkProbe.open(server.url(),START)){
                try{copy(pair,input,sink);check(!mode.equals("downstream"),"write failure swallowed");}
                catch(IOException expected){check(mode.equals("downstream"),"unexpected IOException "+expected);}
            }
            if(mode.equals("complete"))check(count.get()==SIZE,"short copy "+count);
            else check(count.get()>=262144&&count.get()<SIZE,"cancellation/failed write ignored");
            Thread.sleep(100);check(server.gets.get()==1,"extra upstream requests "+server.gets);
            check(server.failure==null,"server contract failed "+server.failure);
            System.out.println("MAIN_COPY_PASS mode="+mode+" bytes="+count.get()+" GETs=1 originalCopyStream=1 offset="+START);
        }
        System.out.println("MAIN_TRANSPORT_FINAL_APK_PROBE=PASS");
    }
    public static void main(String[] args){try{run();System.exit(0);}catch(Throwable t){t.printStackTrace();System.exit(1);}}
}
