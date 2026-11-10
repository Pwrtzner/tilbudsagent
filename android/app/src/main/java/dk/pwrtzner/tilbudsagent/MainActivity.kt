package dk.pwrtzner.tilbudsagent

import android.Manifest
import android.app.Activity
import android.content.ContentValues
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.provider.MediaStore
import android.view.Gravity
import android.view.ViewGroup
import android.webkit.ConsoleMessage
import android.webkit.GeolocationPermissions
import android.webkit.JavascriptInterface
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.TextView
import android.widget.Toast
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * Tynd skal: starter Python-serveren (samme kode som på pc) og viser den i en WebView.
 * Al forretningslogik ligger i Python-filerne; her er kun Android-limen (GPS, filvalg, download).
 */
class MainActivity : Activity() {

    companion object {
        private const val PORT = 18765
        private const val URL_BASE = "http://127.0.0.1:$PORT/"
        private const val REQ_LOKATION = 11
        private const val REQ_FIL = 12
        private const val REQ_NOTIF = 13

        @Volatile private var pythonStartet = false
    }

    private lateinit var web: WebView
    private lateinit var status: TextView
    private var geoOrigin: String? = null
    private var geoCallback: GeolocationPermissions.Callback? = null
    private var filCallback: ValueCallback<Array<Uri>>? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val rod = FrameLayout(this)
        web = WebView(this)
        status = TextView(this).apply {
            text = "Starter Tilbudsagent …"
            textSize = 16f
            setTextColor(Color.DKGRAY)
            gravity = Gravity.CENTER
        }
        rod.addView(web, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        rod.addView(status, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        setContentView(rod)
        web.visibility = android.view.View.INVISIBLE
        opsaetWeb()
        web.addJavascriptInterface(Bro(), "AndroidApp")
        startPython()
        roegtestKrog(intent)
        ventPaaServer()
    }

    // bruges af røgtesten: start ét baggrundsjob med det samme
    private fun roegtestKrog(i: Intent?) {
        if (i?.getBooleanExtra("worker_test", false) == true) Planlaeg.nu(this)
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        roegtestKrog(intent)
    }

    private fun opsaetWeb() {
        val s = web.settings
        s.javaScriptEnabled = true
        s.domStorageEnabled = true
        s.cacheMode = WebSettings.LOAD_NO_CACHE
        s.setGeolocationEnabled(true)
        s.userAgentString = s.userAgentString + " TilbudsagentAndroid"
        web.setBackgroundColor(Color.TRANSPARENT)

        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(v: WebView, r: WebResourceRequest): Boolean {
                if (r.url.host == "127.0.0.1") return false
                try { startActivity(Intent(Intent.ACTION_VIEW, r.url)) } catch (_: Exception) {}
                return true
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onGeolocationPermissionsShowPrompt(origin: String, cb: GeolocationPermissions.Callback) {
                if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
                    cb.invoke(origin, true, false)
                } else {
                    geoOrigin = origin; geoCallback = cb
                    requestPermissions(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION), REQ_LOKATION)
                }
            }

            override fun onShowFileChooser(v: WebView, cb: ValueCallback<Array<Uri>>, p: FileChooserParams): Boolean {
                filCallback?.onReceiveValue(null)
                filCallback = cb
                val i = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = "*/*"
                }
                return try { startActivityForResult(i, REQ_FIL); true } catch (_: Exception) { filCallback = null; false }
            }

