package com.najibrahimi.freevpn;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.VpnService;
import android.os.Build;
import android.os.ParcelFileDescriptor;
import android.util.Log;

import java.io.FileInputStream;
import java.io.FileOutputStream;

/** سرویس VpnService: TUN میسازد و بستهها را به Tun2Socks تحویل میدهد. */
public class FreeVpnService extends VpnService implements Runnable {
    private static final String TAG = "FreeVPN/Service";
    public static final String ACTION_CONNECT = "com.najibrahimi.freevpn.CONNECT";
    public static final String ACTION_DISCONNECT = "com.najibrahimi.freevpn.DISCONNECT";

    private volatile boolean running;
    private ParcelFileDescriptor tun;
    private Thread thread;
    private Tun2Socks tun2socks;

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_DISCONNECT.equals(intent.getAction())) {
            stopAll();
            return START_NOT_STICKY;
        }
        if (running) return START_STICKY;
        startForegroundNotification();
        running = true;
        thread = new Thread(this, "freevpn-tun");
        thread.start();
        return START_STICKY;
    }

    @Override
    public void run() {
        try {
            SharedPreferences p = getSharedPreferences("freevpn", Context.MODE_PRIVATE);
            String host = p.getString("host", "");
            String token = p.getString("token", "");
            String uuid = p.getString("uuid", "");
            int port = p.getInt("port", 443);
            boolean tls = p.getBoolean("tls", true);
            if (host.isEmpty() || token.isEmpty() || uuid.isEmpty()) {
                throw new IllegalStateException("config is empty — open the app and paste your link");
            }

            Builder b = new Builder();
            b.setSession("FreeVPN");
            b.addAddress("10.0.0.2", 32);
            b.addRoute("0.0.0.0", 0);
            b.addDnsServer("1.1.1.1");
            b.addDnsServer("8.8.8.8");
            b.setMtu(1500);
            // اپ خودمان نباید وارد تونل شود، وگرنه حلقه بیپایان میسازد
            try {
                b.addDisallowedApplication(getPackageName());
            } catch (Exception ignored) {
                Log.w(TAG, "could not exclude own package from VPN");
            }
            tun = b.establish();
            if (tun == null) {
                throw new IllegalStateException("VPN permission was not granted");
            }

            FileInputStream in = new FileInputStream(tun.getFileDescriptor());
            FileOutputStream out = new FileOutputStream(tun.getFileDescriptor());
            tun2socks = new Tun2Socks(this, out, host, port, token, uuid, tls);
            Log.i(TAG, "VPN established -> " + host + ":" + port);

            byte[] buf = new byte[32768];
            while (running) {
                int n = in.read(buf);
                if (n <= 0) break;
                tun2socks.handlePacket(buf, n);
            }
        } catch (Exception e) {
            Log.e(TAG, "VPN stopped: " + e, e);
        } finally {
            stopAll();
        }
    }

    @Override
    public void onDestroy() {
        stopAll();
        super.onDestroy();
    }

    @Override
    public void onRevoke() {
        stopAll();
        super.onRevoke();
    }

    private void stopAll() {
        running = false;
        if (tun2socks != null) {
            tun2socks.shutdown();
            tun2socks = null;
        }
        if (tun != null) {
            try { tun.close(); } catch (Exception ignored) {}
            tun = null;
        }
        if (thread != null) {
            thread.interrupt();
            thread = null;
        }
        stopForeground(true);
        stopSelf();
    }

    private void startForegroundNotification() {
        String channel = "freevpn";
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            NotificationChannel ch = new NotificationChannel(channel, "FreeVPN",
                    NotificationManager.IMPORTANCE_LOW);
            nm.createNotificationChannel(ch);
        }
        Notification.Builder nb;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nb = new Notification.Builder(this, channel);
        } else {
            nb = new Notification.Builder(this);
        }
        nb.setSmallIcon(android.R.drawable.ic_dialog_info)
          .setContentTitle("FreeVPN")
          .setContentText("در حال اجرا — برای قطع کردن اپ را باز کن")
          .setOngoing(true);
        startForeground(1, nb.build());
    }
}
