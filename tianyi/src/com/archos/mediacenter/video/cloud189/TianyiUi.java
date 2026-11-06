package com.archos.mediacenter.video.cloud189;

import android.app.Activity;
import android.app.Dialog;
import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.RelativeLayout;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import com.google.zxing.BarcodeFormat;
import com.google.zxing.common.BitMatrix;
import com.google.zxing.qrcode.QRCodeWriter;

import java.lang.reflect.Method;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.WeakHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * QR-only row in the ORIGINAL NOVA 6.6.4 network connection dialog.
 *
 * Important: apktool/aapt2 and NOVA resource package IDs can differ. The old
 * implementation relied entirely on getIdentifier() for existing EditTexts
 * and silently returned with no QR panel. Locate existing views by their
 * verified XML hierarchy instead. Spinner, address, and the QR panel stay
 * inside the original RelativeLayout, side by side.
 */
public final class TianyiUi {
    public static final int NEW_UI_INDEX=2; // Screenshot: WebDAV, SMB, Tianyi, FTP...
    private static final Handler MAIN=new Handler(Looper.getMainLooper());
    private static final Map<Object,AtomicInteger> GENERATIONS =
            Collections.synchronizedMap(new WeakHashMap<>());
    private static final Map<View,QrPanel> PANELS =
            Collections.synchronizedMap(new WeakHashMap<>());

    public static int toLegacyType(int uiIndex) {
        if(uiIndex==NEW_UI_INDEX)return 8;
        return uiIndex>NEW_UI_INDEX?uiIndex-1:uiIndex;
    }
    public static int toUiIndex(int legacyType) {
        if(legacyType==8)return NEW_UI_INDEX;
        return legacyType>=NEW_UI_INDEX?legacyType+1:legacyType;
    }
    public static boolean onConfirm(Object fragment,int uiIndex) {
        if(uiIndex!=NEW_UI_INDEX)return false;
        TianyiDiag.event("UI_CONFIRM","QR_ONLY",0);
        Activity ctx=activity(fragment);
        if(ctx!=null)Toast.makeText(ctx,"请使用右侧二维码扫码授权",Toast.LENGTH_SHORT).show();
        return true;
    }
    private static final class QrPanel {
        final FrameLayout surface;
        final ImageView image;
        final ProgressBar spinner;
        final TextView message;
        QrPanel(FrameLayout s,ImageView i,ProgressBar p,TextView t) {
            surface=s;image=i;spinner=p;message=t;
        }
    }
    private static int dp(Context c,float n){return (int)(c.getResources().getDisplayMetrics().density*n+0.5f);}

