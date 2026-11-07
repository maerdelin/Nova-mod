package com.archos.mediacenter.video.cloud189;

import java.io.IOException;
import java.net.URI;
import java.net.URISyntaxException;
import java.util.Arrays;
import java.util.List;

/** Regression for real 2026-11-07 logs: "Ignore resource with invalid URI". */
public final class TianyiDavPathsTest {
    private static void check(boolean value,String message) {
        if(!value)throw new AssertionError(message);
    }
    private static void reject(String label,String raw) throws Exception {
        try {
            new URI(raw);
            throw new AssertionError("Expected URISyntaxException: "+label);
        }catch(URISyntaxException expected){
            System.out.println("REPRODUCED: "+label+" invalid raw URI");
        }
    }
    private static void checkHref(String uri) throws Exception {
        URI parsed=new URI(uri);
        check(parsed.getRawPath().equals(uri),"URI path changed during parsing");
        check(uri.indexOf('[')<0 && uri.indexOf(']')<0 && uri.indexOf(' ')<0,
                "WebDAV href contains illegal raw path characters");
        check(!uri.contains("%255B")&&!uri.contains("%255D"),
                "Double encoded square bracket in URI");
    }
    private static void expectInvalid(String wire) throws Exception {
        try {
            TianyiDavPaths.canonicalBase("abcdef",wire,true);
            throw new AssertionError("Accepted malformed path: "+wire);
        }catch(IOException expected) {
            System.out.println("PASS: blocked invalid wire path");
        }
    }
    public static void main(String[] args)throws Exception {
        String key="abcdef0123456789abcdef0123456789abcdef0123456789";
        reject("raw [www] parent","/"+key+"/%E5%BD%B1%E8%A7%86/[www.hmxz.org]/movie.mkv");
        reject("unescaped space","/"+key+"/Movies/Some Movie/file.mkv");

        String relative="%E5%BD%B1%E8%A7%86/%E7%94%B5%E5%BD%B1/"
                +"[www.hmxz.org]%E5%93%AA%E5%90%92[HDR+%E5%9B%BD%E8%AF%AD]/";
        String parent=TianyiDavPaths.canonicalBase(key,relative,true);
        checkHref(parent);
        check(parent.contains("%5Bwww.hmxz.org%5D"),"Raw [www] prefix was not encoded");
        check(parent.contains("%5BHDR%2B"),"Bracket/plus punctuation not encoded");
        check(parent.endsWith("/"),"Directory lost its trailing slash");
        System.out.println("PASS: real-log Chinese movie parent path re-encoded");

        String leaf="(www.example.com)Ne.Zha.[HDR+] 2019.mkv.m2ts";
        String child=parent+TianyiDavPaths.encodeSegment(leaf);
        checkHref(child);
        check(child.endsWith(".mkv.m2ts"),"Video leaf name was changed");
        check(child.contains("%28www.example.com%29"),"Parenthesis was not escaped");
        System.out.println("PASS: movie in square-bracket parent passes new URI");

        String encodedRelative=parent.substring(key.length()+2);
        check(parent.equals(TianyiDavPaths.canonicalBase(key,encodedRelative,true)),
                "Already encoded URI was double-encoded");
        check(parent.equals(TianyiDavPaths.canonicalBase(key,relative,true)),
                "Equivalent raw and encoded parents disagree");

        List<String> names=Arrays.asList(
            "[sample] Movie (2026) + HDR.mkv",
            "中文 +[]()#?%&!'「特效」.mkv",
            "movie 100%.mkv",
            "plus+literal.mp4",
            "A+B[foo](test).m2ts"
        );
        for(String name:names) {
            String encoded=TianyiDavPaths.encodeSegment(name);
            String roundTrip=TianyiDavPaths.decodeSegment(encoded);
            check(name.equals(roundTrip),"Filename was changed: "+name);
            checkHref(parent+encoded);
        }
        System.out.println("PASS: Unicode, plus, percent, spaces, square brackets and symbols");

        String rawPlus=TianyiDavPaths.canonicalBase(key,"A+B%20[4K+]/",true);
        check(rawPlus.contains("A%2BB%20%5B4K%2B%5D"),
                "Literal + in request URI was decoded as a form space");
        checkHref(rawPlus);

        String deep=TianyiDavPaths.canonicalBase(key,
                "[www.hmxz.org]%20QA%20[4K+]%20(2026)/[Nested]%20QA/",true);
        checkHref(deep);
        check(deep.contains("%5BNested%5D%20QA/"),
                "Nested bracket parent did not canonicalize");
        String deepLeaf=TianyiDavPaths.canonicalBase(key,
                "[www.hmxz.org]%20QA%20[4K+]%20(2026)/[Nested]%20QA/"
                +"%5BSample%5D%20Nested%20Movie.mkv",false);
        checkHref(deepLeaf);
        check(!deepLeaf.endsWith("/"),"File href erroneously ends in slash");

        String root=TianyiDavPaths.canonicalBase(key,"",true);
        check(("/"+key+"/").equals(root),"Root URL changed");
        expectInvalid("movie/%2Fsecret");
        expectInvalid("movie/%2e%2e/");
        expectInvalid("movie/%ZZbad");
        System.out.println("ALL TIANYI DAV URI CANONICALIZATION TESTS PASS");
    }
}
