package com.dario.gastos

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

object ApiClient {

    data class Budget(
        val id: Int,
        val nombre: String,
        val moneda: String,
        val montoRestante: Double,
        val disponible: Double,
        val porcentajeGastado: Double
    )

    data class Category(
        val id: Int,
        val nombre: String
    )

    data class WidgetSummary(
        val budget: Budget?,
        val message: String?
    )

    private suspend fun makeRequest(
        context: Context,
        path: String,
        method: String = "GET",
        bodyJson: JSONObject? = null,
        needsAuth: Boolean = true
    ): Pair<Int, String> = withContext(Dispatchers.IO) {
        val baseUrl = Prefs.getBaseUrl(context).trimEnd('/')
        val url = URL("$baseUrl$path")
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 10000
            readTimeout = 15000
            setRequestProperty("Accept", "application/json")
            if (bodyJson != null) {
                setRequestProperty("Content-Type", "application/json")
                doOutput = true
            }
            if (needsAuth) {
                val token = Prefs.getToken(context)
                if (!token.isNullOrEmpty()) {
                    setRequestProperty("Authorization", "Bearer $token")
                }
            }
        }

        try {
            if (bodyJson != null) {
                OutputStreamWriter(conn.outputStream, "UTF-8").use { writer ->
                    writer.write(bodyJson.toString())
                    writer.flush()
                }
            }

            val statusCode = conn.responseCode
            val stream = if (statusCode in 200..299) conn.inputStream else conn.errorStream
            val responseText = if (stream != null) {
                BufferedReader(InputStreamReader(stream, "UTF-8")).use { it.readText() }
            } else ""

            Pair(statusCode, responseText)
        } finally {
            conn.disconnect()
        }
    }

    suspend fun login(context: Context, userOrEmail: String, pass: String): Pair<Boolean, String> {
        val payload = JSONObject().apply {
            put("username", userOrEmail)
            put("password", pass)
            put("device_name", "Android App & Widget")
        }
        val (code, response) = makeRequest(context, "/api/auth/login/", "POST", payload, needsAuth = false)
        return try {
            val json = JSONObject(response)
            if (code == 200 && json.optBoolean("success")) {
                val token = json.getString("token")
                Prefs.setToken(context, token)
                Pair(true, "Vinculado correctamente")
            } else {
                Pair(false, json.optString("error", "Error al iniciar sesión ($code)"))
            }
        } catch (e: Exception) {
            Pair(false, "Error de conexión: ${e.localizedMessage}")
        }
    }

    suspend fun getWidgetSummary(context: Context, budgetId: Int? = null): WidgetSummary? {
        val path = if (budgetId != null && budgetId > 0) {
            "/api/widget/resumen/?presupuesto_id=$budgetId"
        } else {
            "/api/widget/resumen/"
        }
        val (code, response) = makeRequest(context, path, "GET")
        if (code != 200) return null
        return try {
            val json = JSONObject(response)
            if (!json.optBoolean("success")) return null
            val bJson = json.optJSONObject("presupuesto") ?: return WidgetSummary(null, json.optString("mensaje"))
            val budget = Budget(
                id = bJson.getInt("id"),
                nombre = bJson.getString("nombre"),
                moneda = bJson.getString("moneda"),
                montoRestante = bJson.getDouble("monto_restante"),
                disponible = bJson.getDouble("disponible"),
                porcentajeGastado = bJson.getDouble("porcentaje_gastado")
            )
            WidgetSummary(budget, null)
        } catch (e: Exception) {
            null
        }
    }

    suspend fun getBudgets(context: Context): List<Budget> {
        val (code, response) = makeRequest(context, "/api/presupuestos/", "GET")
        if (code != 200) return emptyList()
        return try {
            val json = JSONObject(response)
            val arr = json.optJSONArray("presupuestos") ?: JSONArray()
            val list = mutableListOf<Budget>()
            for (i in 0 until arr.length()) {
                val b = arr.getJSONObject(i)
                list.add(
                    Budget(
                        id = b.getInt("id"),
                        nombre = b.getString("nombre"),
                        moneda = b.getString("moneda"),
                        montoRestante = b.getDouble("monto_restante"),
                        disponible = b.getDouble("disponible"),
                        porcentajeGastado = b.getDouble("porcentaje_gastado")
                    )
                )
            }
            list
        } catch (e: Exception) {
            emptyList()
        }
    }

    suspend fun getCategories(context: Context): List<Category> {
        val (code, response) = makeRequest(context, "/api/categorias/", "GET")
        if (code != 200) return emptyList()
        return try {
            val json = JSONObject(response)
            val arr = json.optJSONArray("categorias") ?: JSONArray()
            val list = mutableListOf<Category>()
            for (i in 0 until arr.length()) {
                val c = arr.getJSONObject(i)
                list.add(Category(id = c.getInt("id"), nombre = c.getString("nombre")))
            }
            list
        } catch (e: Exception) {
            emptyList()
        }
    }

    suspend fun createExpense(
        context: Context,
        budgetId: Int,
        nombre: String,
        monto: Double,
        categoryId: Int? = null,
        desc: String = ""
    ): Pair<Boolean, String> {
        val payload = JSONObject().apply {
            put("presupuesto_id", budgetId)
            put("nombre", nombre)
            put("monto", monto)
            if (categoryId != null && categoryId > 0) put("categoria_id", categoryId)
            if (desc.isNotEmpty()) put("descripcion", desc)
        }
        val (code, response) = makeRequest(context, "/api/gastos/crear/", "POST", payload)
        return try {
            val json = JSONObject(response)
            if (code == 201 && json.optBoolean("success")) {
                Pair(true, json.optString("mensaje", "Gasto guardado"))
            } else {
                Pair(false, json.optString("error", "Error al guardar ($code)"))
            }
        } catch (e: Exception) {
            Pair(false, "Error: ${e.localizedMessage}")
        }
    }

    suspend fun createIncome(
        context: Context,
        budgetId: Int,
        nombre: String,
        monto: Double,
        desc: String = ""
    ): Pair<Boolean, String> {
        val payload = JSONObject().apply {
            put("presupuesto_id", budgetId)
            put("nombre", nombre)
            put("monto", monto)
            if (desc.isNotEmpty()) put("descripcion", desc)
        }
        val (code, response) = makeRequest(context, "/api/ingresos/crear/", "POST", payload)
        return try {
            val json = JSONObject(response)
            if (code == 201 && json.optBoolean("success")) {
                Pair(true, json.optString("mensaje", "Ingreso registrado"))
            } else {
                Pair(false, json.optString("error", "Error al guardar ($code)"))
            }
        } catch (e: Exception) {
            Pair(false, "Error: ${e.localizedMessage}")
        }
    }
}
