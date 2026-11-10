package com.dario.gastos

import android.os.Bundle
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.Spinner
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale

class SelectBudgetActivity : AppCompatActivity() {

    private lateinit var spBudgetList: Spinner
    private lateinit var btnApply: Button
    private lateinit var btnCancel: Button
    private var budgets: List<ApiClient.Budget> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.dialog_select_budget)

        val dm = resources.displayMetrics
        val dialogWidth = (dm.widthPixels * 0.92).toInt()
        window.setLayout(dialogWidth, android.view.ViewGroup.LayoutParams.WRAP_CONTENT)

        spBudgetList = findViewById(R.id.spBudgetList)
        btnApply = findViewById(R.id.btnApplySelect)
        btnCancel = findViewById(R.id.btnCancelSelect)

        btnCancel.setOnClickListener { finish() }

        val token = Prefs.getToken(this)
        if (token.isNullOrEmpty()) {
            Toast.makeText(this, "Primero vincula tu cuenta", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        btnApply.setOnClickListener { applySelection() }

        loadBudgets()
    }

    private fun loadBudgets() {
        btnApply.isEnabled = false
        CoroutineScope(Dispatchers.IO).launch {
            val list = ApiClient.getBudgets(this@SelectBudgetActivity)
            withContext(Dispatchers.Main) {
                budgets = list
                if (budgets.isNotEmpty()) {
                    val names = budgets.map {
                        val restanteFormatted = String.format(Locale.getDefault(), "%,.0f", it.montoRestante)
                        "${it.nombre} · $ $restanteFormatted"
                    }
                    val adapter = ArrayAdapter(this@SelectBudgetActivity, R.layout.spinner_item_dark, names).apply {
                        setDropDownViewResource(R.layout.spinner_dropdown_item_dark)
                    }
                    spBudgetList.adapter = adapter

                    val currentSelectedId = Prefs.getSelectedBudgetId(this@SelectBudgetActivity)
                    val idx = budgets.indexOfFirst { it.id == currentSelectedId }
                    if (idx >= 0) {
                        spBudgetList.setSelection(idx)
                    }
                    btnApply.isEnabled = true
                } else {
                    Toast.makeText(this@SelectBudgetActivity, "No se encontraron presupuestos", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    private fun applySelection() {
        val idx = spBudgetList.selectedItemPosition
        if (idx < 0 || idx >= budgets.size) {
            Toast.makeText(this, "Selecciona un presupuesto", Toast.LENGTH_SHORT).show()
            return
        }

        val budget = budgets[idx]
        Prefs.setSelectedBudgetId(this, budget.id)
        Prefs.saveWidgetData(
            this,
            id = budget.id,
            name = budget.nombre,
            remaining = budget.montoRestante,
            available = budget.disponible,
            percent = budget.porcentajeGastado
        )

        GastosWidgetProvider.notifyUpdate(this)
        Toast.makeText(this, "✓ Widget configurado con: ${budget.nombre}", Toast.LENGTH_SHORT).show()
        finish()
    }
}
