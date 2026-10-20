package nova.test;

import android.net.Uri;
import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** Executes classes loaded from the final APK on Android, with loopback HTTP only.
 * Dependency injection bypasses account/UI setup; not a real cloud or playback test. */
public final class FourFixApkProbe {
    static void require(boolean ok,String why) { if(!ok)throw new AssertionError(why); }
    static Throwable actual(Throwable e) { while(e instanceof InvocationTargetException)e=((InvocationTargetException)e).getCause();return e; }
    static Object allocate(Class<?> type) throws Exception {
        Class<?> u=Class.forName("sun.misc.Unsafe");Object singleton=null;
        for(Field f:u.getDeclaredFields())if(f.getType()==u&&Modifier.isStatic(f.getModifiers())){f.setAccessible(true);singleton=f.get(null);if(singleton!=null)break;}
        if(singleton==null)throw new IllegalStateException("ART test allocator unavailable");
        return u.getMethod("allocateInstance",Class.class).invoke(singleton,type);
    }
    static void field(Object obj,Class<?> type,String name,Object value)throws Exception {
        Field f=type.getDeclaredField(name);f.setAccessible(true);f.set(obj,value);
    }
    static final class Server implements Closeable {
        final ServerSocket listener=new ServerSocket(0,32,InetAddress.getByName("127.0.0.1"));
        final ConcurrentHashMap<String,AtomicInteger> counts=new ConcurrentHashMap<String,AtomicInteger>();
        final List<String> requests=Collections.synchronizedList(new ArrayList<String>());
        volatile boolean stop;
        Server()throws IOException {
            Thread accept=new Thread(()->{while(!stop)try{Socket s=listener.accept();Thread t=new Thread(()->handle(s));t.setDaemon(true);t.start();}catch(IOException ignored){}});
            accept.setDaemon(true);accept.start();
        }
        String base(){return "http://127.0.0.1:"+listener.getLocalPort();}
        int count(String path){AtomicInteger i=counts.get(path);return i==null?0:i.get();}
        void handle(Socket socket){try(Socket s=socket){
            s.setSoTimeout(4000);BufferedReader in=new BufferedReader(new InputStreamReader(s.getInputStream(),StandardCharsets.US_ASCII));
            String line=in.readLine();if(line==null)return;String[] first=line.split(" ");String path=first[1];
            Map<String,String> h=new HashMap<String,String>();while((line=in.readLine())!=null&&!line.isEmpty()){int p=line.indexOf(':');if(p>0)h.put(line.substring(0,p).toLowerCase(Locale.ROOT),line.substring(p+1).trim());}
            counts.putIfAbsent(path,new AtomicInteger());int n=counts.get(path).incrementAndGet();requests.add(first[0]+" "+path+" range="+h.get("range")+" fresh="+h.get("cache-control"));
            if(first[0].equals("PUT")) {int bytes=Integer.parseInt(h.getOrDefault("content-length","0"));for(int i=0;i<bytes;i++)if(in.read()<0)break;reply(s,403,null,null,new byte[0]);return;}
            long start=Long.parseLong(h.get("range").substring(6).split("-")[0]);
            if(path.startsWith("/redirect")){reply(s,302,base()+("no-cache".equals(h.get("cache-control"))?"/good":"/expired"),null,new byte[0]);return;}
            if(path.startsWith("/expired")||path.startsWith("/direct403")){reply(s,403,null,null,new byte[0]);return;}
            if(path.startsWith("/direct401")){reply(s,401,null,null,new byte[0]);return;}
            if(path.startsWith("/timeout")&&n<3){Thread.sleep(1100);return;}
            byte[] bytes=new byte[4096];for(int i=0;i<bytes.length;i++)bytes[i]=(byte)((start+i)%251);
            long headerStart=path.startsWith("/bad-range")?start+1:start;
            reply(s,206,null,"bytes "+headerStart+"-"+(headerStart+4095)+"/1000000",bytes);
        }catch(Exception ignored){}}
        void reply(Socket s,int code,String location,String range,byte[] bytes)throws IOException {
            StringBuilder h=new StringBuilder("HTTP/1.1 "+code+" test\r\nConnection: close\r\nContent-Length: "+bytes.length+"\r\n");
            if(location!=null)h.append("Location: ").append(location).append("\r\n");
            if(range!=null)h.append("Content-Range: ").append(range).append("\r\n");
            h.append("\r\n");s.getOutputStream().write(h.toString().getBytes(StandardCharsets.US_ASCII));s.getOutputStream().write(bytes);s.getOutputStream().flush();
        }
        public void close()throws IOException{stop=true;listener.close();}
    }
    static Object client()throws Exception {
        Class<?> b=Class.forName("ms0");Object builder=b.getConstructor().newInstance();
        // These are the verified APK's builder timeout fields; only this test client changes.
        for(String f:new String[]{"x","y","z"})field(builder,b,f,500);
        return Class.forName("ns0").getConstructor(b).newInstance(builder);
    }
    static Object editor(String url)throws Exception {
        Class<?> type=Class.forName("com.archos.filecorelibrary.webdav.WebdavFileEditor");
        Object editor=allocate(type);field(editor,Class.forName("com.archos.filecorelibrary/FileEditor".replace('/','.')),"mUri",Uri.parse(url.replaceFirst("^http:","webdav:")));
        field(editor,type,"mHttpClient",client());field(editor,type,"mLength",-1L);return editor;
    }
    static InputStream open(String url,long offset)throws Exception {
        Object e=editor(url);
        try{return (InputStream)e.getClass().getMethod("getInputStream",long.class).invoke(e,offset);}
        catch(InvocationTargetException fail){Throwable t=actual(fail);if(t instanceof Exception)throw(Exception)t;throw new AssertionError(t);}
    }
    static void bytes(String url,long offset)throws Exception{
        try(InputStream in=open(url,offset)){for(int i=0;i<4096;i++){int n=in.read();require(n==(offset+i)%251,"corrupt body "+i);}require(in.read()==-1,"unexpected tail");}
    }
    static void denied(String url,long offset)throws Exception{
        try(InputStream in=open(url,offset)){throw new AssertionError("bad status accepted");}
        catch(IOException expected){System.out.println("EXPECTED_FAILURE="+expected.getClass().getSimpleName());}
    }
    static void run()throws Exception {
        Class<?> backend=Class.forName("com.archos.filecorelibrary.webdav.WebdavFileEditor");
        Class<?> source=Class.forName("com.archos.filecorelibrary.NovaWebdavOpenPolicy$Source");
        require(source.isAssignableFrom(backend),"final APK backend interface missing");
        try(Server server=new Server()){
            bytes(server.base()+"/good",12345);require(server.count("/good")==1,"good GET repeated");
            denied(server.base()+"/bad-range",12345);require(server.count("/bad-range")==1,"invalid Range retried");
            denied(server.base()+"/direct403",12345);require(server.count("/direct403")==1,"direct 403 retried");
            denied(server.base()+"/direct401",12345);require(server.count("/direct401")==1,"401 retried");
            bytes(server.base()+"/redirect",24123);
            require(server.count("/redirect")==2&&server.count("/expired")==1,"redirected403 not bounded/recovered");
            bytes(server.base()+"/timeout",54321);require(server.count("/timeout")==3,"timeout retry count");
            System.out.println("PASS final APK WebdavFileEditor: byte-exact206, bad-range rejection, direct401/403, redirected403 refresh, timeout recovery");
            Object sardine=Class.forName("com.thegrizzlylabs.sardineandroid.impl.OkHttpSardine").getConstructor().newInstance();
            Method put=sardine.getClass().getMethod("put",String.class,File.class,String.class);
            File f=new File("/data/local/tmp/nova-fourfix-probe.xml");try(FileOutputStream out=new FileOutputStream(f)){out.write("test".getBytes(StandardCharsets.US_ASCII));}
            String base=server.base()+"/[HDR] \u4e2d\u6587/.movie.mkv.";
            int before=server.requests.size();
            for(int pos:new int[]{0,44,88}){
                try{put.invoke(sardine,base+pos+".archos.resume.xml",f,"application/octet-stream");throw new AssertionError("denied PUT reported success");}
                catch(InvocationTargetException failure){Throwable t=actual(failure);require(t instanceof IOException,"unexpected PUT exception "+t);}
            }
            require(server.requests.size()==before+1,"sidecar cooldown did not suppress real PUT requests");
            require(f.length()==4,"local input damaged");f.delete();
            System.out.println("PASS final APK actual OkHttpSardine PUT: raw Unicode/brackets + rotated filenames; 3 calls, 1 HTTP request, no false success");
            for(String request:server.requests)System.out.println("MOCK_REQUEST="+request);
        }
    }
    public static void main(String[] args){try{run();System.out.println("FOURFIX_FINAL_APK_PROBE=PASS");System.exit(0);}catch(Throwable failure){failure.printStackTrace();System.exit(1);}}
}
