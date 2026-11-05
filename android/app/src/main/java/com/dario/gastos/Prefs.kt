package com.dario.gastos

import android.content.Context
import android.content.SharedPreferences

object Prefs {
    private const val PREF_NAME = "gastos_prefs"
    private const val KEY_TOKEN = "api_token"
    private const val KEY_BASE_URL = "base_url"
    private const val KEY_LAST_BUDGET_ID = "last_budget_id"
    private const val KEY_LAST_BUDGET_NAME = "last_budget_name"
    private const val KEY_LAST_REMAINING = "last_remaining"
    private const val KEY_LAST_AVAILABLE = "last_available"
    private const val KEY_LAST_PERCENT = "last_percent"

    const val DEFAULT_BASE_URL = "https://gastos.dario10.pw"

    private fun get(context: Context): SharedPreferences {
        return context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
    }

    fun getToken(context: Context): String? {
        return get(context).getString(KEY_TOKEN, null)
    }

    fun setToken(context: Context, token: String?) {
        get(context).edit().putString(KEY_TOKEN, token).apply()
    }

    fun getBaseUrl(context: Context): String {
        return get(context).getString(KEY_BASE_URL, DEFAULT_BASE_URL) ?: DEFAULT_BASE_URL
    }

    fun saveWidgetData(context: Context, id: Int, name: String, remaining: Double, available: Double, percent: Double) {
        get(context).edit()
            .putInt(KEY_LAST_BUDGET_ID, id)
            .putString(KEY_LAST_BUDGET_NAME, name)
            .putFloat(KEY_LAST_REMAINING, remaining.toFloat())
            .putFloat(KEY_LAST_AVAILABLE, available.toFloat())
            .putFloat(KEY_LAST_PERCENT, percent.toFloat())
            .apply()
    }

    fun getLastBudgetName(context: Context): String {
        return get(context).getString(KEY_LAST_BUDGET_NAME, "Sin datos") ?: "Sin datos"
    }

    fun getLastRemaining(context: Context): Float {
        return get(context).getFloat(KEY_LAST_REMAINING, 0f)
    }

    fun getLastAvailable(context: Context): Float {
        return get(context).getFloat(KEY_LAST_AVAILABLE, 0f)
    }

    fun getLastPercent(context: Context): Int {
        return get(context).getFloat(KEY_LAST_PERCENT, 0f).toInt()
    }

    fun getLastBudgetId(context: Context): Int {
        return get(context).getInt(KEY_LAST_BUDGET_ID, -1)
    }
}
