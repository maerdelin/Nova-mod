package com.archos.mediacenter.video.cloud189;

import android.content.Context;
import android.graphics.Bitmap;
import android.os.Handler;
import android.os.Looper;
import android.net.Uri;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.concurrent.*;
import javax.crypto.Cipher;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.json.*;

/**
 * Minimal read-only 189CloudPC -> loopback WebDAV bridge.
 * Source reference: OpenListTeam/OpenList v4.2.9 drivers/189pc.
 * There is no listener on a LAN address. No login token is put in DAV URLs.
 */
public final class TianyiCloud {
    public interface QrListener {
        void onCode(String code);
        void onStatus(String status);
        void onAuthorized(String davUri);
    }

    private static final String APP_ID="9317140619", CLIENT_TYPE="10020";
    private static final String QR_CLIENT_TYPE="1", RETURN_URL="https://m.cloud.189.cn/zhuanti/2020/loginErrorPc/index.html";
    private static final String WEB="https://cloud.189.cn", AUTH="https://open.e.189.cn", API="https://api.cloud.189.cn";
    private static final String PC="TELEPC", VERSION="7.2.4.0", CHANNEL="web_cloud.189.cn";
    private static final int PORT=27989;
    private static volatile TianyiCloud INSTANCE;
    private final TianyiStore store;
    private final Context app;
    private final ExecutorService workers=Executors.newFixedThreadPool(8, r -> {
        Thread t=new Thread(r,"nova-tianyi"); t.setDaemon(true); return t;
    });
    private final CookieManager cookies=new CookieManager(null,CookiePolicy.ACCEPT_ALL);
    private final SecureRandom rng=new SecureRandom();
    private final Object sessionLock=new Object();
    private final ScheduledExecutorService keepAlive=Executors.newSingleThreadScheduledExecutor(r -> {
        Thread t=new Thread(r,"nova-tianyi-refresh");t.setDaemon(true);return t;
    });
    private volatile String sessionKey="", sessionSecret="";
    private volatile long nextRefresh=0L;
    private volatile boolean started=false;

    private TianyiCloud(Context c) {app=c.getApplicationContext();store=new TianyiStore(app);}
    /** Match only THIS installation's persisted random DAV capability.
     * R8-optimized phone mappers may supply a path label rather than its
     * full webdav:// URI; do not rename arbitrary 48-character strings. */
    public static boolean isOwnShortcutLabel(String label) {
        if(label==null)return false;
        TianyiCloud cloud=INSTANCE;
        if(cloud==null)return false;
        String capability=cloud.store.existingPathKey();
        if(capability==null || !capability.matches("[0-9a-fA-F]{48}"))return false;
        String s=label.trim();
        return s.equals(capability) || s.equals(capability+"/")
                || s.equals("/"+capability) || s.equals("/"+capability+"/");
    }
    public static synchronized TianyiCloud get(Context c) {
        if(INSTANCE==null) INSTANCE=new TianyiCloud(c);
        return INSTANCE;
    }
    public static void startIfSaved(Context c) {
        TianyiCloud cloud=get(c);
        // Schedule binding immediately when the network page resumes.
        // Do not perform socket operations on the Android UI thread; unlike
        // the old implementation we no longer decrypt tokens before binding.
        cloud.workers.execute(() -> {
            try {
                if(!cloud.store.existingPathKey().isEmpty()) {
                    // The shortcut survives reboot independently of this
                    // process. Rebind its existing port and capability, never
                    // generate a fresh key or make a second shortcut.
                    cloud.startServer();
                    TianyiDiag.event("DAV_RESTORE","OK",0);
                    TianyiStore.Saved saved=cloud.store.read();
                    if(saved.refreshToken.isEmpty()) {
                        TianyiDiag.event("DAV_RESTORE_TOKEN","MISSING",0);
                    } else {
                        TianyiDiag.event("DAV_RESTORE_TOKEN","PRESENT",0);
                        // Validate the restored session in the background,
                        // before a directory-open request needs it. A failed
                        // validation must not delete persistent credentials.
                        try {
                            cloud.ensureSession();
                            TianyiDiag.event("DAV_RESTORE_SESSION","OK",0);
                            // Restoration is only usable when the original
                            // account can list its personal cloud root.
                            long startedAt=TianyiDiag.tick();
                            java.util.List<FileObj> entries=cloud.list("-11");
                            TianyiDiag.event("DAV_RESTORE_ROOT","OK",207,startedAt,entries.size());
                        } catch(Exception restoreError) {
                            TianyiDiag.event("DAV_RESTORE_ROOT","FAIL",-1);
                        }
                    }
                }
            }catch(Exception ignored){
                TianyiDiag.event("DAV_RESTORE","FAIL",-1);
            }
        });
    }

