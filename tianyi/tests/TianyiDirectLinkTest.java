package com.archos.mediacenter.video.cloud189;

import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.util.concurrent.atomic.AtomicInteger;

public final class TianyiDirectLinkTest {
    private static void check(boolean ok,String message) {
        if(!ok)throw new AssertionError(message);
    }
    public static void main(String[] args) throws Exception {
        HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        AtomicInteger probes=new AtomicInteger();
        server.createContext("/redirect",ex->{
            probes.incrementAndGet();
            ex.getResponseHeaders().add("Location","https://cdn.example.invalid/movie.iso?key=abc%2F123&exp=123");
            ex.sendResponseHeaders(302,-1);ex.close();
        });
        server.createContext("/relative",ex->{
            ex.getResponseHeaders().add("Location","/stream.iso?a=1");
            ex.sendResponseHeaders(307,-1);ex.close();
        });
        server.createContext("/direct",ex->{ex.sendResponseHeaders(200,-1);ex.close();});
        server.createContext("/partial",ex->{ex.sendResponseHeaders(206,-1);ex.close();});
        server.createContext("/unsafe",ex->{
            ex.getResponseHeaders().add("Location","file:///etc/passwd");
            ex.sendResponseHeaders(302,-1);ex.close();
        });
        server.createContext("/error",ex->{ex.sendResponseHeaders(503,-1);ex.close();});
        server.start();
        String base="http://127.0.0.1:"+server.getAddress().getPort();
        try {
            TianyiDirectLink.Result a=TianyiDirectLink.resolve(base+"/redirect");
            check(a.code==302 && a.url.equals("https://cdn.example.invalid/movie.iso?key=abc%2F123&exp=123"),
                    "CDN Location or signed query modified");
            check(probes.get()==1,"Expected one non-following probe");
            TianyiDirectLink.Result b=TianyiDirectLink.resolve(base+"/relative");
            check(b.code==307 && b.url.equals(base+"/stream.iso?a=1"),"Relative redirect broken");
            TianyiDirectLink.Result c=TianyiDirectLink.resolve(base+"/direct");
            check(c.code==200 && c.url.equals(base+"/direct"),"Direct URL broken");
            TianyiDirectLink.Result d=TianyiDirectLink.resolve(base+"/partial");
            check(d.code==206 && d.url.equals(base+"/partial"),"CDN 206 link broken");
            for(String suffix:new String[]{"/unsafe","/error"}) {
                boolean rejected=false;
                try {TianyiDirectLink.resolve(base+suffix);}catch(IOException ok){rejected=true;}
                check(rejected,"Unsafe or broken upstream response accepted");
            }
            System.out.println("ALL TIANYI DIRECT CDN LINK TESTS PASS");
        }finally {server.stop(0);}
    }
}
