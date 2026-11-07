package com.archos.mediacenter.video.cloud189;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;

/**
 * Persistent local-only WebDAV listener for the saved Tianyi shortcut.
 *
 * This is a real Android foreground service, not a daemon Thread that
 * accidentally disappears when NOVA is moved to the background. The user
 * sees an ongoing low-importance status notification while it is active.
 * START_STICKY permits Android to recreate the service after process
 * reclamation, then the same saved port/capability are restored.
 */
public final class TianyiDavService extends Service {
    private static final String CHANNEL="nova_tianyi_local_dav";
    private static final int NOTIFICATION_ID=18927989;

    @Override public void onCreate() {
        super.onCreate();
        try {
            if(Build.VERSION.SDK_INT>=26) {
                NotificationChannel channel=new NotificationChannel(CHANNEL,
                        "天翼云盘本地 WebDAV",NotificationManager.IMPORTANCE_LOW);
                channel.setDescription("保持 NOVA 的本地天翼云盘目录连接");
                NotificationManager manager=(NotificationManager)getSystemService(NOTIFICATION_SERVICE);
                if(manager!=null)manager.createNotificationChannel(channel);
            }
            Notification.Builder b=Build.VERSION.SDK_INT>=26
                    ?new Notification.Builder(this,CHANNEL):new Notification.Builder(this);
            b.setContentTitle("NOVA 天翼云盘")
                    .setContentText("本地 WebDAV 已开启")
                    .setSmallIcon(android.R.drawable.stat_sys_download_done)
                    .setOngoing(true)
                    .setCategory(Notification.CATEGORY_SERVICE);
            if(Build.VERSION.SDK_INT>=29) {
                startForeground(NOTIFICATION_ID,b.build(),
                        ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
            }else {
                startForeground(NOTIFICATION_ID,b.build());
            }
            TianyiDiag.event("DAV_SERVICE","FOREGROUND",0);
            TianyiCloud.get(this).restoreAsync();
        }catch(RuntimeException cannotForeground) {
            TianyiDiag.event("DAV_SERVICE","FAIL",-1);
            stopSelf();
        }
    }
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        TianyiCloud.get(this).restoreAsync();
        return START_STICKY;
    }
    @Override public IBinder onBind(Intent intent) {return null;}
    @Override public void onDestroy() {
        TianyiDiag.event("DAV_SERVICE","DESTROYED",0);
        super.onDestroy();
    }
}
