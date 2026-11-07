package com.archos.mediacenter.video.cloud189;

import java.io.IOException;
import java.net.URLDecoder;
import java.net.URLEncoder;

/**
 * Canonical URI paths for the loopback WebDAV service.
 *
 * Real NOVA clients may issue a PROPFIND whose request target contains
 * unescaped square brackets, spaces or other filename punctuation.
 * Echoing that raw request path into <d:href> produces invalid Java URIs:
 * Sardine's DavResource throws URISyntaxException and silently excludes
 * the file from the visible folder.
 *
 * Decode each incoming path COMPONENT once, then percent-encode the full
 * parent hierarchy and the final leaf independently. Never URL-encode the
 * entire slash-delimited path, or use HTML/XML escaping in place of URI
 * escaping. File names are preserved byte-for-byte after UTF-8 decoding.
 */
final class TianyiDavPaths {
    private TianyiDavPaths() {}

    static String decodeSegment(String onWire) throws IOException {
        if(onWire==null || onWire.isEmpty())
            throw new IOException("Empty WebDAV URI component");
        final String name;
        try {
            // '+' in a URI PATH is a literal plus, not an HTML-form space.
            name=URLDecoder.decode(onWire.replace("+","%2B"),"UTF-8");
        }catch(IllegalArgumentException badEncoding) {
            throw new IOException("Malformed percent escape in WebDAV path",badEncoding);
        }
        if(name.isEmpty() || name.equals(".") || name.equals("..")
                || name.indexOf('/')>=0 || name.indexOf('\u0000')>=0)
            throw new IOException("Invalid decoded WebDAV path component");
        return name;
    }

    static String encodeSegment(String name) throws IOException {
        if(name==null || name.isEmpty())
            throw new IOException("Missing WebDAV resource name");
        return URLEncoder.encode(name,"UTF-8").replace("+","%20");
    }

    static String canonicalBase(String key,String rawRelative,boolean directory)
            throws IOException {
        if(key==null || key.isEmpty())
            throw new IOException("Missing WebDAV capability key");
        StringBuilder uri=new StringBuilder("/").append(key).append("/");
        boolean hasChild=false;
        if(rawRelative!=null && !rawRelative.isEmpty()) {
            for(String component:rawRelative.split("/",-1)) {
                if(component.isEmpty()) continue; // normalize trailing slash
                uri.append(encodeSegment(decodeSegment(component))).append("/");
                hasChild=true;
            }
        }
        if(!directory && hasChild)uri.setLength(uri.length()-1);
        return uri.toString();
    }
}