            override fun onConsoleMessage(m: ConsoleMessage): Boolean {
                android.util.Log.d("Tilbudsagent", "${m.message()} (${m.sourceId()}:${m.lineNumber()})")
                return true
            }
        }
        // Eksport/fejlrapport: hent filen fra den lokale server og læg den i Downloads
        web.setDownloadListener { url, _, disp, mime, _ -> gemFil(url, disp, mime) }
    }

    private fun startPython() {
        if (pythonStartet) return
        pythonStartet = true
        val (res, data) = Opsaet.mapper(this)  // kopieres ved hver start, så opdateringer slår igennem
        val py = Opsaet.python(this)
        Thread {
            try {
                py.getModule("android_main")
                    .callAttr("start", res.absolutePath, data.absolutePath, PORT)
            } catch (e: Throwable) {
                android.util.Log.e("Tilbudsagent", "Python stoppede", e)
                pythonStartet = false
                runOnUiThread { status.text = "Appen kunne ikke starte:\n${e.message}" }
            }
        }.start()
    }

    /** Funktioner, siden kan kalde (window.AndroidApp): baggrundshentning og notifikationer. */
    inner class Bro {
        @JavascriptInterface
        fun status(): String {
            val p = getSharedPreferences("indst", MODE_PRIVATE)
            return JSONObject().put("baggrund", p.getBoolean("baggrund", false)).put("timer", p.getInt("timer", 12))
                .put("notif", Meldinger.tilladt(this@MainActivity))
                .put("batteri", getSystemService(android.os.PowerManager::class.java).isIgnoringBatteryOptimizations(packageName))
                .put("sidste", p.getLong("sidste_tid", 0L)).put("sidste_tekst", p.getString("sidste_tekst", "") ?: "")
                .toString()
        }

        @JavascriptInterface
        fun saet(aktiv: Boolean, timer: Int) { Planlaeg.saet(this@MainActivity, aktiv, timer.coerceIn(6, 48)) }

        @JavascriptInterface
        fun tilladelse() {
            runOnUiThread {
                if (android.os.Build.VERSION.SDK_INT >= 33) {
                    requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQ_NOTIF)
                } else {
                    startActivity(Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                        .putExtra(android.provider.Settings.EXTRA_APP_PACKAGE, packageName))
                }
            }
        }

        @JavascriptInterface
        fun test() {
            Meldinger.send(this@MainActivity, "Test fra Tilbudsagent", "Sådan ser en besked om et ekstra godt tilbud ud.",
                listOf("Kyllingebryst 55,50 kr/kg, Netto (−44 %)", "Bananer 9,00 kr/kg, REMA 1000 (−55 %)"))
        }

        @JavascriptInterface
        fun nu() { Planlaeg.nu(this@MainActivity); hold() }

        /** Holder appen vågen, mens en hentning kører (kaldes, når du trykker «Hent tilbud»). */
        @JavascriptInterface
        fun hold() {
            runOnUiThread {
                try { startForegroundService(Intent(this@MainActivity, HentTjeneste::class.java)) }
                catch (e: Exception) { android.util.Log.w("Tilbudsagent", "kunne ikke starte hent-tjeneste", e) }
            }
        }

        @JavascriptInterface
        fun batteri() {
            runOnUiThread {
                try {
                    startActivity(Intent(android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                        .setData(android.net.Uri.parse("package:$packageName")))
                } catch (e: Exception) {
                    startActivity(Intent(android.provider.Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
                }
            }
        }
    }

    private fun serverKlar(): Boolean = try {
        val c = URL(URL_BASE + "api/ping").openConnection() as HttpURLConnection
        c.connectTimeout = 800; c.readTimeout = 800
        val ok = c.responseCode == 200 && c.inputStream.bufferedReader().readText().contains("tilbudsagent")
        c.disconnect(); ok
    } catch (_: Exception) { false }

    private fun ventPaaServer() {
        Thread {
            for (i in 0 until 120) {
                if (serverKlar()) {
                    runOnUiThread {
                        status.visibility = android.view.View.GONE
                        web.visibility = android.view.View.VISIBLE
                        web.loadUrl(URL_BASE)
                    }
                    return@Thread
                }
                Thread.sleep(250)
            }
            runOnUiThread { status.text = "Serveren svarede ikke.\nLuk appen helt og prøv igen." }
        }.start()
    }

    private fun gemFil(url: String, disp: String?, mime: String?) {
        Thread {
            try {
                val navn = URLUtil.guessFileName(url, disp, mime)
                val c = URL(url).openConnection() as HttpURLConnection
                val bytes = c.inputStream.use { it.readBytes() }
                c.disconnect()
                val v = ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, navn)
                    put(MediaStore.Downloads.MIME_TYPE, mime ?: "application/octet-stream")
                    put(MediaStore.Downloads.RELATIVE_PATH, "Download/Tilbudsagent")
                }
                val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v)!!
                contentResolver.openOutputStream(uri)!!.use { it.write(bytes) }
                runOnUiThread { Toast.makeText(this, "Gemt i Downloads/Tilbudsagent: $navn", Toast.LENGTH_LONG).show() }
            } catch (e: Exception) {
                runOnUiThread { Toast.makeText(this, "Kunne ikke gemme filen: ${e.message}", Toast.LENGTH_LONG).show() }
            }
        }.start()
    }

    override fun onRequestPermissionsResult(code: Int, perms: Array<out String>, res: IntArray) {
        if (code == REQ_LOKATION) {
            geoCallback?.invoke(geoOrigin, res.any { it == PackageManager.PERMISSION_GRANTED }, false)
            geoCallback = null
        }
    }

    @Deprecated("bruges til filvalg")
    override fun onActivityResult(req: Int, res: Int, data: Intent?) {
        if (req == REQ_FIL) {
            val uri = if (res == RESULT_OK) data?.data else null
            filCallback?.onReceiveValue(if (uri != null) arrayOf(uri) else null)
            filCallback = null
        }
    }

    @Deprecated("tilbage-knap")
    override fun onBackPressed() {
        // luk en åben dialog først; ellers læg appen i baggrunden (serveren kører videre)
        web.evaluateJavascript("(function(){var d=document.querySelector('dialog[open]');if(d){d.close();return 1}return 0})()") {
            if (it != "1") moveTaskToBack(true)
        }
    }

    override fun onResume() {
        super.onResume()
        web.onResume()
        web.evaluateJavascript("if(typeof load==='function'&&document.visibilityState==='visible'){load()}", null)
    }

    override fun onPause() {
        web.onPause()
        super.onPause()
    }
}
