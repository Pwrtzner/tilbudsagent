package dk.pwrtzner.tilbudsagent

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build

/** Notifikationer om ekstra gode tilbud. */
object Meldinger {
    private const val KANAL = "topkoeb"
    private const val ID = 4711

    fun tilladt(ctx: Context): Boolean {
        if (Build.VERSION.SDK_INT >= 33 &&
            ctx.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return false
        return ctx.getSystemService(NotificationManager::class.java).areNotificationsEnabled()
    }

    fun send(ctx: Context, titel: String, tekst: String, linjer: List<String>) {
        if (!tilladt(ctx)) return
        val nm = ctx.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(KANAL, "Ekstra gode tilbud", NotificationManager.IMPORTANCE_DEFAULT))
        val aaben = PendingIntent.getActivity(
            ctx, 0,
            Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val stil = Notification.InboxStyle()
        linjer.take(6).forEach { stil.addLine(it) }
        val n = Notification.Builder(ctx, KANAL)
            .setSmallIcon(R.drawable.ic_notif)
            .setContentTitle(titel)
            .setContentText(tekst)
            .setStyle(stil)
            .setContentIntent(aaben)
            .setAutoCancel(true)
            .build()
        nm.notify(ID, n)
    }
}
