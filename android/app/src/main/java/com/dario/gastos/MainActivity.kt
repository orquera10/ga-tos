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

    inner class AndroidBridge {
        @JavascriptInterface
        fun onTokenReceived(token: String, username: String) {
            runOnUiThread {
                if (token.isNotEmpty()) {
                    val current = Prefs.getToken(this@MainActivity)
                    if (current != token) {
                        Prefs.saveToken(this@MainActivity, token, username)
                        GastosWidgetProvider.notifyUpdate(this@MainActivity)
                        Toast.makeText(this@MainActivity, "✓ Widget sincronizado automáticamente", Toast.LENGTH_SHORT).show()
                    }
                }
            }
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        webView = findViewById(R.id.webView)
        swipeRefresh = findViewById(R.id.swipeRefresh)

        // Setup SwipeRefresh
        swipeRefresh.setColorSchemeColors(Color.parseColor("#00D09C"))
        swipeRefresh.setProgressBackgroundColorSchemeColor(Color.parseColor("#1E1E1E"))
        swipeRefresh.setOnRefreshListener {
            webView.reload()
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

                // Sincronización automática silenciosa del token para el Widget con la sesión activa
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

        val targetUrl = Prefs.getBaseUrl(this)
        webView.loadUrl(targetUrl)

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (webView.canGoBack()) {
                    webView.goBack()
                } else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })
    }
}
