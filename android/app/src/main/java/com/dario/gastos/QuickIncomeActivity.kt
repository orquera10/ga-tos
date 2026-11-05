package com.dario.gastos

import android.content.Context
import android.graphics.Color
import android.os.Bundle
import android.view.inputmethod.InputMethodManager
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Spinner
import android.widget.TextView
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
    private lateinit var spTipoIngreso: Spinner
    private lateinit var etCuentaBancaria: EditText
    private lateinit var llCuentaChipsIngreso: LinearLayout
    private lateinit var btnSave: Button
    private lateinit var btnCancel: Button

    private var budgets: List<ApiClient.Budget> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.dialog_quick_income)

        val dm = resources.displayMetrics
        val dialogWidth = (dm.widthPixels * 0.92).toInt()
        window.setLayout(dialogWidth, android.view.ViewGroup.LayoutParams.WRAP_CONTENT)

        etMonto = findViewById(R.id.etMontoIngreso)
        etNombre = findViewById(R.id.etNombreIngreso)
        spPresupuesto = findViewById(R.id.spPresupuestoIngreso)
        spTipoIngreso = findViewById(R.id.spTipoIngreso)
        etCuentaBancaria = findViewById(R.id.etCuentaBancariaIngreso)
        llCuentaChipsIngreso = findViewById(R.id.llCuentaChipsIngreso)
        btnSave = findViewById(R.id.btnSaveIngreso)
        btnCancel = findViewById(R.id.btnCancelIngreso)

        val tipos = listOf("Transferencia", "Efectivo", "Sueldo")
        spTipoIngreso.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, tipos)

        btnCancel.setOnClickListener { finish() }

        val token = Prefs.getToken(this)
        if (token.isNullOrEmpty()) {
            Toast.makeText(this, "Primero abre la app y vincula tu cuenta", Toast.LENGTH_LONG).show()
            finish()
            return
        }

        etMonto.requestFocus()
        val imm = getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager
        imm?.showSoftInput(etMonto, InputMethodManager.SHOW_IMPLICIT)

        btnSave.setOnClickListener { saveIncome() }

        loadBudgetsAndMetadata()
    }

    private fun loadBudgetsAndMetadata() {
        CoroutineScope(Dispatchers.IO).launch {
            val bList = ApiClient.getBudgets(this@QuickIncomeActivity)
            val metadata = ApiClient.getMetadata(this@QuickIncomeActivity)
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

                // Renderizar chips de cuentas bancarias
                llCuentaChipsIngreso.removeAllViews()
                for (c in metadata.cuentas) {
                    val chip = TextView(this@QuickIncomeActivity).apply {
                        text = c
                        setTextColor(Color.parseColor("#3D8BFD"))
                        textSize = 13f
                        setBackgroundResource(R.drawable.chip_bank_bg)
                        setPadding(28, 14, 28, 14)
                        val lp = LinearLayout.LayoutParams(
                            LinearLayout.LayoutParams.WRAP_CONTENT,
                            LinearLayout.LayoutParams.WRAP_CONTENT
                        ).apply {
                            setMargins(0, 0, 16, 0)
                        }
                        layoutParams = lp
                        setOnClickListener {
                            etCuentaBancaria.setText(c)
                            etCuentaBancaria.setSelection(c.length)
                            spTipoIngreso.setSelection(0) // Transferencia
                        }
                    }
                    llCuentaChipsIngreso.addView(chip)
                }
            }
        }
    }

    private fun saveIncome() {
        val montoStr = etMonto.text.toString().trim().replace(',', '.')
        val monto = montoStr.toDoubleOrNull()
        if (monto == null || monto <= 0) {
            Toast.makeText(this, "Ingresa un monto válido", Toast.LENGTH_SHORT).show()
            return
        }

        val nombre = etNombre.text.toString().trim()
        if (nombre.isEmpty()) {
            Toast.makeText(this, "Ingresa un concepto", Toast.LENGTH_SHORT).show()
            return
        }

        val selectedBudgetIdx = spPresupuesto.selectedItemPosition
        if (selectedBudgetIdx < 0 || selectedBudgetIdx >= budgets.size) {
            Toast.makeText(this, "Selecciona un presupuesto", Toast.LENGTH_SHORT).show()
            return
        }
        val budget = budgets[selectedBudgetIdx]

        val tipoValue = when (spTipoIngreso.selectedItemPosition) {
            1 -> "efectivo"
            2 -> "sueldo"
            else -> "transferencia"
        }

        val cuenta = etCuentaBancaria.text.toString().trim()

        btnSave.isEnabled = false
        btnSave.text = "Guardando..."

        CoroutineScope(Dispatchers.IO).launch {
            val (ok, msg) = ApiClient.createIncome(
                context = this@QuickIncomeActivity,
                budgetId = budget.id,
                nombre = nombre,
                monto = monto,
                tipoIngreso = tipoValue,
                cuentaBancaria = cuenta
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