    /** Called from the actual Smali Spinner onItemSelected listener. */
    public static boolean onSelection(Object fragment,View root,int selected) {
        try {
            return onSelectionInner(fragment,root,selected);
        } catch(RuntimeException ex) {
            TianyiDiag.event("UI_UNCAUGHT","FAIL",-1);
            Activity ctx=activity(fragment);
            if(ctx!=null)Toast.makeText(ctx,"天翼云盘界面初始化失败，请退出重试",Toast.LENGTH_LONG).show();
            return selected==NEW_UI_INDEX;
        }
    }
    private static boolean onSelectionInner(Object fragment,View root,int selected) {
        final boolean tianyi=selected==NEW_UI_INDEX;
        Activity activity=activity(fragment);
        if(activity==null || !(root instanceof LinearLayout)) {
            TianyiDiag.event("UI_LAYOUT","FAIL",1);
            return tianyi;
        }
        LinearLayout form=(LinearLayout)root;
        // network_credential_layout.xml:
        // 0: RelativeLayout(Spinner,remote), 1:port, 2:path, 3:username,
        // 4:password, 5:domain, 6:show-password, 7:save-password.
        if(form.getChildCount()<8 || !(form.getChildAt(0) instanceof RelativeLayout)) {
            TianyiDiag.event("UI_LAYOUT","FAIL",2);
            return tianyi;
        }
        RelativeLayout row=(RelativeLayout)form.getChildAt(0);
        if(row.getChildCount()<2 || !(row.getChildAt(0) instanceof Spinner)
                || !(row.getChildAt(1) instanceof EditText)) {
            TianyiDiag.event("UI_LAYOUT","FAIL",3);
            return tianyi;
        }
        Spinner protocol=(Spinner)row.getChildAt(0);
        View address=row.getChildAt(1);
        AtomicInteger gen;
        synchronized(GENERATIONS) {
            gen=GENERATIONS.get(fragment);
            if(gen==null){gen=new AtomicInteger();GENERATIONS.put(fragment,gen);}
        }
        final int current=gen.incrementAndGet();
        TianyiDiag.event("UI_PROTOCOL","SELECT",selected);
        QrPanel panel=PANELS.get(root);
        for(int i=1;i<form.getChildCount();i++)form.getChildAt(i).setVisibility(tianyi?View.GONE:View.VISIBLE);
        address.setVisibility(tianyi?View.GONE:View.VISIBLE);
        RelativeLayout.LayoutParams spinnerLp=(RelativeLayout.LayoutParams)protocol.getLayoutParams();
        if(tianyi) {
            spinnerLp.removeRule(RelativeLayout.ALIGN_BASELINE);
            spinnerLp.addRule(RelativeLayout.ALIGN_PARENT_TOP);
        } else {
            spinnerLp.removeRule(RelativeLayout.ALIGN_PARENT_TOP);
            spinnerLp.addRule(RelativeLayout.ALIGN_BASELINE,address.getId());
        }
        protocol.setLayoutParams(spinnerLp);

        if(!tianyi) {
            if(panel!=null)panel.surface.setVisibility(View.GONE);
            return false; // existing NOVA listener updates the SMB domain.
        }
        if(panel==null) {
            panel=createPanel(activity,row,protocol);
            PANELS.put(root,panel);
        }
        final QrPanel target=panel;
        target.surface.setVisibility(View.VISIBLE);
        showLoading(target,"正在获取天翼云盘二维码…");
        TianyiDiag.event("UI_PANEL","VISIBLE",0);
        target.surface.setOnClickListener(v -> {
            Object tag=v.getTag();
            if("retry".equals(tag))onSelection(fragment,root,NEW_UI_INDEX);
        });
        final AtomicInteger guard=gen;
        TianyiCloud.get(activity).beginLogin(new TianyiCloud.QrListener() {
            public void onCode(String uuid) {
                try {
                    // OpenList's PC driver QR content is the UUID *as returned by
                    // getUUID.do*. Never draw a static/demo QR code.
                    BitMatrix bits=new QRCodeWriter().encode(uuid,BarcodeFormat.QR_CODE,360,360);
                    int width=bits.getWidth(),height=bits.getHeight();
                    int[] pixels=new int[width*height];
                    for(int y=0;y<height;y++)
                        for(int x=0;x<width;x++)
                            pixels[y*width+x]=bits.get(x,y)?Color.BLACK:Color.WHITE;
                    Bitmap bitmap=Bitmap.createBitmap(width,height,Bitmap.Config.ARGB_8888);
                    bitmap.setPixels(pixels,0,width,0,0,width,height);
                    MAIN.post(()->{
                        if(guard.get()==current && isShowing(fragment)) {
                            target.image.setImageBitmap(bitmap);
                            target.image.setVisibility(View.VISIBLE);
                            target.spinner.setVisibility(View.GONE);
                            target.message.setVisibility(View.GONE);
                            target.surface.setTag("active");
                            TianyiDiag.event("QR_DISPLAY","OK",0);
                        }
                    });
                }catch(Exception e) {
                    TianyiDiag.event("QR_DISPLAY","FAIL",-1);
                    onStatus("生成二维码失败，点击重试");
                }
            }
            public void onStatus(String msg) {
                MAIN.post(()->{
                    if(guard.get()!=current || !isShowing(fragment))return;
                    if(msg.contains("确认")) {
                        Toast.makeText(activity,"请在手机天翼云盘中确认授权",Toast.LENGTH_SHORT).show();
                        return;
                    }
                    showError(target,"二维码加载失败，点击重试");
                    TianyiDiag.event("QR_STATUS","ERROR",0);
                    // Error details are reported by the cloud driver as
                    // privacy-safe diagnostic phase/class labels.
                    Toast.makeText(activity,msg,Toast.LENGTH_LONG).show();
                });
            }
            public void onAuthorized(String uri) {
                MAIN.post(()->{
                    if(guard.get()!=current || !isShowing(fragment))return;
                    try{
                        Uri rootUri=Uri.parse(uri);
                        if(!"webdav".equals(rootUri.getScheme())
                                ||!"127.0.0.1".equals(rootUri.getHost()))
                            throw new SecurityException("Invalid local WebDAV root");
                        Class<?> dbType=Class.forName("com.archos.mediacenter.video.browser.ShortcutDb");
                        @SuppressWarnings({"rawtypes","unchecked"})
                        Object db=Enum.valueOf((Class<? extends Enum>)dbType,"STATIC");
                        long existing=((Number)dbType.getMethod("isShortcut",Context.class,String.class)
                                .invoke(db,activity,uri)).longValue();
                        if(existing<0) {
                            Object inserted=dbType.getMethod("insertShortcut",Context.class,
                                    Uri.class,String.class,String.class)
                                    .invoke(db,activity,rootUri,"天翼云盘","天翼云盘");
                            if(!Boolean.TRUE.equals(inserted))
                                throw new IllegalStateException("shortcut insert returned false");
                        }
                        TianyiDiag.event("SHORTCUT_CREATE","OK",0);
                        guard.incrementAndGet();
                        // Refresh the existing network shortcuts row directly;
                        // don't attempt to launch an unrelated ListingActivity
                        // that may not exist in this optimized v6.6.4 APK.
                        refreshNetworkPage(fragment);
                        fragment.getClass().getMethod("dismiss").invoke(fragment);
                        Toast.makeText(activity,"天翼云盘已添加到网络存储",Toast.LENGTH_SHORT).show();
                    }catch(Exception e) {
                        TianyiDiag.event("SHORTCUT_CREATE","FAIL",-1);
                        showError(target,"添加快捷方式失败，点击重试");
                        Toast.makeText(activity,"授权成功，但网络快捷方式保存失败",Toast.LENGTH_LONG).show();
                    }
                });
            }
        },()->guard.get()==current && isShowing(fragment));
        return true;
    }

