package dk.pwrtzner.tilbudsagent

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log

/**
 * Holder appen i live, mens en hentning kører, også når du skifter til en anden app eller skærmen slukkes.
 * Selve hentningen kører i Python; tjenesten venter, til den er færdig, og lukker så sig selv.
 */
class HentTjeneste : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("hent", "Henter tilbud", NotificationManager.IMPORTANCE_LOW))
        val n = Notification.Builder(this, "hent")
            .setSmallIcon(R.drawable.ic_notif)
            .setContentTitle("Henter tilbud …")
            .setContentText("Tilbudsagent henter tilbud fra Tjek.")
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 29) startForeground(77, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        else startForeground(77, n)
        val laas = getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "tilbudsagent:hent")
        laas.acquire(25 * 60 * 1000L)
        Thread {
            try {
                val modul = Opsaet.python(this).getModule("android_main")
                var set = false
                var ventet = 0
                while (ventet < 750) {  // højst cirka 25 minutter
                    val koerer = modul.callAttr("hent_koerer").toBoolean()
                    if (koerer) set = true
                    if (!koerer && (set || ventet >= 8)) break  // 8 x 2 sek. til hentningen når at starte
                    Thread.sleep(2000)
                    ventet++
                }
            } catch (e: Throwable) {
                Log.e("Tilbudsagent", "hent-tjeneste fejlede", e)
            } finally {
                if (laas.isHeld) laas.release()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }.start()
        return START_NOT_STICKY
    }
}
