package com.dario.gastos

import android.annotation.SuppressLint
import android.graphics.Color
import android.os.Bundle
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var swipeRefresh: SwipeRefreshLayout
    private var isInClassicWeb: Boolean = false

    inner class AndroidBridge {
        @JavascriptInterface
        fun getToken(): String {
            return Prefs.getToken(this@MainActivity) ?: ""
        }

        @JavascriptInterface
        fun getSelectedBudgetId(): Int {
            return Prefs.getLastBudgetId(this@MainActivity)
        }

        @JavascriptInterface
        fun onTokenReceived(token: String, username: String) {
            runOnUiThread {
                if (token.isNotEmpty()) {
                    val current = Prefs.getToken(this@MainActivity)
                    Prefs.saveToken(this@MainActivity, token, username)
                    GastosWidgetProvider.notifyUpdate(this@MainActivity)
                    if (current != token) {
                        Toast.makeText(this@MainActivity, "✓ Cuenta y Widget sincronizados", Toast.LENGTH_SHORT).show()
                    }
                }
            }
        }

        @JavascriptInterface
        fun onBudgetSelected(id: Int, name: String, remaining: Double, available: Double, percent: Double) {
            runOnUiThread {
                if (id > 0) {
                    Prefs.setSelectedBudgetId(this@MainActivity, id)
                    Prefs.saveWidgetData(this@MainActivity, id, name, remaining, available, percent)
                    GastosWidgetProvider.notifyUpdate(this@MainActivity)
                }
            }
        }

        @JavascriptInterface
        fun openClassicWeb(path: String) {
            runOnUiThread {
                isInClassicWeb = true
                val base = Prefs.getBaseUrl(this@MainActivity).trimEnd('/')
                val cleanPath = if (path.startsWith("/")) path else "/$path"
                webView.loadUrl("$base$cleanPath")
            }
        }
    }

    private fun loadRedesignedApp() {
        isInClassicWeb = false
        val baseUrl = Prefs.getBaseUrl(this).trimEnd('/')
        try {
            val html = assets.open("app.html").bufferedReader(Charsets.UTF_8).use { it.readText() }
            webView.loadDataWithBaseURL(
                "$baseUrl/",
                html,
                "text/html",
                "UTF-8",
                "$baseUrl/app/"
            )
        } catch (e: Exception) {
            webView.loadUrl("$baseUrl/app/")
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.parseColor("#0D0F16")
        window.navigationBarColor = Color.parseColor("#12141D")
        setContentView(R.layout.activity_main)

        webView = findViewById(R.id.webView)
        swipeRefresh = findViewById(R.id.swipeRefresh)
        webView.setBackgroundColor(Color.parseColor("#0D0F16"))

        // Setup SwipeRefresh
        swipeRefresh.setColorSchemeColors(Color.parseColor("#6758E8"), Color.parseColor("#55D2AD"))
        swipeRefresh.setProgressBackgroundColorSchemeColor(Color.parseColor("#151821"))
        swipeRefresh.setOnRefreshListener {
            if (isInClassicWeb) {
                webView.reload()
            } else {
                webView.evaluateJavascript("if(window.reloadAppData) window.reloadAppData();", null)
                swipeRefresh.postDelayed({ swipeRefresh.isRefreshing = false }, 600)
            }
        }

        // Configure WebView
        val settings: WebSettings = webView.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.databaseEnabled = true
        settings.useWideViewPort = true
        settings.loadWithOverviewMode = true
        settings.cacheMode = WebSettings.LOAD_DEFAULT

        val cookieManager = CookieManager.getInstance()
        cookieManager.setAcceptCookie(true)
        cookieManager.setAcceptThirdPartyCookies(webView, true)

        webView.addJavascriptInterface(AndroidBridge(), "AndroidBridge")

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                return false
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                swipeRefresh.isRefreshing = false
                cookieManager.flush()

                if (isInClassicWeb) {
                    val jsAutoSync = """
                        (function() {
                            try {
                                fetch('/api/auth/token/', { credentials: 'include' })
                                    .then(function(r) { return r.json(); })
                                    .then(function(d) {
                                        if (d && d.success && d.token && window.AndroidBridge) {
                                            window.AndroidBridge.onTokenReceived(d.token, d.username || '');
                                        }
                                    })
                                    .catch(function(e) {});
                            } catch(err) {}
                        })();
                    """.trimIndent()
                    webView.evaluateJavascript(jsAutoSync, null)
                }

                if (!Prefs.getToken(this@MainActivity).isNullOrEmpty()) {
                    GastosWidgetProvider.notifyUpdate(this@MainActivity)
                }
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                if (newProgress == 100) {
                    swipeRefresh.isRefreshing = false
                }
            }
        }

        loadRedesignedApp()

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (isInClassicWeb) {
                    if (webView.canGoBack()) {
                        webView.goBack()
                    } else {
                        loadRedesignedApp()
                    }
                } else if (webView.canGoBack()) {
                    webView.goBack()
                } else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })
    }

    override fun onResume() {
        super.onResume()
        if (!isInClassicWeb && ::webView.isInitialized) {
            webView.evaluateJavascript("if(window.reloadAppData) window.reloadAppData();", null)
        }
    }
}