    private static QrPanel createPanel(Context ctx,RelativeLayout row,Spinner protocol) {
        FrameLayout container=new FrameLayout(ctx);
        int size=dp(ctx,194);
        RelativeLayout.LayoutParams params=new RelativeLayout.LayoutParams(size,size);
        params.addRule(RelativeLayout.RIGHT_OF,protocol.getId());
        params.addRule(RelativeLayout.ALIGN_PARENT_TOP);
        params.leftMargin=dp(ctx,9);
        params.bottomMargin=dp(ctx,6);
        row.addView(container,params);
        GradientDrawable white=new GradientDrawable();
        white.setColor(Color.WHITE);
        white.setCornerRadius(dp(ctx,5));
        container.setBackground(white);
        ImageView image=new ImageView(ctx);
        image.setScaleType(ImageView.ScaleType.FIT_CENTER);
        image.setPadding(dp(ctx,7),dp(ctx,7),dp(ctx,7),dp(ctx,7));
        FrameLayout.LayoutParams fill=new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.MATCH_PARENT);
        container.addView(image,fill);
        image.setVisibility(View.GONE);
        ProgressBar progress=new ProgressBar(ctx);
        FrameLayout.LayoutParams progressLp=new FrameLayout.LayoutParams(dp(ctx,35),dp(ctx,35),Gravity.CENTER);
        container.addView(progress,progressLp);
        TextView msg=new TextView(ctx);
        msg.setGravity(Gravity.CENTER);
        msg.setTextSize(12);
        msg.setTextColor(Color.DKGRAY);
        FrameLayout.LayoutParams msgLp=new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,dp(ctx,53),Gravity.BOTTOM);
        container.addView(msg,msgLp);
        return new QrPanel(container,image,progress,msg);
    }
    private static void showLoading(QrPanel p,String message) {
        p.surface.setTag("loading");
        p.image.setVisibility(View.GONE);
        p.spinner.setVisibility(View.VISIBLE);
        p.message.setText(message);
        p.message.setVisibility(View.VISIBLE);
    }
    private static void showError(QrPanel p,String message) {
        p.surface.setTag("retry");
        p.image.setVisibility(View.GONE);
        p.spinner.setVisibility(View.GONE);
        p.message.setGravity(Gravity.CENTER);
        p.message.setText(message);
        p.message.setVisibility(View.VISIBLE);
    }
    private static void refreshNetworkPage(Object dialog) throws Exception {
        Object manager=dialog.getClass().getMethod("getParentFragmentManager").invoke(dialog);
        if(manager==null)throw new IllegalStateException("No FragmentManager");
        Object out=manager.getClass().getMethod("getFragments").invoke(manager);
        if(!(out instanceof List))throw new IllegalStateException("No active fragments");
        for(Object f:(List<?>)out) {
            if(f!=null && "com.archos.mediacenter.video.leanback.network.NetworkRootFragment"
                    .equals(f.getClass().getName())) {
                Method refresh=f.getClass().getMethod("novaTianyiRefreshShortcuts");
                refresh.invoke(f);
                TianyiDiag.event("NETWORK_REFRESH","OK",0);
                return;
            }
        }
        throw new IllegalStateException("Network page not active");
    }
    private static boolean isShowing(Object fragment) {
        try {
            Object dialog=fragment.getClass().getMethod("getDialog").invoke(fragment);
            return dialog instanceof Dialog && ((Dialog)dialog).isShowing();
        }catch(Exception ignored){return false;}
    }
    private static Activity activity(Object fragment) {
        try {
            Object a=fragment.getClass().getMethod("getActivity").invoke(fragment);
            return a instanceof Activity?(Activity)a:null;
        }catch(Exception ignored){return null;}
    }
    private TianyiUi(){}
}
