package dk.pwrtzner.tilbudsagent

import android.content.Context
import android.util.Log
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import org.json.JSONObject
import java.util.Locale
import java.util.concurrent.TimeUnit

/** Henter tilbud i baggrunden og melder nye ekstra gode tilbud. Al logik ligger i Python (webapp.baggrundshent). */
class HentWorker(ctx: Context, p: WorkerParameters) : Worker(ctx, p) {
    override fun doWork(): Result {
        return try {
            val (res, data) = Opsaet.mapper(applicationContext, kopier = false)
            val json = Opsaet.python(applicationContext).getModule("android_main")
                .callAttr("hent_baggrund", res.absolutePath, data.absolutePath).toString()
            Log.i("Tilbudsagent", "worker færdig: ${json.take(300)}")
            val svar = JSONObject(json)
            val nye = svar.getJSONArray("nye")
            val fejlTekst = svar.optString("fejl", "")
            applicationContext.getSharedPreferences("indst", Context.MODE_PRIVATE).edit()
                .putLong("sidste_tid", System.currentTimeMillis())
                .putString("sidste_tekst", if (fejlTekst.isNotEmpty()) fejlTekst else if (nye.length() == 0) "ingen nye ekstra gode tilbud" else "${nye.length()} nye ekstra gode tilbud")
                .apply()
            if (nye.length() > 0) {
                val dk = Locale("da", "DK")
                val linjer = (0 until nye.length()).map {
                    val o = nye.getJSONObject(it)
                    val ep = if (o.isNull("ep")) "" else String.format(dk, " %.2f kr/%s", o.getDouble("ep"), o.getString("enhed"))
                    val rabat = if (o.isNull("rabat")) "" else String.format(dk, " (−%d %%)", Math.round(o.getDouble("rabat") * 100))
                    "${o.getString("vare")}$ep, ${o.getString("butik_navn")}$rabat"
                }
                val titel = if (nye.length() == 1) "Ét nyt ekstra godt tilbud" else "${nye.length()} nye ekstra gode tilbud"
                Meldinger.send(applicationContext, titel, linjer.first(), linjer)
            }
            Result.success()
        } catch (e: Throwable) {
            Log.e("Tilbudsagent", "worker fejlede", e)
            applicationContext.getSharedPreferences("indst", Context.MODE_PRIVATE).edit()
                .putLong("sidste_tid", System.currentTimeMillis())
                .putString("sidste_tekst", "fejl: ${e.message ?: e.javaClass.simpleName}").apply()
            Result.success()  // næste planlagte kørsel prøver igen
        }
    }
}

object Planlaeg {
    private const val NAVN = "hent-baggrund"

    private fun krav() = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

    fun saet(ctx: Context, aktiv: Boolean, timer: Int) {
        ctx.getSharedPreferences("indst", Context.MODE_PRIVATE).edit()
            .putBoolean("baggrund", aktiv).putInt("timer", timer).apply()
        val wm = WorkManager.getInstance(ctx)
        if (!aktiv) { wm.cancelUniqueWork(NAVN); return }
        val req = PeriodicWorkRequestBuilder<HentWorker>(timer.toLong(), TimeUnit.HOURS).setConstraints(krav()).build()
        wm.enqueueUniquePeriodicWork(NAVN, ExistingPeriodicWorkPolicy.UPDATE, req)
    }

    fun nu(ctx: Context) {
        android.util.Log.i("Tilbudsagent", "baggrundsjob bestilt")
        WorkManager.getInstance(ctx).enqueue(OneTimeWorkRequestBuilder<HentWorker>().build())
    }
}
