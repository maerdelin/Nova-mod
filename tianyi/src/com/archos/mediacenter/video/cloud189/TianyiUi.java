package com.archos.mediacenter.video.cloud189;

import android.app.Activity;
import android.app.Dialog;
import android.content.Context;
import android.database.Cursor;
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
import android.widget.BaseAdapter;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.RelativeLayout;
import android.widget.Spinner;
import android.widget.SpinnerAdapter;
import android.widget.TextView;
import android.widget.Toast;

import com.google.zxing.BarcodeFormat;
import com.google.zxing.common.BitMatrix;
import com.google.zxing.qrcode.QRCodeWriter;

import java.lang.reflect.Method;
import java.lang.ref.WeakReference;
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
    // Original Always-new protocol IDs: WebDAV=0, SMB=1, FTP=2,
    // SFTP=3, FTPS=4, SSHJ=5, SMBJ=6, WebDAVS=7.
    // The Tianyi UI item is inserted at position 1 (second); it never
    // flows into NOVA's native UriUtils protocol handling.
    public static final int NEW_UI_INDEX=1;
    private static final Handler MAIN=new Handler(Looper.getMainLooper());
    private static final Map<Object,AtomicInteger> GENERATIONS =
            Collections.synchronizedMap(new WeakHashMap<>());
    private static final Map<View,QrPanel> PANELS =
            Collections.synchronizedMap(new WeakHashMap<>());
    // Restore the original Always-new layout after leaving Tianyi mode;
    // do not make every protocol field VISIBLE (some are protocol-specific).
    private static final Map<View,FormState> ORIGINAL_FORMS =
            Collections.synchronizedMap(new WeakHashMap<>());
    private static final class FormState {
        final int[] visibility;
        final int addressVisibility;
        final RelativeLayout.LayoutParams spinnerLayout;
        FormState(LinearLayout form,View address,Spinner spinner) {
            visibility=new int[form.getChildCount()];
            for(int i=1;i<form.getChildCount();i++)
                visibility[i]=form.getChildAt(i).getVisibility();
            addressVisibility=address.getVisibility();
            spinnerLayout=new RelativeLayout.LayoutParams(
                    (RelativeLayout.LayoutParams)spinner.getLayoutParams());
        }
        void restore(LinearLayout form,View address,Spinner spinner) {
            for(int i=1;i<form.getChildCount() && i<visibility.length;i++)
                form.getChildAt(i).setVisibility(visibility[i]);
            address.setVisibility(addressVisibility);
            spinner.setLayoutParams(new RelativeLayout.LayoutParams(spinnerLayout));
        }
    }

    /** Locate the cloud shortcut in NOVA's actual database, not stale prefs. */
    private static boolean isTianyiUri(String raw) {
        if(raw==null)return false;
        try {
            Uri candidate=Uri.parse(raw);
            List<String> segments=candidate.getPathSegments();
            return "webdav".equalsIgnoreCase(candidate.getScheme())
                    && "127.0.0.1".equals(candidate.getHost())
                    && candidate.getPort()==27989
                    && segments!=null && !segments.isEmpty()
                    && segments.get(0).matches("[0-9a-fA-F]{48}");
        }catch(Exception ignored){return false;}
    }
    public static boolean hasExistingShortcut(Context ctx) {
        if(ctx==null)return false;
        Cursor cursor=null;
        try {
            Class<?> cls=Class.forName("com.archos.mediacenter.video.browser.ShortcutDb");
            @SuppressWarnings({"rawtypes","unchecked"})
            Object db=Enum.valueOf((Class<? extends Enum>)cls,"STATIC");
            cursor=(Cursor)cls.getMethod("getCursorAllShortcuts",Context.class)
                    .invoke(db,ctx);
            if(cursor!=null) {
                int index=cursor.getColumnIndex("uri");
                if(index>=0)while(cursor.moveToNext()) {
                    if(isTianyiUri(cursor.getString(index)))return true;
                }
            }
            return false;
        }catch(Exception e) {
            TianyiDiag.event("SHORTCUT_LOOKUP","FAIL",-1);
            // If DB is temporarily unavailable, do not overwrite saved login.
            return !new TianyiStore(ctx).existingPathKey().isEmpty();
        }finally{
            if(cursor!=null)cursor.close();
        }
    }
    /**
     * A disabled ListAdapter row is actually non-clickable in the Spinner
     * popup; only the new Tianyi row is changed. All original IDs are kept.
     */
    private static final class GuardedProtocols extends BaseAdapter {
        final SpinnerAdapter delegate;
        final Context context;
        GuardedProtocols(SpinnerAdapter adapter,Context ctx){
            delegate=adapter;context=ctx.getApplicationContext();
        }
        @Override public int getCount(){return delegate.getCount();}
        @Override public Object getItem(int position){return delegate.getItem(position);}
        @Override public long getItemId(int position){return delegate.getItemId(position);}
        @Override public boolean hasStableIds(){return delegate.hasStableIds();}
        @Override public boolean areAllItemsEnabled(){return !hasExistingShortcut(context);}
        @Override public boolean isEnabled(int position){
            return position!=NEW_UI_INDEX || !hasExistingShortcut(context);
        }
        private View tint(View view,int position){
            if(view==null)return null;
            boolean disabled=position==NEW_UI_INDEX && hasExistingShortcut(context);
            view.setAlpha(disabled?0.35f:1f);
            view.setEnabled(!disabled);
            return view;
        }
        @Override public View getView(int index,View old,ViewGroup parent){
            return tint(delegate.getView(index,old,parent),index);
        }
        @Override public View getDropDownView(int index,View old,ViewGroup parent){
            return tint(delegate.getDropDownView(index,old,parent),index);
        }
    }
    public static void installProtocolGuard(Spinner spinner) {
        if(spinner==null)return;
        SpinnerAdapter adapter=spinner.getAdapter();
        if(adapter==null || adapter instanceof GuardedProtocols)return;
        int old=spinner.getSelectedItemPosition();
        spinner.setAdapter(new GuardedProtocols(adapter,spinner.getContext()));
        if(old>=0)spinner.setSelection(old,false);
    }

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
        Activity ctx=activity(fragment);
        if(ctx!=null && hasExistingShortcut(ctx)) {
            Toast.makeText(ctx,"天翼云盘已添加，请先删除原快捷方式",Toast.LENGTH_SHORT).show();
            TianyiDiag.event("UI_CONFIRM","DUPLICATE_BLOCKED",0);
            return true;
        }
        TianyiDiag.event("UI_CONFIRM","QR_ONLY",0);
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
        if(tianyi && hasExistingShortcut(activity)) {
            protocol.setSelection(0);
            Toast.makeText(activity,"天翼云盘已添加，请先删除原快捷方式",Toast.LENGTH_SHORT).show();
            TianyiDiag.event("UI_PROTOCOL","DUPLICATE_BLOCKED",0);
            return true;
        }
        AtomicInteger gen;
        synchronized(GENERATIONS) {
            gen=GENERATIONS.get(fragment);
            if(gen==null){gen=new AtomicInteger();GENERATIONS.put(fragment,gen);}
        }
        final int current=gen.incrementAndGet();
        TianyiDiag.event("UI_PROTOCOL","SELECT",selected);
        QrPanel panel=PANELS.get(root);
        if(!tianyi) {
            // Undo Tianyi-only UI changes, then let the ORIGINAL listener
            // decide SMB/SMBJ domain and all legacy protocol state.
            FormState original=ORIGINAL_FORMS.remove(root);
            if(original!=null)original.restore(form,address,protocol);
            if(panel!=null)panel.surface.setVisibility(View.GONE);
            return false;
        }
        if(!ORIGINAL_FORMS.containsKey(root))
            ORIGINAL_FORMS.put(root,new FormState(form,address,protocol));
        for(int i=1;i<form.getChildCount();i++)
            form.getChildAt(i).setVisibility(View.GONE);
        address.setVisibility(View.GONE);
        RelativeLayout.LayoutParams spinnerLp=(RelativeLayout.LayoutParams)protocol.getLayoutParams();
        spinnerLp.removeRule(RelativeLayout.ALIGN_BASELINE);
        spinnerLp.addRule(RelativeLayout.ALIGN_PARENT_TOP);
        protocol.setLayoutParams(spinnerLp);

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
                    // Never blank an already-rendered QR for a later network
                    // or account-state error. Keep it visible until the scan
                    // challenge expires; the message remains separately visible.
                    boolean qrVisible=target.image.getVisibility()==View.VISIBLE;
                    if(qrVisible) {
                        target.surface.setTag("retry");
                        target.spinner.setVisibility(View.GONE);
                        target.message.setText(msg.length()<85 ? msg : "网络异常，点击重试");
                        target.message.setVisibility(View.VISIBLE);
                        target.message.bringToFront();
                    } else {
                        showError(target,msg.length()<85 ? msg : "登录失败，点击重试");
                    }
                    TianyiDiag.event("QR_STATUS","ERROR",0);
                    // Error details are reported by the cloud driver as
                    // privacy-safe diagnostic phase/class labels.
                    Toast.makeText(activity,msg,Toast.LENGTH_LONG).show();
                });
            }
            public void onAuthorized(String uri) {
                MAIN.post(()->saveAuthorizedShortcut(fragment,activity,target,guard,current,uri));
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
    // The FragmentManager APIs were renamed in this optimized NOVA build.
    // The network page registers itself from its real onResume Smali hook.
    // Keep only a weak reference: this must not leak an Activity.
    private static volatile WeakReference<Object> activeNetworkPage=new WeakReference<>(null);

    public static void registerNetworkPage(Object page) {
        if(page==null)return;
        activeNetworkPage=new WeakReference<>(page);
        // The optimized NetworkRootFragment does not reliably dispatch
        // onResume after a cold start. Trigger asynchronous DAV restore when
        // the network page is first created, too.
        Activity owner=activity(page);
        if(owner!=null)TianyiCloud.startIfSaved(owner);
    }

    /**
     * Saves the verified local DAV URI in NOVA's existing ShortcutDb.
     * A previously saved URI is success (idempotent, no duplicate shortcut).
     */
    /** Only NOVA's private loopback cloud URI gets a friendly list title.
     * All other existing network shortcut labels pass through unchanged. */
    public static String displayCloudShortcutName(String path,String oldName) {
        // Some optimized phone/tablet adapters supply only a random DAV
        // capability segment as their visible title, not its full URI.
        // Compare against the SAVED key so ordinary WebDAV paths are intact.
        if(TianyiCloud.isOwnShortcutLabel(oldName)
                || TianyiCloud.isOwnShortcutLabel(path))
            return "天翼云盘";
        if(path==null)return oldName;
        try {
            if(isTianyiUri(path))
                return "天翼云盘";
        }catch(Exception ignored){}
        return oldName;
    }

    public static boolean installCloudShortcut(Context ctx,String rawUri) throws Exception {
        Uri uri=Uri.parse(rawUri);
        if(!"webdav".equals(uri.getScheme())
                ||!"127.0.0.1".equals(uri.getHost())
                ||uri.getPort()!=27989
                ||uri.getPathSegments().isEmpty()
                ||uri.getPathSegments().get(0).length()<32)
            throw new SecurityException("Invalid local cloud DAV address");
        Class<?> cls=Class.forName("com.archos.mediacenter.video.browser.ShortcutDb");
        @SuppressWarnings({"rawtypes","unchecked"})
        Object db=Enum.valueOf((Class<? extends Enum>)cls,"STATIC");
        Method exists=cls.getMethod("isShortcut",Context.class,String.class);
        long already=((Number)exists.invoke(db,ctx,rawUri)).longValue();
        if(already>=0)return true;
        if(hasExistingShortcut(ctx))
            throw new IllegalStateException("Only one Tianyi shortcut is allowed");
        Object result=cls.getMethod("insertShortcut",Context.class,
                Uri.class,String.class,String.class)
                .invoke(db,ctx,uri,"天翼云盘","天翼云盘");
        if(!Boolean.TRUE.equals(result))throw new IllegalStateException("ShortcutDb insert failed");
        long persisted=((Number)exists.invoke(db,ctx,rawUri)).longValue();
        if(persisted<0)throw new IllegalStateException("ShortcutDb persistence check failed");
        return true;
    }

    private static void saveAuthorizedShortcut(Object fragment,Activity activity,
                                                QrPanel panel,AtomicInteger guard,
                                                int generation,String uri) {
        if(guard.get()!=generation || !isShowing(fragment))return;
        try {
            installCloudShortcut(activity,uri);
            TianyiDiag.event("SHORTCUT_SAVE","OK",0);
        }catch(Exception saveError) {
            TianyiDiag.event("SHORTCUT_SAVE","FAIL",-1);
            // The phone is already authorized. Retrying a local database
            // operation must NEVER start a second cloud QR login request.
            showError(panel,"授权成功，保存失败，点击重试");
            panel.surface.setTag("retry-save");
            panel.surface.setOnClickListener(v->{
                if("retry-save".equals(v.getTag()))
                    saveAuthorizedShortcut(fragment,activity,panel,guard,generation,uri);
            });
            Toast.makeText(activity,"授权已成功，重新保存不需要扫码",Toast.LENGTH_LONG).show();
            return;
        }
        // Invalidate pending QR callbacks before any asynchronous list reload.
        guard.incrementAndGet();
        // The dialog dismissal already works on the user's device.
        // Reload ONCE after its transition instead of immediately loading
        // and cancelling that task 500 ms later (which loses adapter results).
        dismissAuthorizedDialog(fragment);
        scheduleNetworkRefresh(0,activity);
        Toast.makeText(activity,"天翼云盘已保存，正在更新网络列表",Toast.LENGTH_SHORT).show();
    }

    private static void dismissAuthorizedDialog(Object fragment) {
        try {
            fragment.getClass().getMethod("dismiss").invoke(fragment);
            TianyiDiag.event("QR_DIALOG","DISMISSED",0);
            return;
        }catch(Exception ignored){}
        try {
            fragment.getClass().getMethod("dismissAllowingStateLoss").invoke(fragment);
            TianyiDiag.event("QR_DIALOG","DISMISSED",0);
            return;
        }catch(Exception ignored){}
        // Works with the original DialogFragment even when its AndroidX
        // library methods have been renamed by the APK optimizer.
        try {
            Object dialog=fragment.getClass().getMethod("getDialog").invoke(fragment);
            if(dialog instanceof Dialog) {
                ((Dialog)dialog).dismiss();
                TianyiDiag.event("QR_DIALOG","DISMISSED",0);
                return;
            }
        }catch(Exception ignored){}
        TianyiDiag.event("QR_DIALOG","FAIL",-1);
    }

    private static void scheduleNetworkRefresh(int attempt,Activity owner) {
        MAIN.postDelayed(()->{
            boolean ready=false;
            try { ready=refreshNetworkPage(); }
            catch(Exception ignored) { TianyiDiag.event("NETWORK_REFRESH_RETRY","FAIL",-1); }
            if(ready)return;
            // In some original NOVA phone layouts the active Network page
            // is not NetworkRootFragment (the leanback class we patched).
            // The original activity lifecycle will reload ShortcutDb after
            // a single recreate. This avoids a dead shortcut list and is
            // ONLY used when the targeted loader was unavailable.
            if(attempt<2) {
                scheduleNetworkRefresh(attempt+1,owner);
            } else if(owner!=null && !owner.isFinishing() && !owner.isDestroyed()) {
                TianyiDiag.event("NETWORK_REFRESH","RECREATE",0);
                owner.recreate();
            }
        },attempt==0?350:400);
    }

    private static boolean refreshNetworkPage() throws Exception {
        WeakReference<Object> ref=activeNetworkPage;
        Object page=ref==null?null:ref.get();
        if(page==null) {
            TianyiDiag.event("NETWORK_REFRESH","UNAVAILABLE",0);
            return false;
        }
        // Smali bridge runs the SAME NetworkShortcutsLoaderTask that NOVA
        // uses on onResume; reuses its existing adapter and thread handling.
        page.getClass().getMethod("novaTianyiRefreshShortcuts").invoke(page);
        TianyiDiag.event("NETWORK_REFRESH","OK",0);
        return true;
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
