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
                views.setTextViewText(R.id.widgetBudgetName, "Sin vincular")
                views.setTextViewText(R.id.widgetTxtRestante, "Tocá para entrar")
                views.setTextColor(R.id.widgetTxtRestante, Color.parseColor("#F0BD62"))
            } else {
                val budgetName = Prefs.getLastBudgetName(context)
                val remaining = Prefs.getLastRemaining(context)

                views.setTextViewText(R.id.widgetBudgetName, "$budgetName ▾")
                views.setTextViewText(
                    R.id.widgetTxtRestante,
                    String.format(Locale.getDefault(), "$ %,.0f", remaining)
                )
                val remainingColor = if (remaining < 0) Color.parseColor("#FF8780") else Color.parseColor("#FFFFFF")
                views.setTextColor(R.id.widgetTxtRestante, remainingColor)
            }

            // Click en el botón "Ver ↗" o cuerpo del widget -> Abrir MainActivity en el presupuesto seleccionado
            val currentBudgetId = Prefs.getLastBudgetId(context)
            val mainIntent = Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
                if (currentBudgetId > 0) {
                    putExtra(MainActivity.EXTRA_BUDGET_ID, currentBudgetId)
                }
            }
            val mainPending = PendingIntent.getActivity(
                context, 0, mainIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            views.setOnClickPendingIntent(R.id.widgetContainer, mainPending)
            views.setOnClickPendingIntent(R.id.widgetBtnOpenBudget, mainPending)

            // Click en el selector de presupuesto o saldo -> Abrir diálogo para cambiar de presupuesto
            val selectIntent = Intent(context, SelectBudgetActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            val selectPending = PendingIntent.getActivity(
                context, 4, selectIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            views.setOnClickPendingIntent(R.id.widgetBudgetInfo, selectPending)
            views.setOnClickPendingIntent(R.id.widgetBudgetName, selectPending)
            views.setOnClickPendingIntent(R.id.widgetTxtRestante, selectPending)

            // Click + Gasto -> Abrir QuickExpenseActivity independiente
            val expenseIntent = Intent(context, QuickExpenseActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            val expensePending = PendingIntent.getActivity(
                context, 1, expenseIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            views.setOnClickPendingIntent(R.id.widgetBtnAddExpense, expensePending)

            // Click + Ingreso -> Abrir QuickIncomeActivity independiente
            val incomeIntent = Intent(context, QuickIncomeActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            val incomePending = PendingIntent.getActivity(
                context, 2, incomeIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            views.setOnClickPendingIntent(R.id.widgetBtnAddIncome, incomePending)

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
                val selectedId = Prefs.getSelectedBudgetId(context)
                val budgetIdParam = if (selectedId > 0) selectedId else null
                val summary = ApiClient.getWidgetSummary(context, budgetIdParam)

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
