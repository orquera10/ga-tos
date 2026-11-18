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

class QuickExpenseActivity : AppCompatActivity() {

    private lateinit var etMonto: EditText
    private lateinit var etNombre: EditText
    private lateinit var spPresupuesto: Spinner
    private lateinit var btnSave: Button
    private lateinit var btnCancel: Button
    private lateinit var chipEfectivo: TextView
    private lateinit var chipTransferencia: TextView
    private lateinit var chipTarjeta: TextView

    private var budgets: List<ApiClient.Budget> = emptyList()
    private var selectedMetodo: String = "efectivo"
    private var metodoManuallyChosen: Boolean = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.dialog_quick_expense)

        val dm = resources.displayMetrics
        val dialogWidth = (dm.widthPixels * 0.92).toInt()
        window.setLayout(dialogWidth, android.view.ViewGroup.LayoutParams.WRAP_CONTENT)

        etMonto = findViewById(R.id.etMonto)
        etNombre = findViewById(R.id.etNombre)
        spPresupuesto = findViewById(R.id.spPresupuesto)
        btnSave = findViewById(R.id.btnSave)
        btnCancel = findViewById(R.id.btnCancel)
        chipEfectivo = findViewById(R.id.chipMetodoEfectivo)
        chipTransferencia = findViewById(R.id.chipMetodoTransferencia)
        chipTarjeta = findViewById(R.id.chipMetodoTarjeta)

        btnCancel.setOnClickListener { finish() }

        val token = Prefs.getToken(this)
        if (token.isNullOrEmpty()) {
            Toast.makeText(this, "Primero abre la app y vincula tu cuenta", Toast.LENGTH_LONG).show()
            finish()
            return
        }

        chipEfectivo.setOnClickListener {
            metodoManuallyChosen = true
            setMetodo("efectivo")
        }
        chipTransferencia.setOnClickListener {
            metodoManuallyChosen = true
            setMetodo("transferencia")
        }
        chipTarjeta.setOnClickListener {
            metodoManuallyChosen = true
            setMetodo("tarjeta")
        }
        setMetodo("efectivo")

        etNombre.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                if (metodoManuallyChosen) return
                val txt = (s?.toString() ?: "").lowercase()
                when {
                    txt.contains("tarjeta") || txt.contains("visa") || txt.contains("master") -> setMetodo("tarjeta")
                    txt.contains("transferencia") || txt.contains("transf") || txt.contains("mp") || txt.contains("mercado pago") -> setMetodo("transferencia")
                    txt.contains("efectivo") -> setMetodo("efectivo")
                }
            }
        })

        // Auto focus monto y abrir teclado numérico directamente
        etMonto.requestFocus()
        val imm = getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager
        imm?.showSoftInput(etMonto, InputMethodManager.SHOW_IMPLICIT)

        btnSave.setOnClickListener { saveExpense() }

        loadBudgets()
    }

    private fun setMetodo(metodo: String) {
        selectedMetodo = metodo
        val activeColor = Color.parseColor("#FFFFFF")
        val mutedColor = Color.parseColor("#C2C4D4")

        chipEfectivo.setBackgroundResource(if (metodo == "efectivo") R.drawable.widget_pill_purple else R.drawable.chip_tag_bg)
        chipEfectivo.setTextColor(if (metodo == "efectivo") activeColor else mutedColor)

        chipTransferencia.setBackgroundResource(if (metodo == "transferencia") R.drawable.widget_pill_purple else R.drawable.chip_tag_bg)
        chipTransferencia.setTextColor(if (metodo == "transferencia") activeColor else mutedColor)

        chipTarjeta.setBackgroundResource(if (metodo == "tarjeta") R.drawable.widget_pill_purple else R.drawable.chip_tag_bg)
        chipTarjeta.setTextColor(if (metodo == "tarjeta") activeColor else mutedColor)
    }

    private fun loadBudgets() {
        CoroutineScope(Dispatchers.IO).launch {
            val bList = ApiClient.getBudgets(this@QuickExpenseActivity)
            withContext(Dispatchers.Main) {
                budgets = bList
                if (budgets.isNotEmpty()) {
                    val bNames = budgets.map { "${it.nombre} (${it.moneda})" }
                    val bAdapter = ArrayAdapter(this@QuickExpenseActivity, R.layout.spinner_item_dark, bNames).apply {
                        setDropDownViewResource(R.layout.spinner_dropdown_item_dark)
                    }
                    spPresupuesto.adapter = bAdapter

                    val lastBudgetId = Prefs.getLastBudgetId(this@QuickExpenseActivity)
                    val idx = budgets.indexOfFirst { it.id == lastBudgetId }
                    if (idx >= 0) {
                        spPresupuesto.setSelection(idx)
                    }
                }
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
            val (ok, msg) = ApiClient.createExpense(
                context = this@QuickExpenseActivity,
                budgetId = budget.id,
                nombre = nombre,
                monto = monto,
                metodoPago = selectedMetodo
            )

            withContext(Dispatchers.Main) {
                if (ok) {
                    Toast.makeText(this@QuickExpenseActivity, "✓ $msg", Toast.LENGTH_SHORT).show()
                    GastosWidgetProvider.notifyUpdate(this@QuickExpenseActivity)
                    finish()
                } else {
                    btnSave.isEnabled = true
                    btnSave.text = "Guardar gasto"
                    Toast.makeText(this@QuickExpenseActivity, "Error: $msg", Toast.LENGTH_LONG).show()
                }
            }
        }
    }
}
