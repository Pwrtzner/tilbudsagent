package dk.pwrtzner.tilbudsagent

import android.content.Context
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File

/** Fælles opsætning for aktiviteten og baggrundsjobbet (de kører i samme proces og deler Python). */
object Opsaet {
    @Synchronized
    fun python(ctx: Context): Python {
        if (!Python.isStarted()) Python.start(AndroidPlatform(ctx.applicationContext))
        return Python.getInstance()
    }

    /** Kopierer app.html, config.toml og varer.csv til appens mappe. Returnerer (res, data). */
    @Synchronized
    fun mapper(ctx: Context, kopier: Boolean = true): Pair<File, File> {
        val res = File(ctx.filesDir, "res").apply { mkdirs() }
        if (kopier || !File(res, "config.toml").exists()) {
            ctx.assets.list("res")?.forEach { navn ->
                ctx.assets.open("res/$navn").use { inp -> File(res, navn).outputStream().use { inp.copyTo(it) } }
            }
        }
        val data = File(ctx.filesDir, "data").apply { mkdirs() }
        return Pair(res, data)
    }
}
