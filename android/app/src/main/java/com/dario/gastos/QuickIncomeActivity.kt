package com.dario.gastos

import android.content.Context
import android.graphics.Color
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.inputmethod.InputMethodManager
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
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
    private lateinit var btnSave: Button
    private lateinit var btnCancel: Button
    private lateinit var chipTransf: TextView
    private lateinit var chipEfectivo: TextView
    private lateinit var chipSueldo: TextView

    private var budgets: List<ApiClient.Budget> = emptyList()
    private var selectedTipoIngreso: String = "transferencia"
    private var tipoManuallyChosen: Boolean = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.dialog_quick_income)

        val dm = resources.displayMetrics
        val dialogWidth = (dm.widthPixels * 0.92).toInt()
        window.setLayout(dialogWidth, android.view.ViewGroup.LayoutParams.WRAP_CONTENT)

        etMonto = findViewById(R.id.etMontoIngreso)
        etNombre = findViewById(R.id.etNombreIngreso)
        spPresupuesto = findViewById(R.id.spPresupuestoIngreso)
        btnSave = findViewById(R.id.btnSaveIngreso)
        btnCancel = findViewById(R.id.btnCancelIngreso)
        chipTransf = findViewById(R.id.chipIngresoTransf)
        chipEfectivo = findViewById(R.id.chipIngresoEfectivo)
        chipSueldo = findViewById(R.id.chipIngresoSueldo)

        btnCancel.setOnClickListener { finish() }

        val token = Prefs.getToken(this)
        if (token.isNullOrEmpty()) {
            Toast.makeText(this, "Primero abre la app y vincula tu cuenta", Toast.LENGTH_LONG).show()
            finish()
            return
        }

        chipTransf.setOnClickListener {
            tipoManuallyChosen = true
            setTipoIngreso("transferencia")
        }
        chipEfectivo.setOnClickListener {
            tipoManuallyChosen = true
            setTipoIngreso("efectivo")
        }
        chipSueldo.setOnClickListener {
            tipoManuallyChosen = true
            setTipoIngreso("sueldo")
        }
        setTipoIngreso("transferencia")

        etNombre.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                if (tipoManuallyChosen) return
                val txt = (s?.toString() ?: "").lowercase()
                when {
                    txt.contains("sueldo") || txt.contains("salario") -> setTipoIngreso("sueldo")
                    txt.contains("efectivo") -> setTipoIngreso("efectivo")
                    txt.contains("transferencia") || txt.contains("transf") -> setTipoIngreso("transferencia")
                }
            }
        })

        // Auto focus monto y abrir teclado numérico
        etMonto.requestFocus()
        val imm = getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager
        imm?.showSoftInput(etMonto, InputMethodManager.SHOW_IMPLICIT)

        btnSave.setOnClickListener { saveIncome() }

        loadBudgets()
    }

    private fun setTipoIngreso(tipo: String) {
        selectedTipoIngreso = tipo
        val activeColor = Color.parseColor("#FFFFFF")
        val mutedColor = Color.parseColor("#A8AAB8")

        chipTransf.setBackgroundResource(if (tipo == "transferencia") R.drawable.chip_method_selected else R.drawable.chip_method_unselected)
        chipTransf.setTextColor(if (tipo == "transferencia") activeColor else mutedColor)

        chipEfectivo.setBackgroundResource(if (tipo == "efectivo") R.drawable.chip_method_selected else R.drawable.chip_method_unselected)
        chipEfectivo.setTextColor(if (tipo == "efectivo") activeColor else mutedColor)

        chipSueldo.setBackgroundResource(if (tipo == "sueldo") R.drawable.chip_method_selected else R.drawable.chip_method_unselected)
        chipSueldo.setTextColor(if (tipo == "sueldo") activeColor else mutedColor)
    }

    private fun loadBudgets() {
        CoroutineScope(Dispatchers.IO).launch {
            val bList = ApiClient.getBudgets(this@QuickIncomeActivity)
            withContext(Dispatchers.Main) {
                budgets = bList
                if (budgets.isNotEmpty()) {
                    val bNames = budgets.map { "${it.nombre} (${it.moneda})" }
                    val bAdapter = ArrayAdapter(this@QuickIncomeActivity, R.layout.spinner_item_dark, bNames).apply {
                        setDropDownViewResource(R.layout.spinner_dropdown_item_dark)
                    }
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

        val nombre = etNombre.text.toString().trim()

        btnSave.isEnabled = false
        btnSave.text = "Guardando..."

        CoroutineScope(Dispatchers.IO).launch {
            val (ok, msg) = ApiClient.createIncome(
                context = this@QuickIncomeActivity,
                budgetId = budget.id,
                nombre = nombre,
                monto = monto,
                tipoIngreso = selectedTipoIngreso
            )

            withContext(Dispatchers.Main) {
                if (ok) {
                    Toast.makeText(this@QuickIncomeActivity, "✓ $msg", Toast.LENGTH_SHORT).show()
                    GastosWidgetProvider.notifyUpdate(this@QuickIncomeActivity)
                    finish()
                } else {
                    btnSave.isEnabled = true
                    btnSave.text = "Guardar ingreso"
                    Toast.makeText(this@QuickIncomeActivity, "Error: $msg", Toast.LENGTH_LONG).show()
                }
            }
        }
    }
}