    private void resetIfShortcutWasDeleted() {
        try {
            String path=store.existingPathKey();
            if(path.isEmpty())return;
            String uri="webdav://127.0.0.1:"+PORT+"/"+path+"/";
            Class<?> cls=Class.forName("com.archos.mediacenter.video.browser.ShortcutDb");
            @SuppressWarnings({"rawtypes","unchecked"})
            Object db=Enum.valueOf((Class<? extends Enum>)cls,"STATIC");
            long found=((Number)cls.getMethod("isShortcut",Context.class,String.class)
                    .invoke(db,app,uri)).longValue();
            if(found>=0)return;
            // The only Tianyi shortcut was deleted. Never silently reuse
            // its previous tokens or local capability in a new QR session.
            store.resetAfterShortcutDeletion();
            sessionKey="";
            sessionSecret="";
            nextRefresh=0L;
            cookies.getCookieStore().removeAll();
            TianyiDiag.event("ACCOUNT_RESET","DELETED",0);
        }catch(Exception ignored) {
            // A transient database read failure must not revoke credentials.
            TianyiDiag.event("ACCOUNT_RESET","CHECK_FAIL",-1);
        }
    }
    public void startServer() throws Exception {
        synchronized(this) {
            if(started)return;
            ServerSocket sock=new ServerSocket();
            sock.setReuseAddress(true);
            sock.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"),PORT),32);
            started=true;
            TianyiDiag.event("DAV_BIND","OK",PORT);
            Thread acceptor=new Thread(()->{
                while(!sock.isClosed()) {
                    try {
                        Socket client=sock.accept();
                        client.setSoTimeout(25000);
                        workers.execute(()->handle(client));
                    }catch(Exception ignored){TianyiDiag.event("DAV_ACCEPT","FAIL",-1);}
                }
            },"nova-tianyi-dav");
            acceptor.setDaemon(true);
            acceptor.start();
            // OpenList's PC driver periodically pings its authenticated session.
            // Android can suspend the timer; every DAV request can also refresh.
            keepAlive.scheduleWithFixedDelay(() -> {
                long diagStart=TianyiDiag.tick();
                try {
                    if(!store.read().refreshToken.isEmpty())
                        apiGet("/keepUserSession.action",new LinkedHashMap<String,String>());
                    TianyiDiag.event("KEEPALIVE","OK",0,diagStart,0L);
                } catch(Exception e) {
                    TianyiDiag.event("KEEPALIVE","FAIL",-1,diagStart,0L);
                    nextRefresh=0;
                    try{ensureSession();}catch(Exception ignored){}
                }
            },5,5,TimeUnit.MINUTES);
        }
    }
    public String rootUri() throws Exception {
        startServer();
        return "webdav://127.0.0.1:"+PORT+"/"+store.getOrCreatePathKey()+"/";
    }
    public void beginLogin(QrListener listener, Callable<Boolean> alive) {
        workers.execute(()->{
            if(TianyiUi.hasExistingShortcut(app)) {
                listener.onStatus("已添加天翼云盘，请先删除原快捷方式");
                TianyiDiag.event("QR_START","DUPLICATE_BLOCKED",0);
                return;
            }
            long diagStart=TianyiDiag.tick();
            TianyiDiag.event("QR_START","BEGIN",0);
            final String[] phase=new String[]{"FINGER"};
            try {
                resetIfShortcutWasDeleted();
                cookies.getCookieStore().removeAll();
                String finger=store.getOrCreateFinger();
                String ts=Long.toString(System.currentTimeMillis());
                Map<String,String> start=map("appId",APP_ID,"clientType",CLIENT_TYPE,"returnURL",RETURN_URL,"timeStamp",ts);
                phase[0]="INIT_LOGIN";
                Reply initial=request("GET",WEB+"/api/portal/unifyLoginForPC.action",start,null,null,true);
                String endpoint=initial.url;
                String lt=param(endpoint,"lt"), reqId=param(endpoint,"reqId");
                String ref=endpoint;
                String paramId="";
                if(lt.isEmpty()||reqId.isEmpty()) {
                    lt=match(initial.body,"lt = \"([^\"]+)\"");
                    reqId=match(initial.body,"reqId = \"([^\"]+)\"");
                    paramId=match(initial.body,"paramId = \"([^\"]+)\"");
                    ref=AUTH+"/api/logbox/separate/web/index.html?appId="+APP_ID+"&lt="+URLEncoder.encode(lt,"UTF-8")+"&reqId="+URLEncoder.encode(reqId,"UTF-8");
                }
                if(lt.isEmpty()||reqId.isEmpty())throw new IOException("Login challenge unavailable");
                Map<String,String> headers=map("REQID",reqId,"lt",lt,"user-finger",finger,"Referer",ref);
                if(paramId.isEmpty()){
                    phase[0]="APP_CONF";
                    JSONObject conf=json(request("POST",AUTH+"/api/logbox/oauth2/appConf.do",null,
                            map("version","2.0","appKey",APP_ID),headers,true).body);
                    paramId=conf.optJSONObject("data")==null?"":conf.getJSONObject("data").optString("paramId","");
                }
                if(paramId.isEmpty())throw new IOException("Missing login parameter");
                phase[0]="GET_UUID";
                JSONObject qr=json(request("POST",AUTH+"/api/logbox/oauth2/getUUID.do",null,map("appId",APP_ID),headers,true).body);
                String uuid=qr.optString("uuid",""), enc=qr.optString("encryuuid","");
                if(uuid.isEmpty())throw new IOException("QR challenge unavailable");
                // Preflight secret persistence BEFORE rendering the QR, so a
                // storage failure cannot flash a QR then replace it immediately.
                // Only actual login tokens are encrypted and committed.
                phase[0]="SECURE_STORE";
                store.verifyCrypto();
                TianyiDiag.event("SECURE_STORE","OK",0);
                phase[0]="QR_DISPLAY";
                TianyiDiag.event("QR_CREATE","OK",0,diagStart,0L);
                listener.onCode(uuid);
                final long until=System.currentTimeMillis()+180000L;
                while(System.currentTimeMillis()<until && Boolean.TRUE.equals(alive.call())) {
                    Thread.sleep(2000);
                    Date now=new Date();
                    String date=new SimpleDateFormat("yyyy-MM-ddHH:mm:ss.SSS",Locale.US).format(now);
                    Map<String,String> form=map("appId",APP_ID,"clientType",QR_CLIENT_TYPE,"returnUrl",RETURN_URL,
                            "paramId",paramId,"uuid",uuid,"encryuuid",enc,"cb_SaveName","3",
                            "isOauth2","false","state","","date",date,"timeStamp",
                            Long.toString(System.currentTimeMillis()));
                    phase[0]="QR_POLL";
                    JSONObject status=json(request("POST",AUTH+"/api/logbox/oauth2/qrcodeLoginState.do",
                            null,form,headers,true).body);
                    int state=status.optInt("status",-100);
                    if(state==0){TianyiDiag.event("QR_POLL","AUTHORIZED",state);
                        String redirect=status.optString("redirectUrl","");
                        if(redirect.isEmpty())throw new IOException("Missing QR authorization redirect");
                        phase[0]="GET_SESSION";
                        JSONObject token=json(request("POST",API+"/getSessionForPC.action",
                                suffix(map("redirectURL",redirect,"returnType","JSON")),
                                null,map("X-Request-ID",UUID.randomUUID().toString()),true).body);
                        String access=token.optString("accessToken",""),refresh=token.optString("refreshToken","");
                        if(access.isEmpty()||refresh.isEmpty())throw new IOException("QR token exchange failed");
                        phase[0]="TOKEN_SAVE";
                        if(TianyiUi.hasExistingShortcut(app))
                            throw new IOException("Tianyi shortcut already exists");
                        store.saveTokens(access,refresh);
                        TianyiDiag.event("QR_TOKEN","OK",0,diagStart,0L);
                        setSession(token);
                        ensureSession();
                        phase[0]="ROOT_LIST";
                        list("-11"); // Verify root directory before creating a shortcut.
                        TianyiDiag.event("QR_ROOT","OK",0,diagStart,0L);
                        listener.onAuthorized(rootUri());
                        return;
                    }
                    if(state==-11001){
                        TianyiDiag.event("QR_POLL","EXPIRED",state);
                        throw new IOException("QR expired");
                    }
                    if(state==-11002){
                        TianyiDiag.event("QR_POLL","CONFIRM",state);
                        listener.onStatus("请在手机上确认登录");
                    }
                    else if(state!=-106)throw new IOException("QR authorization rejected ("+state+")");
                }
                if(Boolean.TRUE.equals(alive.call()))listener.onStatus("二维码已过期，请重新选择天翼云盘");
            }catch(Exception e) {
                TianyiDiag.event("QR_LOGIN_"+phase[0],"FAIL",-1,diagStart,0L);
                if(safeAlive(alive)) {
                    String cause=e.getClass().getSimpleName();
                    // Crypto errors use only a static stage name, not provider messages
                    // which might reveal internal device/Keystore details.
                    if("SECURE_STORE".equals(phase[0]) && e instanceof IOException
                            && e.getMessage()!=null && e.getMessage().matches("CRYPTO_[A-Z_]+[A-Za-z]+Exception"))
                        cause=e.getMessage();
                    listener.onStatus("天翼云盘 "+phase[0]+" 失败 ("+cause+")，点击重试");
                }
            }
        });
    }
    private static boolean safeAlive(Callable<Boolean> c) {try{return c.call();}catch(Exception e){return false;}}
    private static String cleanError(Exception e) {
        String s=e.getMessage();if(s==null)return "网络异常";
        if(s.length()>110)s=s.substring(0,110);
        return s.replaceAll("(?i)(accessToken|refreshToken|sessionSecret)=[^ &]+","$1=[hidden]");
    }
    private void setSession(JSONObject token) {
        String k=token.optString("sessionKey",""),s=token.optString("sessionSecret","");
        if(!k.isEmpty()&&!s.isEmpty()) {
            sessionKey=k;sessionSecret=s;nextRefresh=System.currentTimeMillis()+15*60*1000L;
        }
    }
    public void ensureSession() throws Exception {
        synchronized(sessionLock){
            if(!sessionKey.isEmpty()&&System.currentTimeMillis()<nextRefresh)return;
            long diagStart=TianyiDiag.tick();
            TianyiDiag.event("SESSION","BEGIN",0);
            TianyiStore.Saved saved=store.read();
            if(saved.refreshToken.isEmpty())throw new IOException("Please scan the Tianyi QR code");
            JSONObject data=null;
            // On a cold start the cached access token may have expired.
            // The Tianyi API can report that as HTTP 401/403 (throwing) OR
            // JSON without sessionKey. Both must fall back to the encrypted,
            // persisted refresh token rather than leaving the shortcut dead.
            if(!saved.accessToken.isEmpty()) {
                try {
                    data=json(request("GET",API+"/getSessionForPC.action",
                            suffix(map("appId",APP_ID,"accessToken",saved.accessToken,"returnType","JSON")),
                            null,map("X-Request-ID",UUID.randomUUID().toString()),true).body);
                }catch(IOException expiredAccess) {
                    TianyiDiag.event("SESSION_ACCESS","REFRESH_REQUIRED",0);
                }
            }
            if(data==null || data.optString("sessionKey","").isEmpty()){
                JSONObject refreshed=json(request("POST",AUTH+"/api/oauth2/refreshToken.do",
                        null,map("clientId",APP_ID,"refreshToken",saved.refreshToken,"grantType","refresh_token","format","json"),
                        null,true).body);
                String access=refreshed.optString("accessToken",""), refresh=refreshed.optString("refreshToken","");
                if(access.isEmpty()||refresh.isEmpty())throw new IOException("Please re-scan Tianyi QR code");
                store.saveTokens(access,refresh);
                TianyiDiag.event("TOKEN_REFRESH","OK",0,diagStart,0L);
                data=json(request("GET",API+"/getSessionForPC.action",
                        suffix(map("appId",APP_ID,"accessToken",access,"returnType","JSON")),
                        null,map("X-Request-ID",UUID.randomUUID().toString()),true).body);
            }
            // Do not accept an obsolete in-memory session if the newly
            // acquired response did not include both signed-session fields.
            sessionKey="";
            sessionSecret="";
            nextRefresh=0L;
            setSession(data);
            if(sessionKey.isEmpty() || sessionSecret.isEmpty()) {
                TianyiDiag.event("SESSION","FAIL",-1,diagStart,0L);
                throw new IOException("Cannot initialize Tianyi session");
            }
            TianyiDiag.event("SESSION","OK",0,diagStart,0L);
        }
    }
    private Map<String,String> signedHeaders(String path,String encryptedParams) throws Exception {
        ensureSession();
        String date=new SimpleDateFormat("EEE, dd MMM yyyy HH:mm:ss 'GMT'",Locale.US) {{
            setTimeZone(TimeZone.getTimeZone("GMT"));
        }}.format(new Date());
        String message="SessionKey="+sessionKey+"&Operate=GET&RequestURI="+path+"&Date="+date;
        if(encryptedParams!=null && !encryptedParams.isEmpty())message+="&params="+encryptedParams;
        Mac mac=Mac.getInstance("HmacSHA1");
        mac.init(new SecretKeySpec(sessionSecret.getBytes(StandardCharsets.UTF_8),"HmacSHA1"));
        StringBuilder hex=new StringBuilder();
        for(byte b:mac.doFinal(message.getBytes(StandardCharsets.UTF_8)))hex.append(String.format(Locale.US,"%02X",b&255));
        return map("SessionKey",sessionKey,"Date",date,"Signature",hex.toString(),"X-Request-ID",UUID.randomUUID().toString());
    }
    private Map<String,String> suffix(Map<String,String> query) {
        query.put("clientType",PC);query.put("version",VERSION);query.put("channelId",CHANNEL);
        query.put("rand",Integer.toString(rng.nextInt(100000))+"_"+Long.toString(Math.abs(rng.nextLong()%10000000000L)));
        return query;
    }
    // OpenList v4.2.9 uses y.get(url, callback) for listFiles and
    // getFileDownloadUrl: the callback sets ordinary query parameters.
    // Only the separate request(params) overload AES-encrypts params.
    // Incorrectly encrypting these listing/link query arguments breaks them.
    private JSONObject apiGet(String path,Map<String,String> params) throws Exception {
        Map<String,String> query=suffix(new LinkedHashMap<String,String>(params));
        Reply r=request("GET",API+path,query,null,signedHeaders(path,""),true);
        JSONObject data=json(r.body);
        if(data.has("res_code")&&data.optInt("res_code",0)!=0) {
            nextRefresh=0;
            throw new IOException("Tianyi API rejected request");
        }
        return data;
    }
    private static final class FileObj {
        String name,id,parent;long size,mtime;boolean dir;
    }
    private List<FileObj> list(String folderId) throws Exception {
        long diagStart=TianyiDiag.tick();
        List<FileObj> out=new ArrayList<>();
        for(int page=1;page<=200;page++){
            JSONObject r=apiGet("/listFiles.action",map("folderId",folderId,"fileType","0","mediaAttr","0","iconOption","5",
                    "pageNum",Integer.toString(page),"pageSize","1000","recursive","0",
                    "orderBy","filename","descending","false"));
            JSONObject arr=r.optJSONObject("fileListAO");
            if(arr==null)throw new IOException("Cloud folder list unavailable");
            JSONArray folders=arr.optJSONArray("folderList"),files=arr.optJSONArray("fileList");
            int count=0;
            if(folders!=null)for(int i=0;i<folders.length();i++){JSONObject j=folders.getJSONObject(i);out.add(obj(j,true,folderId));count++;}
            if(files!=null)for(int i=0;i<files.length();i++){JSONObject j=files.getJSONObject(i);out.add(obj(j,false,folderId));count++;}
            if(count<1000)break;
        }
        TianyiDiag.event("DIRECTORY","OK",0,diagStart,out.size());
        return out;
    }
    private static FileObj obj(JSONObject j,boolean dir,String parent){
        FileObj f=new FileObj();f.name=j.optString("name","");f.id=j.optString("id","");f.dir=dir;
        f.size=dir?0:j.optLong("size",0L);f.parent=parent;f.mtime=System.currentTimeMillis();return f;
    }
    private FileObj resolve(String rel) throws Exception {
        FileObj root=new FileObj();root.dir=true;root.id="-11";root.name="";root.parent="";
        if(rel.isEmpty())return root;
        FileObj cursor=root;
        String[] parts=rel.split("/");
        for(String p:parts){
            if(p.isEmpty())continue;
            if(!cursor.dir)throw new FileNotFoundException();
            String target=URLDecoder.decode(p.replace("+","%2B"),"UTF-8");
            if(target.equals("..")||target.equals(".")||target.contains("/"))throw new FileNotFoundException();
            FileObj next=null;
            for(FileObj child:list(cursor.id))if(child.name.equals(target)){next=child;break;}
            if(next==null)throw new FileNotFoundException();
            cursor=next;
        }
        return cursor;
    }
    private String downloadUrl(FileObj f) throws Exception {
        long diagStart=TianyiDiag.tick();
        JSONObject data=apiGet("/getFileDownloadUrl.action",map("fileId",f.id,"dt","3","flag","1"));
        String url=data.optString("fileDownloadUrl","");
        if(url.isEmpty())throw new IOException("No download URL");
        url=url.replace("&amp;","&").replaceFirst("^http://","https://");
        if(url.startsWith("//"))url="https:"+url;
        if(!url.startsWith("https://"))throw new IOException("Insecure cloud download URL");
        TianyiDiag.event("FILE_LINK","OK",0,diagStart,f.size);
        return url;
    }
    private void handle(Socket socket){
        long diagStart=TianyiDiag.tick();
        boolean responseStarted=false;
        try{
            Socket s=socket;
            BufferedInputStream in=new BufferedInputStream(s.getInputStream());
            OutputStream out=new BufferedOutputStream(s.getOutputStream());
            String request=readLine(in);
            if(request==null)return;
            String[] fields=request.split(" ");
            if(fields.length<2){error(out,400);return;}
            String method=fields[0], raw=fields[1];
            final String davEvent = method.equals("PROPFIND")?"DAV_PROPFIND":
                    method.equals("GET")?"DAV_GET":method.equals("HEAD")?"DAV_HEAD":"DAV_OTHER";
            Map<String,String> headers=new HashMap<>();
            for(int n=0;n<80;n++){
                String line=readLine(in);if(line==null||line.isEmpty())break;
                int c=line.indexOf(':');if(c>0)headers.put(line.substring(0,c).trim().toLowerCase(Locale.US),line.substring(c+1).trim());
            }
            if(!raw.startsWith("/")){error(out,400);return;}
            String rawPath=raw.split("\\?",2)[0], key=store.getOrCreatePathKey();
            if(!rawPath.startsWith("/"+key+"/")){error(out,404);return;}
            String rel=rawPath.substring(key.length()+2);
            if(rel.contains("\\")||rel.length()>4096){error(out,400);return;}
            if(method.equals("OPTIONS")){
                respond(out,200,"DAV: 1\r\nAllow: OPTIONS, PROPFIND, GET, HEAD\r\nContent-Length: 0\r\n");return;
            }
            if(!method.equals("PROPFIND")&&!method.equals("GET")&&!method.equals("HEAD")){error(out,405);return;}
            FileObj f=resolve(rel);
            if(method.equals("PROPFIND")){
                ArrayList<FileObj> items=new ArrayList<>();items.add(f);
                if(f.dir&&!"0".equals(headers.get("depth")))items.addAll(list(f.id));
                String base="/"+key+"/"+rel;
                if(f.dir&&!base.endsWith("/"))base+="/";
                StringBuilder xml=new StringBuilder("<?xml version=\"1.0\" encoding=\"utf-8\"?><d:multistatus xmlns:d=\"DAV:\">");
                for(int i=0;i<items.size();i++){
                    FileObj item=items.get(i);
                    String href=i==0?base:base+encodeSegment(item.name)+(item.dir?"/":"");
                    xml.append("<d:response><d:href>").append(escapeXml(href)).append("</d:href><d:propstat><d:prop><d:displayname>")
                      .append(escapeXml(item.name)).append("</d:displayname><d:resourcetype>");
                    if(item.dir)xml.append("<d:collection/>");
                    xml.append("</d:resourcetype>");
                    if(!item.dir)xml.append("<d:getcontenttype>").append(escapeXml(contentType(item)))
                            .append("</d:getcontenttype>");
                    xml.append("<d:getcontentlength>").append(item.size)
                       .append("</d:getcontentlength><d:getlastmodified>Fri, 06 Nov 2026 00:00:00 GMT</d:getlastmodified>")
                       .append("</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>");
                }
                xml.append("</d:multistatus>");
                byte[] body=xml.toString().getBytes(StandardCharsets.UTF_8);
                responseStarted=true;
                respond(out,207,"Content-Type: application/xml; charset=utf-8\r\nContent-Length: "+body.length+"\r\n");
                out.write(body);out.flush();
                TianyiDiag.event("DAV_PROPFIND","OK",207,diagStart,items.size());
                return;
            }
            if(f.dir){error(out,405);return;}
            String url=downloadUrl(f);
            HttpURLConnection c=(HttpURLConnection)new URL(url).openConnection();
            c.setConnectTimeout(10000);c.setReadTimeout(30000);
            c.setRequestProperty("User-Agent","Mozilla/5.0");
            String range=headers.get("range");
            if(range!=null)c.setRequestProperty("Range",range);
            c.setInstanceFollowRedirects(true);
            c.setRequestMethod("GET");
            int status=c.getResponseCode();
            if(status!=200&&status!=206){c.disconnect();error(out,502);return;}
            if(range!=null&&status!=206){
                TianyiDiag.event("DAV_RANGE","FAIL",status,diagStart,0L);
                c.disconnect();error(out,502);return;
            }
            long length=c.getContentLengthLong();
            StringBuilder extra=new StringBuilder("Content-Type: "+contentType(f)+"\r\nAccept-Ranges: bytes\r\n");
            if(length>=0)extra.append("Content-Length: ").append(length).append("\r\n");
            if(c.getHeaderField("Content-Range")!=null)extra.append("Content-Range: ").append(c.getHeaderField("Content-Range")).append("\r\n");
            TianyiDiag.event(range!=null?"DAV_RANGE":davEvent,"OK",status,diagStart,length);
            responseStarted=true;
            respond(out,status,extra.toString());
            if(method.equals("HEAD")){c.disconnect();return;}
            try(InputStream source=c.getInputStream()){
                byte[] buf=new byte[65536];int n;
                while((n=source.read(buf))!=-1){out.write(buf,0,n);out.flush();}
            }finally{c.disconnect();}
        }catch(Exception ignored){
            TianyiDiag.event("DAV_REQUEST","FAIL",-1,diagStart,0L);
            // A lost cloud session must not leave the NOVA directory spinner
            // waiting for the socket timeout. Return a finite WebDAV error
            // before closing a request whose headers have not been sent.
            if(!responseStarted) {
                try { error(socket.getOutputStream(),503); }catch(Exception ignoredAgain){}
            }
        }finally{
            try { socket.close(); }catch(Exception ignoredAgain){}
        }
    }
    private static String contentType(FileObj file) {
        if(file.dir)return "httpd/unix-directory";
        String name=file.name==null?"":file.name.toLowerCase(Locale.US);
        if(name.endsWith(".mp4")||name.endsWith(".m4v"))return "video/mp4";
        if(name.endsWith(".mkv"))return "video/x-matroska";
        if(name.endsWith(".avi"))return "video/x-msvideo";
        if(name.endsWith(".m2ts")||name.endsWith(".mts")||name.endsWith(".ts"))return "video/mp2t";
        if(name.endsWith(".mov"))return "video/quicktime";
        if(name.endsWith(".webm"))return "video/webm";
        if(name.endsWith(".wmv"))return "video/x-ms-wmv";
        if(name.endsWith(".flv"))return "video/x-flv";
        if(name.endsWith(".rmvb")||name.endsWith(".rm"))return "application/vnd.rn-realmedia";
        if(name.endsWith(".mpeg")||name.endsWith(".mpg")||name.endsWith(".vob"))return "video/mpeg";
        if(name.endsWith(".iso"))return "application/x-iso9660-image";
        if(name.endsWith(".srt"))return "application/x-subrip";
        if(name.endsWith(".ass")||name.endsWith(".ssa"))return "text/plain";
        String guess=URLConnection.guessContentTypeFromName(name);
        return guess==null?"application/octet-stream":guess;
    }
    private static String encodeSegment(String s) throws Exception {
        return URLEncoder.encode(s,"UTF-8").replace("+","%20");
    }
    private static String escapeXml(String s){return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\"","&quot;");}
    private static String readLine(InputStream in)throws IOException {
        ByteArrayOutputStream b=new ByteArrayOutputStream();
        for(int i=0;i<8192;i++){int x=in.read();if(x==-1)break;if(x=='\n')break;if(x!='\r')b.write(x);}
        return b.toString("UTF-8");
    }
    private static void respond(OutputStream out,int status,String headers)throws IOException{
        String text=status==207?"Multi-Status":status==206?"Partial Content":status==200?"OK":"Error";
        out.write(("HTTP/1.1 "+status+" "+text+"\r\nConnection: close\r\n"+headers+"\r\n").getBytes(StandardCharsets.US_ASCII));out.flush();
    }
    private static void error(OutputStream out,int code)throws IOException{respond(out,code,"Content-Length: 0\r\n");}
    private static Map<String,String> map(String... kv){
        LinkedHashMap<String,String> m=new LinkedHashMap<>();for(int i=0;i<kv.length;i+=2)m.put(kv[i],kv[i+1]);return m;
    }
    private static String joinCookie(List<String> cookies){StringBuilder b=new StringBuilder();for(String c:cookies){if(b.length()>0)b.append("; ");b.append(c);}return b.toString();}
    private static String query(Map<String,String> m) throws Exception {
        if(m==null)return "";
        StringBuilder b=new StringBuilder();
        for(Map.Entry<String,String> e:m.entrySet()){
            if(b.length()>0)b.append('&');
            b.append(URLEncoder.encode(e.getKey(),"UTF-8")).append('=').append(URLEncoder.encode(e.getValue(),"UTF-8"));
        }return b.toString();
    }
    private static String param(String u,String key){
        try{String s=new URL(u).getQuery();if(s==null)return "";for(String p:s.split("&")){String[]kv=p.split("=",2);if(URLDecoder.decode(kv[0],"UTF-8").equals(key))return kv.length>1?URLDecoder.decode(kv[1],"UTF-8"):"";}}catch(Exception ignored){}return "";
    }
    private static String match(String s,String re){
        java.util.regex.Matcher m=java.util.regex.Pattern.compile(re).matcher(s);return m.find()?m.group(1):"";
    }
    private static JSONObject json(String text)throws JSONException {
        JSONObject j=new JSONObject(text);return j.optJSONObject("data")!=null&&j.optString("accessToken","").isEmpty()?
                (j.has("fileListAO")?j:j):j;
    }
    private static final class Reply{
        String body,url;
        Reply(String b,String u){body=b;url=u;}
    }
    private Reply request(String method,String url,Map<String,String> params,
                          Map<String,String> form,Map<String,String> headers,
                          boolean redirect)throws Exception {
        return request0(method,url,params,form,headers,redirect,0);
    }
    private Reply request0(String method,String url,Map<String,String> params,
                           Map<String,String> form,Map<String,String> headers,
                           boolean redirect,int hops)throws Exception {
        if(hops>8)throw new IOException("Too many Tianyi login redirects");
        String q=query(params);
        URL target=new URL(url+(q.isEmpty()?"":(url.contains("?")?"&":"?")+q));
        if(!"https".equalsIgnoreCase(target.getProtocol()))
            throw new IOException("Insecure Tianyi authentication URL");
        HttpURLConnection c=(HttpURLConnection)target.openConnection();
        c.setConnectTimeout(12000);
        c.setReadTimeout(12000);
        c.setInstanceFollowRedirects(false); // capture cookies from EVERY redirect
        c.setRequestMethod(method);
        c.setRequestProperty("Accept","application/json;charset=UTF-8");
        c.setRequestProperty("User-Agent","Mozilla/5.0");
        if(headers!=null)for(Map.Entry<String,String> e:headers.entrySet())
            c.setRequestProperty(e.getKey(),e.getValue());
        Map<String,List<String>> sent=cookies.get(target.toURI(),Collections.emptyMap());
        for(Map.Entry<String,List<String>> e:sent.entrySet())
            if(e.getKey()!=null&&!e.getValue().isEmpty())
                c.setRequestProperty(e.getKey(),joinCookie(e.getValue()));
        if(form!=null){
            byte[] data=query(form).getBytes(StandardCharsets.UTF_8);
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type","application/x-www-form-urlencoded;charset=UTF-8");
            try(OutputStream o=c.getOutputStream()){o.write(data);}
        }
        long diagStart=TianyiDiag.tick();
        int status=c.getResponseCode();
        TianyiDiag.event("CLOUD_HTTP",status>=400?"FAIL":"OK",status,diagStart,0L);
        cookies.put(target.toURI(),c.getHeaderFields());
        if(status>=300&&status<400&&redirect){
            String location=c.getHeaderField("Location");
            c.disconnect();
            if(location==null||location.isEmpty())
                throw new IOException("Redirect location missing");
            URL to=new URL(target,location);
            String host=to.getHost().toLowerCase(Locale.US);
            if(!"https".equalsIgnoreCase(to.getProtocol())
                  ||!(host.equals("cloud.189.cn")||host.equals("open.e.189.cn")
                     ||host.endsWith(".cloud.189.cn")||host.endsWith(".e.189.cn")))
                throw new IOException("Login redirected outside trusted Tianyi domains");
            boolean retain=(status==307||status==308);
            return request0(retain?method:"GET",to.toString(),null,
                            retain?form:null,headers,true,hops+1);
        }
        String finalUrl=c.getURL().toString();
        InputStream stream=status>=400?c.getErrorStream():c.getInputStream();
        String body="";
        if(stream!=null)try(InputStream in=stream){
            ByteArrayOutputStream out=new ByteArrayOutputStream();
            byte[] buf=new byte[8192];int n;
            while((n=in.read(buf))!=-1){
                out.write(buf,0,n);
                if(out.size()>4*1024*1024)throw new IOException("Oversize API response");
            }
            body=out.toString("UTF-8");
        }finally{c.disconnect();}
        if(status>=400)throw new IOException("Tianyi service HTTP "+status);
        return new Reply(body,finalUrl);
    }

}
