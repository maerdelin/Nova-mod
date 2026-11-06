package com.archos.mediacenter.video.cloud189;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.ViewGroup;
import android.widget.*;
import android.widget.RelativeLayout;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import com.google.zxing.BarcodeFormat;
import com.google.zxing.common.BitMatrix;
import com.google.zxing.qrcode.QRCodeWriter;

/** One visual-only spinner item inserted after the original SMB (index 1 in MOD v6.6.4). */
public final class TianyiUi {
    public static final int NEW_UI_INDEX=2;
    private static final Handler MAIN=new Handler(Looper.getMainLooper());
    private static final Map<Object,AtomicInteger> GENERATIONS=Collections.synchronizedMap(new WeakHashMap<>());
    private static final Map<View,ImageView> IMAGES=Collections.synchronizedMap(new WeakHashMap<>());

    public static int toLegacyType(int uiIndex) {
        if(uiIndex==NEW_UI_INDEX)return 8;
        return uiIndex>NEW_UI_INDEX?uiIndex-1:uiIndex;
    }
    public static int toUiIndex(int legacyType) {
        return legacyType>=NEW_UI_INDEX?legacyType+1:legacyType;
    }
    public static boolean onConfirm(Object fragment,int uiIndex){
        if(uiIndex!=NEW_UI_INDEX)return false;
        TianyiDiag.event("UI_CONFIRM","QR_ONLY",0);
        Activity a=activity(fragment);
        if(a!=null)Toast.makeText(a,"请扫描二维码并在手机上确认",Toast.LENGTH_SHORT).show();
        return true;
    }
    public static boolean onSelection(Object fragment,View root,int selected){
        Activity ctx=activity(fragment);
        if(ctx==null||root==null)return selected==NEW_UI_INDEX;
        AtomicInteger generation;
        synchronized(GENERATIONS){
            generation=GENERATIONS.get(fragment);
            if(generation==null){generation=new AtomicInteger();GENERATIONS.put(fragment,generation);}
        }
        final int current=generation.incrementAndGet();
        TianyiDiag.event("UI_PROTOCOL","SELECT",selected);
        final boolean tianyi=selected==NEW_UI_INDEX;
        int[] ids=new int[]{resId(ctx,"remote"),resId(ctx,"port"),resId(ctx,"path"),
                resId(ctx,"username"),resId(ctx,"password"),resId(ctx,"domain"),
                resId(ctx,"save_password"),resId(ctx,"show_password_checkbox")};
        for(int id:ids)if(id!=0){View v=root.findViewById(id);if(v!=null)v.setVisibility(tianyi?View.GONE:View.VISIBLE);}
        // Other protocols previously hide SMB domain with their own existing listener.
        if(!tianyi){
            ImageView image=IMAGES.get(root);
            if(image!=null)image.setVisibility(View.GONE);
            return false;
        }
        View remote=root.findViewById(resId(ctx,"remote"));
        View spinner=root.findViewById(resId(ctx,"ssh_spinner"));
        if(!(remote!=null&&remote.getParent() instanceof RelativeLayout))return true;
        RelativeLayout row=(RelativeLayout)remote.getParent();
        ImageView qr=IMAGES.get(root);
        if(qr==null){
            qr=new ImageView(ctx);
            qr.setScaleType(ImageView.ScaleType.FIT_CENTER);
            int px=(int)(184*ctx.getResources().getDisplayMetrics().density);
            RelativeLayout.LayoutParams lp=new RelativeLayout.LayoutParams(px,px);
            if(spinner!=null)lp.addRule(RelativeLayout.END_OF,spinner.getId());
            lp.addRule(RelativeLayout.ALIGN_PARENT_TOP);
            lp.leftMargin=(int)(8*ctx.getResources().getDisplayMetrics().density);
            row.addView(qr,lp);
            IMAGES.put(root,qr);
        }
        final ImageView image=qr;
        image.setVisibility(View.VISIBLE);
        image.setImageDrawable(null);
        TianyiCloud cloud=TianyiCloud.get(ctx);
        final AtomicInteger guard=generation;
        cloud.beginLogin(new TianyiCloud.QrListener(){
            public void onCode(String code) {
                try {
                    BitMatrix bits=new QRCodeWriter().encode(code,BarcodeFormat.QR_CODE,400,400);
                    int width=bits.getWidth(),height=bits.getHeight();
                    int[] pixels=new int[width*height];
                    for(int y=0;y<height;y++)for(int x=0;x<width;x++)
                        pixels[y*width+x]=bits.get(x,y)?0xff000000:0xffffffff;
                    final Bitmap bitmap=Bitmap.createBitmap(width,height,Bitmap.Config.ARGB_8888);
                    bitmap.setPixels(pixels,0,width,0,0,width,height);
                    MAIN.post(()->{
                        if(guard.get()==current&&isShowing(fragment)) {
                            image.setImageBitmap(bitmap);
                            TianyiDiag.event("QR_DISPLAY","OK",0);
                        }
                    });
                }catch(Exception e){
                    TianyiDiag.event("QR_DISPLAY","FAIL",-1);
                    onStatus("无法生成登录二维码");
                }
            }
            public void onStatus(String message) {
                MAIN.post(()->{if(guard.get()==current&&isShowing(fragment))Toast.makeText(ctx,message,Toast.LENGTH_LONG).show();});
            }
            public void onAuthorized(String uri) {
                MAIN.post(()->{
                    if(guard.get()!=current||!isShowing(fragment))return;
                    try{
                        Uri rootUri=Uri.parse(uri);
                        Class<?> dbClass=Class.forName("com.archos.mediacenter.video.browser.ShortcutDb");
                        @SuppressWarnings({"unchecked","rawtypes"})
                        Object db=Enum.valueOf((Class<? extends Enum>)dbClass,"STATIC");
                        Method check=dbClass.getMethod("isShortcut",Context.class,String.class);
                        long existing=((Number)check.invoke(db,ctx,uri)).longValue();
                        if(existing<0){
                            Method save=dbClass.getMethod("insertShortcut",Context.class,Uri.class,String.class,String.class);
                            Object ok=save.invoke(db,ctx,rootUri,"天翼云盘","天翼云盘");
                            if(!(ok instanceof Boolean)||!((Boolean)ok))throw new IllegalStateException("无法保存网络快捷方式");
                        }
                        TianyiDiag.event("SHORTCUT_CREATE","OK",0);
                        Toast.makeText(ctx,"天翼云盘添加成功",Toast.LENGTH_SHORT).show();
                        guard.incrementAndGet();
                        Method dismiss=fragment.getClass().getMethod("dismiss");
                        dismiss.invoke(fragment);
                        Class<?> listing=Class.forName("com.archos.mediacenter.video.leanback.network.webdav.WebdavListingActivity");
                        Intent launch=new Intent(ctx,listing);
                        Class<?> base=Class.forName("com.archos.mediacenter.video.leanback.filebrowsing.ListingActivity");
                        launch.putExtra((String)base.getField("EXTRA_ROOT_URI").get(null),rootUri);
                        launch.putExtra((String)base.getField("EXTRA_ROOT_NAME").get(null),"天翼云盘");
                        ctx.startActivity(launch);
                    }catch(Exception e){
                        TianyiDiag.event("SHORTCUT_CREATE","FAIL",-1);
                        Toast.makeText(ctx,"账号已授权，但创建快捷方式失败",Toast.LENGTH_LONG).show();
                    }
                });
            }
        },()->guard.get()==current&&isShowing(fragment));
        return true;
    }
    private static boolean isShowing(Object f){
        try{
            Object dialog=f.getClass().getMethod("getDialog").invoke(f);
            if(!(dialog instanceof android.app.Dialog))return false;
            return ((android.app.Dialog)dialog).isShowing();
        }catch(Exception e){return false;}
    }
    private static Activity activity(Object fragment){
        try{
            Object a=fragment.getClass().getMethod("getActivity").invoke(fragment);
            return a instanceof Activity?(Activity)a:null;
        }catch(Exception e){return null;}
    }
    private static int resId(Context c,String name){return c.getResources().getIdentifier(name,"id",c.getPackageName());}
    private TianyiUi(){}
}
