package com.dario.gastos

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.widget.RemoteViews
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.util.Locale

class GastosWidgetProvider : AppWidgetProvider() {

    override fun onUpdate(context: Context, appWidgetManager: AppWidgetManager, appWidgetIds: IntArray) {
        for (widgetId in appWidgetIds) {
            updateAppWidget(context, appWidgetManager, widgetId)
        }
        refreshDataFromApi(context)
    }

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        if (intent.action == ACTION_REFRESH_WIDGET || intent.action == AppWidgetManager.ACTION_APPWIDGET_UPDATE) {
            refreshDataFromApi(context)
        }
    }

    companion object {
        const val ACTION_REFRESH_WIDGET = "com.dario.gastos.ACTION_REFRESH_WIDGET"

        fun notifyUpdate(context: Context) {
            val intent = Intent(context, GastosWidgetProvider::class.java).apply {
                action = ACTION_REFRESH_WIDGET
            }
            context.sendBroadcast(intent)
        }

        fun updateAppWidget(context: Context, appWidgetManager: AppWidgetManager, appWidgetId: Int) {
            val views = RemoteViews(context.packageName, R.layout.widget_gastos)

            val token = Prefs.getToken(context)
            if (token.isNullOrEmpty()) {
                views.setTextViewText(R.id.widgetBudgetName, "Toca para vincular")
                views.setTextViewText(R.id.widgetTxtRestante, "Sin vincular")
                views.setTextColor(R.id.widgetTxtRestante, Color.parseColor("#FFB74D"))
                views.setTextViewText(R.id.widgetTxtDisponible, "-")
                views.setProgressBar(R.id.widgetProgressBar, 100, 0, false)
            } else {
                val budgetName = Prefs.getLastBudgetName(context)
                val remaining = Prefs.getLastRemaining(context)
                val available = Prefs.getLastAvailable(context)
                val percent = Prefs.getLastPercent(context)

                views.setTextViewText(R.id.widgetBudgetName, budgetName)
                views.setTextViewText(
                    R.id.widgetTxtRestante,
                    String.format(Locale.getDefault(), "$ %.2f", remaining)
                )
                val remainingColor = if (remaining < 0) Color.parseColor("#FF5252") else Color.parseColor("#00E676")
                views.setTextColor(R.id.widgetTxtRestante, remainingColor)

                views.setTextViewText(
                    R.id.widgetTxtDisponible,
                    String.format(Locale.getDefault(), "$ %.2f", available)
                )
                views.setProgressBar(R.id.widgetProgressBar, 100, percent.coerceIn(0, 100), false)
            }

            // Click on widget body -> Open MainActivity
            val mainIntent = Intent(context, MainActivity::class.java)
            val mainPending = PendingIntent.getActivity(
                context, 0, mainIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            views.setOnClickPendingIntent(R.id.widgetContainer, mainPending)

            // Click + Gasto -> Open QuickExpenseActivity
            val expenseIntent = Intent(context, QuickExpenseActivity::class.java)
            val expensePending = PendingIntent.getActivity(
                context, 1, expenseIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            views.setOnClickPendingIntent(R.id.widgetBtnAddExpense, expensePending)

            // Click + Ingreso -> Open QuickIncomeActivity
            val incomeIntent = Intent(context, QuickIncomeActivity::class.java)
            val incomePending = PendingIntent.getActivity(
                context, 2, incomeIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            views.setOnClickPendingIntent(R.id.widgetBtnAddIncome, incomePending)

            // Click ↻ -> Trigger refresh broadcast
            val refreshIntent = Intent(context, GastosWidgetProvider::class.java).apply {
                action = ACTION_REFRESH_WIDGET
            }
            val refreshPending = PendingIntent.getBroadcast(
                context, 3, refreshIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            views.setOnClickPendingIntent(R.id.widgetBtnRefresh, refreshPending)

            appWidgetManager.updateAppWidget(appWidgetId, views)
        }

        private fun refreshDataFromApi(context: Context) {
            val token = Prefs.getToken(context)
            if (token.isNullOrEmpty()) {
                val appWidgetManager = AppWidgetManager.getInstance(context)
                val thisWidget = ComponentName(context, GastosWidgetProvider::class.java)
                val allWidgetIds = appWidgetManager.getAppWidgetIds(thisWidget)
                for (id in allWidgetIds) {
                    updateAppWidget(context, appWidgetManager, id)
                }
                return
            }

            CoroutineScope(Dispatchers.IO).launch {
                val summary = ApiClient.getWidgetSummary(context)
                if (summary?.budget != null) {
                    val b = summary.budget
                    Prefs.saveWidgetData(
                        context,
                        id = b.id,
                        name = b.nombre,
                        remaining = b.montoRestante,
                        available = b.disponible,
                        percent = b.porcentajeGastado
                    )
                }

                launch(Dispatchers.Main) {
                    val appWidgetManager = AppWidgetManager.getInstance(context)
                    val thisWidget = ComponentName(context, GastosWidgetProvider::class.java)
                    val allWidgetIds = appWidgetManager.getAppWidgetIds(thisWidget)
                    for (id in allWidgetIds) {
                        updateAppWidget(context, appWidgetManager, id)
                    }
                }
            }
        }
    }
}
