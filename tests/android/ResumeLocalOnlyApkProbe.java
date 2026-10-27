package nova.test;
import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Uses the real final APK's Sardine method, loopback only; not shipped in APK. */
public final class ResumeLocalOnlyApkProbe {
    static void check(boolean ok,String what){if(!ok)throw new AssertionError(what);}
    static Throwable actual(Throwable t){while(t instanceof InvocationTargetException)t=((InvocationTargetException)t).getCause();return t;}
    static final class Server implements Closeable {
        final ServerSocket listener;
        final List<String> requests=Collections.synchronizedList(new ArrayList<String>());
        volatile boolean stop;
        Server()throws Exception{
            listener=new ServerSocket(0,16,InetAddress.getByName("127.0.0.1"));
            Thread thread=new Thread(()->{while(!stop)try{
                Socket s=listener.accept();Thread worker=new Thread(()->handle(s));
                worker.setDaemon(true);worker.start();
            }catch(IOException ignored){if(stop)return;}});
            thread.setDaemon(true);thread.start();
        }
        String base(){return "http://127.0.0.1:"+listener.getLocalPort();}
        void handle(Socket incoming){try(Socket s=incoming){
            s.setSoTimeout(4000);
            BufferedReader reader=new BufferedReader(new InputStreamReader(s.getInputStream(),StandardCharsets.US_ASCII));
            String line=reader.readLine();if(line==null)return;
            String requestLine=line;int size=0;
            while((line=reader.readLine())!=null&&!line.isEmpty()){
                int p=line.indexOf(':');
                if(p>=0&&line.substring(0,p).equalsIgnoreCase("content-length"))
                    size=Integer.parseInt(line.substring(p+1).trim());
            }
            requests.add(requestLine);
            for(int i=0;i<size;i++)if(reader.read()<0)break;
            s.getOutputStream().write("HTTP/1.1 403 Denied\r\nConnection: close\r\nContent-Length: 0\r\n\r\n".getBytes(StandardCharsets.US_ASCII));
            s.getOutputStream().flush();
        }catch(Exception ignored){}}
        public void close()throws IOException{stop=true;listener.close();}
    }
    public static void main(String[] args)throws Exception{
        Class<?> clazz=Class.forName("com.thegrizzlylabs.sardineandroid.impl.OkHttpSardine");
        Object client=clazz.getConstructor().newInstance();
        Method put=clazz.getMethod("put",String.class,File.class,String.class);
        File local=new File("/data/local/tmp/nova-resume-local-only-test.xml");
        try(FileOutputStream out=new FileOutputStream(local)){
            out.write("LOCAL_ONLY_SENTINEL".getBytes(StandardCharsets.US_ASCII));
        }
        try(Server server=new Server()){
            String host=server.base();
            String[] sidecars={
                host+"/%E4%B8%AD%E6%96%87/[HDR]/.movie.mkv.0.archos.resume.xml",
                host+"/Dune/.Dune.Part.One.mkv.44.archos.resume.xml",
                host+"/Dune/%2EDune.Part.One.mkv.88.archos.resume.xml",
                host+"/Dune/.Dune.Part.Two.mkv.0.archos.resume.xml?token=abc"};
            for(String url:sidecars)put.invoke(client,url,local,"application/octet-stream");
            Thread.sleep(200);
            check(server.requests.size()==0,"Remote resume PUT leaked: "+server.requests);
            System.out.println("RESUME_REMOTE_REQUESTS=0");
            try{
                put.invoke(client,host+"/normal-upload.xml",local,"application/octet-stream");
                throw new AssertionError("Normal WebDAV PUT did not reach server");
            }catch(InvocationTargetException error){
                check(actual(error) instanceof IOException,"Unexpected original PUT failure "+actual(error));
            }
            check(server.requests.size()==1,"Normal PUT not delegated: "+server.requests);
            check(server.requests.get(0).startsWith("PUT /normal-upload.xml "), "Incorrect request "+server.requests);
            check(local.isFile()&&local.length()=="LOCAL_ONLY_SENTINEL".length(),"Local file modified");
            System.out.println("NORMAL_WEBDAV_PUT_REQUESTS=1");
            System.out.println("LOCAL_INPUT_INTACT=1");
            System.out.println("RESUME_LOCAL_ONLY_FINAL_APK_PROBE=PASS");
        }finally{local.delete();}
    }
}
