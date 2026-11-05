package com.dario.gastos

import android.content.Context
import android.os.Bundle
import android.view.inputmethod.InputMethodManager
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.Spinner
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class QuickIncomeActivity : AppCompatActivity() {

    private lateinit var etMonto: EditText
    private lateinit var etNombre: EditText
    private lateinit var spPresupuesto: Spinner
    private lateinit var btnSave: Button
    private lateinit var btnCancel: Button

    private var budgets: List<ApiClient.Budget> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.dialog_quick_income)

        val dm = resources.displayMetrics
        val dialogWidth = (dm.widthPixels * 0.90).toInt()
        window.setLayout(dialogWidth, android.view.ViewGroup.LayoutParams.WRAP_CONTENT)

        etMonto = findViewById(R.id.etMontoIngreso)
        etNombre = findViewById(R.id.etNombreIngreso)
        spPresupuesto = findViewById(R.id.spPresupuestoIngreso)
        btnSave = findViewById(R.id.btnSaveIngreso)
        btnCancel = findViewById(R.id.btnCancelIngreso)

        btnCancel.setOnClickListener { finish() }

        val token = Prefs.getToken(this)
        if (token.isNullOrEmpty()) {
            Toast.makeText(this, "Primero abre la app y vincula tu cuenta", Toast.LENGTH_LONG).show()
            finish()
            return
        }

        // Auto focus monto y abrir teclado numérico
        etMonto.requestFocus()
        val imm = getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager
        imm?.showSoftInput(etMonto, InputMethodManager.SHOW_IMPLICIT)

        btnSave.setOnClickListener { saveIncome() }

        loadBudgets()
    }

    private fun loadBudgets() {
        CoroutineScope(Dispatchers.IO).launch {
            val bList = ApiClient.getBudgets(this@QuickIncomeActivity)
            withContext(Dispatchers.Main) {
                budgets = bList
                if (budgets.isNotEmpty()) {
                    val bNames = budgets.map { "${it.nombre} (${it.moneda})" }
                    val bAdapter = ArrayAdapter(this@QuickIncomeActivity, android.R.layout.simple_spinner_dropdown_item, bNames)
                    spPresupuesto.adapter = bAdapter

                    val lastBudgetId = Prefs.getLastBudgetId(this@QuickIncomeActivity)
                    val idx = budgets.indexOfFirst { it.id == lastBudgetId }
                    if (idx >= 0) {
                        spPresupuesto.setSelection(idx)
                    }
                }
            }
        }
    }

    private fun saveIncome() {
        val montoStr = etMonto.text.toString().trim().replace(',', '.')
        val monto = montoStr.toDoubleOrNull()
        if (monto == null || monto <= 0) {
            Toast.makeText(this, "Ingresa un monto válido", Toast.LENGTH_SHORT).show()
            etMonto.requestFocus()
            return
        }

        val selectedBudgetIdx = spPresupuesto.selectedItemPosition
        if (selectedBudgetIdx < 0 || selectedBudgetIdx >= budgets.size) {
            Toast.makeText(this, "Selecciona un presupuesto", Toast.LENGTH_SHORT).show()
            return
        }
        val budget = budgets[selectedBudgetIdx]
        Prefs.saveLastBudgetId(this, budget.id)

        // Nombre opcional: si está vacío, el servidor asignará "⚡ Ingreso rápido 01" automáticamente
        val nombre = etNombre.text.toString().trim()

        btnSave.isEnabled = false
        btnSave.text = "Guardando..."

        CoroutineScope(Dispatchers.IO).launch {
            val (ok, msg) = ApiClient.createIncome(
                context = this@QuickIncomeActivity,
                budgetId = budget.id,
                nombre = nombre,
                monto = monto
            )

            withContext(Dispatchers.Main) {
                if (ok) {
                    Toast.makeText(this@QuickIncomeActivity, "✓ $msg", Toast.LENGTH_SHORT).show()
                    GastosWidgetProvider.notifyUpdate(this@QuickIncomeActivity)
                    finish()
                } else {
                    btnSave.isEnabled = true
                    btnSave.text = "Guardar"
                    Toast.makeText(this@QuickIncomeActivity, "Error: $msg", Toast.LENGTH_LONG).show()
                }
            }
        }
    }
}
