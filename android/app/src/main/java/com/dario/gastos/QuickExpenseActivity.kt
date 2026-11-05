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

class QuickExpenseActivity : AppCompatActivity() {

    private lateinit var etMonto: EditText
    private lateinit var etNombre: EditText
    private lateinit var spPresupuesto: Spinner
    private lateinit var spCategoria: Spinner
    private lateinit var btnSave: Button
    private lateinit var btnCancel: Button

    private var budgets: List<ApiClient.Budget> = emptyList()
    private var categories: List<ApiClient.Category> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.dialog_quick_expense)

        val dm = resources.displayMetrics
        val dialogWidth = (dm.widthPixels * 0.92).toInt()
        window.setLayout(dialogWidth, android.view.ViewGroup.LayoutParams.WRAP_CONTENT)

        etMonto = findViewById(R.id.etMonto)
        etNombre = findViewById(R.id.etNombre)
        spPresupuesto = findViewById(R.id.spPresupuesto)
        spCategoria = findViewById(R.id.spCategoria)
        btnSave = findViewById(R.id.btnSave)
        btnCancel = findViewById(R.id.btnCancel)

        btnCancel.setOnClickListener { finish() }

        val token = Prefs.getToken(this)
        if (token.isNullOrEmpty()) {
            Toast.makeText(this, "Primero abre la app y vincula tu cuenta", Toast.LENGTH_LONG).show()
            finish()
            return
        }

        // Auto focus monto and show soft keyboard
        etMonto.requestFocus()
        val imm = getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager
        imm?.showSoftInput(etMonto, InputMethodManager.SHOW_IMPLICIT)

        btnSave.setOnClickListener { saveExpense() }

        loadSpinners()
    }

    private fun loadSpinners() {
        CoroutineScope(Dispatchers.IO).launch {
            val bList = ApiClient.getBudgets(this@QuickExpenseActivity)
            val cList = ApiClient.getCategories(this@QuickExpenseActivity)

            withContext(Dispatchers.Main) {
                budgets = bList
                categories = cList

                if (budgets.isNotEmpty()) {
                    val bNames = budgets.map { "${it.nombre} (${it.moneda})" }
                    val bAdapter = ArrayAdapter(this@QuickExpenseActivity, android.R.layout.simple_spinner_dropdown_item, bNames)
                    spPresupuesto.adapter = bAdapter

                    // Seleccionar el último presupuesto usado si existe
                    val lastBudgetId = Prefs.getLastBudgetId(this@QuickExpenseActivity)
                    val idx = budgets.indexOfFirst { it.id == lastBudgetId }
                    if (idx >= 0) {
                        spPresupuesto.setSelection(idx)
                    }
                }

                val cNames = mutableListOf("Sin categoría")
                cNames.addAll(categories.map { it.nombre })
                val cAdapter = ArrayAdapter(this@QuickExpenseActivity, android.R.layout.simple_spinner_dropdown_item, cNames)
                spCategoria.adapter = cAdapter
            }
        }
    }

    private fun saveExpense() {
        val montoStr = etMonto.text.toString().trim().replace(',', '.')
        val monto = montoStr.toDoubleOrNull()
        if (monto == null || monto <= 0) {
            Toast.makeText(this, "Ingresa un monto válido", Toast.LENGTH_SHORT).show()
            etMonto.requestFocus()
            return
        }

        val nombre = etNombre.text.toString().trim()
        if (nombre.isEmpty()) {
            Toast.makeText(this, "Ingresa en qué gastaste", Toast.LENGTH_SHORT).show()
            etNombre.requestFocus()
            return
        }

        val selectedBudgetIdx = spPresupuesto.selectedItemPosition
        if (selectedBudgetIdx < 0 || selectedBudgetIdx >= budgets.size) {
            Toast.makeText(this, "Selecciona un presupuesto", Toast.LENGTH_SHORT).show()
            return
        }
        val budget = budgets[selectedBudgetIdx]

        var categoryId: Int? = null
        val selectedCatIdx = spCategoria.selectedItemPosition
        if (selectedCatIdx > 0 && selectedCatIdx - 1 < categories.size) {
            categoryId = categories[selectedCatIdx - 1].id
        }

        btnSave.isEnabled = false
        btnSave.text = "Guardando..."

        CoroutineScope(Dispatchers.IO).launch {
            val (ok, msg) = ApiClient.createExpense(
                context = this@QuickExpenseActivity,
                budgetId = budget.id,
                nombre = nombre,
                monto = monto,
                categoryId = categoryId
            )

            withContext(Dispatchers.Main) {
                if (ok) {
                    Toast.makeText(this@QuickExpenseActivity, "✓ $msg", Toast.LENGTH_SHORT).show()
                    GastosWidgetProvider.notifyUpdate(this@QuickExpenseActivity)
                    finish()
                } else {
                    btnSave.isEnabled = true
                    btnSave.text = "Guardar"
                    Toast.makeText(this@QuickExpenseActivity, "Error: $msg", Toast.LENGTH_LONG).show()
                }
            }
        }
    }
}
