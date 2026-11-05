package com.dario.gastos

import android.annotation.SuppressLint
import android.app.Dialog
import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.os.Bundle
import android.view.View
import android.view.Window
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var swipeRefresh: SwipeRefreshLayout
    private lateinit var btnLinkWidget: Button
    private lateinit var btnSelectBudget: Button

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        webView = findViewById(R.id.webView)
        swipeRefresh = findViewById(R.id.swipeRefresh)
        btnLinkWidget = findViewById(R.id.btnLinkWidget)
        btnSelectBudget = findViewById(R.id.btnSelectBudget)

        updateButtonsStatus()
        btnLinkWidget.setOnClickListener { showLinkDialog() }
        btnSelectBudget.setOnClickListener {
            startActivity(Intent(this, SelectBudgetActivity::class.java))
        }

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

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                return false
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                swipeRefresh.isRefreshing = false
                cookieManager.flush()
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

    override fun onResume() {
        super.onResume()
        updateButtonsStatus()
    }

    private fun updateButtonsStatus() {
        val token = Prefs.getToken(this)
        if (!token.isNullOrEmpty()) {
            btnLinkWidget.text = "✓ Conectado"
            btnLinkWidget.setTextColor(Color.parseColor("#00E676"))
            btnSelectBudget.visibility = View.VISIBLE
        } else {
            btnLinkWidget.text = "Vincular"
            btnLinkWidget.setTextColor(Color.parseColor("#FFFFFF"))
            btnSelectBudget.visibility = View.GONE
        }
    }

    private fun showLinkDialog() {
        val dialog = Dialog(this)
        dialog.requestWindowFeature(Window.FEATURE_NO_TITLE)
        dialog.setContentView(R.layout.dialog_link_widget)
        dialog.window?.setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))

        val etUser = dialog.findViewById<EditText>(R.id.etAuthUser)
        val etPass = dialog.findViewById<EditText>(R.id.etAuthPassword)
        val btnConnect = dialog.findViewById<Button>(R.id.btnConnectAuth)
        val btnCancel = dialog.findViewById<Button>(R.id.btnCancelAuth)

        btnCancel.setOnClickListener { dialog.dismiss() }

        btnConnect.setOnClickListener {
            val userOrEmail = etUser.text.toString().trim()
            val pass = etPass.text.toString().trim()

            if (userOrEmail.isEmpty() || pass.isEmpty()) {
                Toast.makeText(this, "Completa usuario y contraseña", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            btnConnect.isEnabled = false
            btnConnect.text = "Conectando..."

            CoroutineScope(Dispatchers.IO).launch {
                val (ok, msg) = ApiClient.login(this@MainActivity, userOrEmail, pass)
                withContext(Dispatchers.Main) {
                    if (ok) {
                        Toast.makeText(this@MainActivity, "✓ $msg", Toast.LENGTH_SHORT).show()
                        updateButtonsStatus()
                        GastosWidgetProvider.notifyUpdate(this@MainActivity)
                        dialog.dismiss()
                    } else {
                        btnConnect.isEnabled = true
                        btnConnect.text = "Vincular"
                        Toast.makeText(this@MainActivity, "Error: $msg", Toast.LENGTH_LONG).show()
                    }
                }
            }
        }

        dialog.show()
    }
}
