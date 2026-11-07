package com.archos.mediacenter.video.cloud189;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;

/** Resolve 189Cloud download URL like OpenList 189pc Link(): a non-following
 * GET HEADERS probe, then hand the actual CDN URL to native NOVA libcurl.
 * No video response bodies are read, buffered or forwarded in this class. */
public final class TianyiDirectLink {
    private TianyiDirectLink() {}

    public static final class Result {
        public final String url;
        public final int code;
        Result(String url,int code) {this.url=url;this.code=code;}
    }

    public static Result resolve(String initial) throws IOException {
        if(initial==null || initial.isEmpty() || initial.indexOf('\r')>=0 || initial.indexOf('\n')>=0)
            throw new IOException("Invalid cloud download URL");
        URL original=new URL(initial);
        validProtocol(original);
        HttpURLConnection request=null;
        try {
            request=(HttpURLConnection)original.openConnection();
            request.setConnectTimeout(10000);
            request.setReadTimeout(12000);
            request.setInstanceFollowRedirects(false);
            request.setRequestProperty("User-Agent","Mozilla/5.0");
            request.setRequestMethod("GET");
            int status=request.getResponseCode();
            if(status==301 || status==302 || status==303 || status==307 || status==308) {
                String location=request.getHeaderField("Location");
                if(location==null || location.isEmpty() ||
                   location.indexOf('\r')>=0 || location.indexOf('\n')>=0)
                    throw new IOException("Invalid cloud redirect Location");
                URL url=new URL(original,location);
                validProtocol(url);
                String target=url.toExternalForm();
                if(target.indexOf('\r')>=0 || target.indexOf('\n')>=0)
                    throw new IOException("Invalid cloud redirect target");
                return new Result(target,status);
            }
            if(status==200 || status==206)
                return new Result(initial,status);
            throw new IOException("Cloud download URL returned HTTP "+status);
        }finally {
            if(request!=null)request.disconnect();
        }
    }

    private static void validProtocol(URL url) throws IOException {
        String p=url.getProtocol();
        if(!"http".equalsIgnoreCase(p) && !"https".equalsIgnoreCase(p))
            throw new IOException("Unsupported download protocol");
    }
}
