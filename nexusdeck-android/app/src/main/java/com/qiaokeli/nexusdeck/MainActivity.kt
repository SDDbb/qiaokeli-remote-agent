package com.qiaokeli.nexusdeck

import android.app.Application
import android.content.Context
import android.content.SharedPreferences
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Article
import androidx.compose.material.icons.automirrored.filled.ListAlt
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material.icons.filled.Dashboard
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.OpenInBrowser
import androidx.compose.material.icons.filled.PermDeviceInformation
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.material.icons.filled.TravelExplore
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStream
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

data class NexusSettings(
    val baseUrl: String = "",
    val token: String = "",
    val mode: String = "confirm",
    val permissionMode: String = "workspace_write",
)

data class UiState(
    val settings: NexusSettings = NexusSettings(),
    val selectedTab: String = "Deck",
    val loading: Boolean = false,
    val lastCommandId: String = "",
    val health: String = "Not checked yet.",
    val result: String = "",
    val error: String = "",
    val conversation: List<ChatMessage> = emptyList(),
    val pendingConfirmation: PendingConfirmation? = null,
    val playbooks: List<PlaybookItem> = emptyList(),
)

data class ChatMessage(
    val role: String,
    val title: String,
    val body: String,
    val commandId: String = "",
)

data class PendingConfirmation(
    val type: String,
    val payload: JSONObject,
    val title: String,
    val detail: String,
)

data class PlaybookItem(
    val id: String,
    val name: String,
    val type: String,
    val path: String,
    val risk: String,
    val steps: Int,
)

data class AgentBackend(
    val label: String,
    val type: String,
    val mark: String,
    val description: String,
    val icon: ImageVector,
)

val AGENT_BACKENDS = listOf(
    AgentBackend("Codex", "codex", "CX", "GPT-5.5 coding agent on the desktop.", Icons.Filled.Terminal),
    AgentBackend("OpenClaw", "openclaw", "OC", "Local desktop workflow runner.", Icons.Filled.TravelExplore),
    AgentBackend("Claude Code", "cloud_code", "CL", "Claude Code CLI when installed.", Icons.Filled.SmartToy),
    AgentBackend("DeepSeek", "deepseek", "DS", "Fast low-cost DeepSeek draft route.", Icons.Filled.Search),
)

val AGENT_TYPES = AGENT_BACKENDS.map { it.type }.toSet()

data class PermissionMode(
    val label: String,
    val value: String,
    val summary: String,
)

val PERMISSION_MODES = listOf(
    PermissionMode("Default", "default", "Use each CLI's normal permission behavior."),
    PermissionMode("Read Only", "read_only", "Inspect only; no write sandbox."),
    PermissionMode("Workspace", "workspace_write", "Write inside the selected workspace."),
    PermissionMode("Full Access", "full_access", "No filesystem sandbox for Codex."),
    PermissionMode("Bypass", "bypass", "Skip Codex approvals and sandbox."),
)

fun normalizeBaseUrl(value: String): String {
    return value
        .trim()
        .replace('：', ':')
        .replace('／', '/')
        .replace('。', '.')
        .replace('．', '.')
        .trimEnd('/')
}

fun okBad(value: Boolean): String = if (value) "OK" else "Needs attention"

fun serviceState(value: Boolean): String = if (value) "running" else "stopped"

fun formatHealth(response: JSONObject): String {
    val result = response.optJSONObject("result") ?: return "Health check returned no data."
    val api = result.optJSONObject("api") ?: JSONObject()
    val host = result.optJSONObject("host") ?: JSONObject()
    val adb = result.optJSONObject("adb") ?: JSONObject()
    val adbResult = adb.optJSONObject("result") ?: JSONObject()
    val devices = adbResult.optJSONObject("devices")?.optJSONArray("devices") ?: JSONArray()
    val connectedDevice = (0 until devices.length())
        .mapNotNull { devices.optJSONObject(it) }
        .firstOrNull { it.optString("state") == "device" }

    val adbChecked = adb.has("ok") && !adb.isNull("ok")
    val lines = mutableListOf<String>()
    lines += "Overall: ${okBad(response.optBoolean("ok") && (!adbChecked || adb.optBoolean("ok")))}"
    lines += "API: online at ${api.optString("bind_host", "-")}:${api.optInt("port", 0)}"
    lines += "Computer: ${host.optString("host", "-")}"
    lines += "Tailscale: ${if (host.optBoolean("tailscale_online")) "online" else "offline"} ${host.optString("tailscale_ip", "")}".trim()
    lines += "remote-agent: ${serviceState(host.optBoolean("remote_agent_active"))}"
    lines += "Syncthing: ${serviceState(host.optBoolean("syncthing_active"))}"
    lines += "OpenClaw Gateway: ${serviceState(host.optBoolean("openclaw_gateway_active"))}"

    if (!adbChecked || adb.optString("status") == "not_checked") {
        lines += "ADB: not checked"
    } else if (connectedDevice != null) {
        val model = adbResult.optString("model", connectedDevice.optString("model", "-"))
        val android = adbResult.optString("android", "-")
        val serial = adbResult.optString("serial", connectedDevice.optString("serial", "-"))
        lines += "ADB: connected to $model, Android $android"
        lines += "ADB target: $serial"
        adbResult.optString("wm_size").takeIf { it.isNotBlank() }?.let { lines += "Screen: $it" }
        val wifi = adbResult.optString("wifi_status")
        Regex("Wifi is connected to \"([^\"]+)\"").find(wifi)?.groupValues?.getOrNull(1)?.let {
            lines += "Wi-Fi: $it"
        }
    } else {
        val error = adb.optString("error")
        lines += "ADB: no connected device${if (error.isNotBlank()) ", $error" else ""}"
    }

    return lines.joinToString("\n")
}

fun formatPlaybooks(response: JSONObject): String {
    val items = response.optJSONArray("result") ?: return "No playbooks found."
    if (items.length() == 0) {
        return "No playbooks found."
    }
    val lines = mutableListOf("Available playbooks: ${items.length()}")
    for (index in 0 until items.length()) {
        val item = items.optJSONObject(index) ?: continue
        val name = item.optString("name", item.optString("id", "unnamed"))
        val type = item.optString("type", "-")
        val risk = item.optString("risk", "-")
        val steps = item.optInt("steps", 0)
        lines += "${index + 1}. $name  type: $type  risk: $risk  steps: $steps"
    }
    return lines.joinToString("\n")
}

fun parsePlaybooks(response: JSONObject): List<PlaybookItem> {
    val items = response.optJSONArray("result") ?: return emptyList()
    return (0 until items.length()).mapNotNull { index ->
        val item = items.optJSONObject(index) ?: return@mapNotNull null
        PlaybookItem(
            id = item.optString("id", ""),
            name = item.optString("name", item.optString("id", "unnamed")),
            type = item.optString("type", "browser"),
            path = item.optString("path", ""),
            risk = item.optString("risk", "-"),
            steps = item.optInt("steps", 0),
        )
    }
}

fun shortError(error: String): String {
    val trimmed = error.trim()
    if (trimmed.contains("requires a newer version of Codex")) {
        return "Codex CLI is too old for the configured model. Upgrade Codex or change the model, then retry."
    }
    return trimmed.lines()
        .map { it.trim() }
        .firstOrNull { it.isNotBlank() && !it.startsWith("OpenAI Codex") && !it.startsWith("--------") }
        ?: trimmed.ifBlank { "Unknown error." }
}

fun formatApiError(error: String): String {
    val trimmed = error.trim()
    return when {
        trimmed.startsWith("HTTP 401") -> "Unauthorized. Check the Bearer token in Settings, then save and retry."
        trimmed.startsWith("HTTP 409") && trimmed.contains("needs_confirmation") ->
            "This command needs confirmation. Switch to Bypass for trusted testing, or add a confirmation flow."
        trimmed.startsWith("HTTP 403") -> "Blocked by the desktop policy. Check Work mode or Agent permission."
        trimmed.startsWith("HTTP ") -> shortError(trimmed.substringAfter(": ", trimmed))
        else -> shortError(trimmed)
    }
}

fun formatAndroidResult(result: JSONObject): String {
    val action = result.optString("action", "android")
    val payload = result.optJSONObject("result") ?: JSONObject()
    return when (action) {
        "current_app" -> {
            val pkg = payload.optString("package", "-")
            val activity = payload.optString("activity", "-")
            "Android current app\nPackage: $pkg\nActivity: $activity"
        }
        "open_url" -> "Android URL opened\nURL: ${payload.optString("url", "-")}"
        "screenshot" -> "Android screenshot captured\nFile: ${payload.optString("path", "-")}"
        "ui_dump" -> "Android UI dump captured\nFile: ${payload.optString("path", "-")}"
        "unlock" -> "Android unlock completed"
        "keyevent" -> "Android key event sent\nKey: ${payload.optString("key", "-")}"
        "status" -> {
            val model = payload.optString("model", "-")
            val android = payload.optString("android", "-")
            val serial = payload.optString("serial", "-")
            "Android status\nDevice: $model\nAndroid: $android\nADB target: $serial"
        }
        else -> "Android action completed\nAction: $action"
    }
}

fun formatCommandStatus(response: JSONObject): String {
    val envelope = response.optJSONObject("result") ?: response
    val status = envelope.optString("status", response.optString("status", "unknown"))
    val id = envelope.optString("id", response.optString("id", "-"))
    val command = envelope.optJSONObject("response") ?: response
    val type = command.optString("type", response.optString("type", "-")).replace("_", " ")

    if (status == "accepted") {
        return "Task accepted\nType: $type\nID: $id\nStatus: running"
    }
    if (status == "unknown") {
        return "Task not found\nID: $id"
    }

    val ok = command.optBoolean("ok", envelope.opt("ok") == true)
    val lines = mutableListOf<String>()
    lines += "Task ${if (ok) "completed" else "failed"}"
    lines += "Type: ${type.ifBlank { "-" }}"
    lines += "ID: $id"

    if (!ok) {
        lines += "Error: ${shortError(command.optString("error", envelope.optString("error", "")))}"
        return lines.joinToString("\n")
    }

    val result = command.optJSONObject("result") ?: envelope.optJSONObject("result") ?: JSONObject()
    val reply = result.optString("reply").trim()
    if (reply.isNotBlank()) {
        lines += ""
        lines += reply
        return lines.joinToString("\n")
    }

    if (type == "android") {
        lines += ""
        lines += formatAndroidResult(result)
        return lines.joinToString("\n")
    }

    result.optString("text").takeIf { it.isNotBlank() }?.let {
        lines += ""
        lines += it
    }
    if (lines.size <= 3) {
        lines += "No readable output was returned."
    }
    return lines.joinToString("\n")
}

fun backendLabel(type: String): String {
    return AGENT_BACKENDS.firstOrNull { it.type == type }?.label ?: type.replace("_", " ")
}

fun promptFromPayload(type: String, payload: JSONObject): String {
    val key = if (type == "openclaw") "message" else "prompt"
    return payload.optString(key, payload.optString("prompt", payload.optString("message", ""))).trim()
}

fun commandTitle(type: String, payload: JSONObject): String {
    if (type == "android") {
        return "Android / ${payload.optString("action", "command").replace("_", " ")}"
    }
    if (type in AGENT_TYPES) {
        return backendLabel(type)
    }
    return type.replace("_", " ")
}

fun needsConfirmation(exc: NexusHttpException): Boolean {
    if (exc.statusCode != 409) {
        return false
    }
    return exc.responseText.contains("needs_confirmation") || exc.responseText.contains("\"risk\"")
}

fun formatAgentMessage(response: JSONObject, backend: String): ChatMessage {
    val envelope = response.optJSONObject("result") ?: response
    val status = envelope.optString("status", response.optString("status", "unknown"))
    val id = envelope.optString("id", response.optString("id", ""))
    val command = envelope.optJSONObject("response") ?: response
    val label = backendLabel(backend)

    if (status == "accepted") {
        return ChatMessage("assistant", label, "Running on the desktop...", id)
    }
    if (status == "unknown") {
        return ChatMessage("assistant", label, "No matching task was found.", id)
    }

    val ok = command.optBoolean("ok", envelope.opt("ok") == true)
    if (!ok) {
        val error = command.optString("error", envelope.optString("error", ""))
        return ChatMessage("assistant", label, "Failed: ${shortError(error)}", id)
    }

    val result = command.optJSONObject("result") ?: envelope.optJSONObject("result") ?: JSONObject()
    val reply = result.optString("reply").trim()
    if (reply.isNotBlank()) {
        return ChatMessage("assistant", label, reply, id)
    }

    val text = result.optString("text").trim()
    if (text.isNotBlank()) {
        return ChatMessage("assistant", label, text, id)
    }

    return ChatMessage("assistant", label, "Completed. No readable reply was returned.", id)
}

fun formatUpload(response: JSONObject): String {
    val result = response.optJSONObject("result") ?: return "Upload completed."
    return "Upload completed\nFile: ${result.optString("filename", result.optString("artifact_id", "-"))}\nArtifact: ${result.optString("artifact_id", "-")}\nBytes: ${result.optLong("bytes", 0)}"
}

class SettingsStore(context: Context) {
    private val prefs: SharedPreferences = runCatching {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            "nexusdeck_secure",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }.getOrElse {
        context.getSharedPreferences("nexusdeck_settings", Context.MODE_PRIVATE)
    }

    fun load(): NexusSettings {
        return NexusSettings(
            baseUrl = normalizeBaseUrl(prefs.getString("base_url", "") ?: ""),
            token = prefs.getString("token", "") ?: "",
            mode = prefs.getString("mode", "confirm") ?: "confirm",
            permissionMode = prefs.getString("permission_mode", "workspace_write") ?: "workspace_write",
        )
    }

    fun save(settings: NexusSettings) {
        prefs.edit()
            .putString("base_url", normalizeBaseUrl(settings.baseUrl))
            .putString("token", settings.token.trim())
            .putString("mode", settings.mode)
            .putString("permission_mode", settings.permissionMode)
            .apply()
    }
}

class NexusDeckClient(private val settings: NexusSettings) {
    private fun endpoint(path: String): URL {
        val base = normalizeBaseUrl(settings.baseUrl)
        require(base.isNotBlank()) { "Set the NexusDeck API base URL first." }
        return URL(base + path)
    }

    suspend fun get(path: String): JSONObject = request("GET", path, null)

    suspend fun post(path: String, body: JSONObject): JSONObject = request("POST", path, body)

    suspend fun postFile(filename: String, size: Long, inputProvider: () -> InputStream): JSONObject = withContext(Dispatchers.IO) {
        val connection = (endpoint("/api/v1/files").openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 8_000
            readTimeout = 60_000
            doOutput = true
            setRequestProperty("Authorization", "Bearer ${settings.token.trim()}")
            setRequestProperty("Content-Type", "application/octet-stream")
            setRequestProperty("Accept", "application/json")
            setRequestProperty("X-NexusDeck-Filename", Uri.encode(filename))
            if (size > 0) {
                setFixedLengthStreamingMode(size)
            } else {
                setChunkedStreamingMode(1024 * 1024)
            }
        }
        inputProvider().use { input ->
            connection.outputStream.use { output ->
                input.copyTo(output, 1024 * 1024)
            }
        }
        val stream = if (connection.responseCode in 200..299) connection.inputStream else connection.errorStream
        val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
        if (connection.responseCode !in 200..299) {
            throw NexusHttpException(connection.responseCode, text)
        }
        JSONObject(text)
    }

    private suspend fun request(method: String, path: String, body: JSONObject?): JSONObject = withContext(Dispatchers.IO) {
        val connection = (endpoint(path).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 8_000
            readTimeout = 20_000
            setRequestProperty("Authorization", "Bearer ${settings.token.trim()}")
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("Accept", "application/json")
            if (body != null) {
                doOutput = true
            }
        }
        if (body != null) {
            OutputStreamWriter(connection.outputStream, Charsets.UTF_8).use { it.write(body.toString()) }
        }
        val stream = if (connection.responseCode in 200..299) connection.inputStream else connection.errorStream
        val text = stream?.let { BufferedReader(InputStreamReader(it, Charsets.UTF_8)).use { reader -> reader.readText() } }.orEmpty()
        if (connection.responseCode !in 200..299) {
            throw NexusHttpException(connection.responseCode, text)
        }
        JSONObject(text)
    }
}

class NexusHttpException(val statusCode: Int, val responseText: String) : IllegalStateException("HTTP $statusCode: $responseText")

class NexusDeckViewModel(application: Application) : AndroidViewModel(application) {
    private val store = SettingsStore(application)
    var state by mutableStateOf(UiState(settings = store.load()))
        private set

    fun select(tab: String) {
        state = state.copy(selectedTab = tab)
    }

    fun updateSettings(
        baseUrl: String = state.settings.baseUrl,
        token: String = state.settings.token,
        mode: String = state.settings.mode,
        permissionMode: String = state.settings.permissionMode,
    ) {
        state = state.copy(settings = NexusSettings(baseUrl, token, mode, permissionMode))
    }

    fun saveSettings() {
        store.save(state.settings)
        state = state.copy(result = "Settings saved.")
    }

    fun refreshHealth() = launchApi {
        val response = client().get("/api/v1/health")
        state = state.copy(health = formatHealth(response), result = "")
    }

    fun refreshDiagnostics() = launchApi {
        val response = client().get("/api/v1/diagnostics")
        state = state.copy(health = formatHealth(response), result = "Diagnostics completed.")
    }

    fun loadPlaybooks() = launchApi {
        val response = client().get("/api/v1/playbooks")
        val playbooks = parsePlaybooks(response)
        state = state.copy(playbooks = playbooks, result = if (playbooks.isEmpty()) "No playbooks found." else "")
    }

    fun checkCommand() = launchApi {
        val id = state.lastCommandId
        require(id.isNotBlank()) { "No command id yet." }
        val response = fetchCommandStatus(client(), id)
        state = state.copy(result = formatCommandStatus(response))
    }

    fun submit(type: String, payload: JSONObject = JSONObject(), confirmed: Boolean = false, appendUserMessage: Boolean = true) = launchApi {
        val api = client()
        val isAgent = type in AGENT_TYPES
        val prompt = promptFromPayload(type, payload)
        if (appendUserMessage && isAgent && prompt.isNotBlank()) {
            state = state.copy(
                result = "",
                conversation = state.conversation + ChatMessage("user", "You", prompt),
            )
        }
        val body = JSONObject()
            .put("type", type)
            .put("mode", state.settings.mode)
            .put("confirmed", confirmed)
            .put("client_request_id", "nexusdeck-${System.currentTimeMillis()}")
            .put("payload", payload)
        val response = try {
            api.post("/api/v1/commands", body)
        } catch (exc: NexusHttpException) {
            if (needsConfirmation(exc)) {
                val pending = PendingConfirmation(
                    type = type,
                    payload = JSONObject(payload.toString()),
                    title = commandTitle(type, payload),
                    detail = "This command is high risk in Confirm mode. Review it, then continue.",
                )
                val nextConversation = if (isAgent) {
                    state.conversation + ChatMessage("assistant", backendLabel(type), "Needs confirmation before the desktop runs it.")
                } else {
                    state.conversation
                }
                state = state.copy(
                    pendingConfirmation = pending,
                    conversation = nextConversation,
                    result = if (isAgent) "" else "Needs confirmation\n${pending.title}",
                    error = "",
                )
                return@launchApi
            }
            throw exc
        }
        val id = response.optString("id")
        state = state.copy(pendingConfirmation = null)
        if (isAgent) {
            state = state.copy(lastCommandId = id)
            upsertAssistantMessage(formatAgentMessage(response, type))
        } else {
            state = state.copy(lastCommandId = id, result = formatCommandStatus(response))
        }
        if (response.optString("status") == "accepted" && id.isNotBlank()) {
            val finalStatus = awaitCommand(api, id)
            if (isAgent) {
                upsertAssistantMessage(formatAgentMessage(finalStatus, type))
            } else {
                state = state.copy(result = formatCommandStatus(finalStatus))
            }
        }
    }

    fun confirmPending() {
        val pending = state.pendingConfirmation ?: return
        state = state.copy(pendingConfirmation = null, result = "")
        submit(pending.type, JSONObject(pending.payload.toString()), confirmed = true, appendUserMessage = false)
    }

    fun dismissPending() {
        state = state.copy(pendingConfirmation = null, result = "")
    }

    fun runPlaybook(playbook: PlaybookItem) {
        val payload = JSONObject().put("playbook_file", playbook.path)
        if (playbook.type == "android") {
            payload.put("action", "playbook")
        }
        submit(playbook.type, payload)
    }

    fun uploadUri(context: Context, uri: Uri) = launchApi {
        val resolver = context.contentResolver
        var size = -1L
        val name = resolver.query(uri, null, null, null, null)?.use { cursor ->
            val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
            if (cursor.moveToFirst()) {
                if (sizeIndex >= 0) size = cursor.getLong(sizeIndex)
                if (index >= 0) cursor.getString(index) else null
            } else {
                null
            }
        } ?: "nexusdeck-upload.bin"
        val response = client().postFile(name, size) {
            resolver.openInputStream(uri) ?: error("Cannot read selected file.")
        }
        state = state.copy(result = formatUpload(response))
    }

    private fun client(): NexusDeckClient = NexusDeckClient(state.settings)

    private suspend fun fetchCommandStatus(api: NexusDeckClient, id: String): JSONObject {
        return api.get("/api/v1/commands/$id")
    }

    private suspend fun awaitCommand(api: NexusDeckClient, id: String): JSONObject {
        var latest = fetchCommandStatus(api, id)
        repeat(30) {
            val status = latest.optJSONObject("result")?.optString("status").orEmpty()
            if (status !in setOf("accepted", "unknown")) {
                return latest
            }
            delay(1_000)
            latest = fetchCommandStatus(api, id)
        }
        return latest
    }

    private fun upsertAssistantMessage(message: ChatMessage) {
        val messages = state.conversation.toMutableList()
        val index = messages.indexOfLast { it.role == "assistant" && it.commandId == message.commandId && message.commandId.isNotBlank() }
        if (index >= 0) {
            messages[index] = message
        } else {
            messages += message
        }
        state = state.copy(conversation = messages)
    }

    private fun launchApi(block: suspend () -> Unit) {
        viewModelScope.launch {
            state = state.copy(loading = true, error = "")
            runCatching { block() }
                .onFailure { state = state.copy(error = formatApiError(it.message ?: it.toString())) }
            state = state.copy(loading = false)
        }
    }
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val vm: NexusDeckViewModel = viewModel(factory = object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T {
                    return NexusDeckViewModel(application) as T
                }
            })
            val baseUrl = intent.getStringExtra("nexus_base_url").orEmpty()
            val token = intent.getStringExtra("nexus_token").orEmpty()
            val refresh = intent.getBooleanExtra("nexus_refresh", false)
            LaunchedEffect(baseUrl, token, refresh) {
                if (baseUrl.isNotBlank() || token.isNotBlank()) {
                    vm.updateSettings(
                        baseUrl = baseUrl.ifBlank { vm.state.settings.baseUrl },
                        token = token.ifBlank { vm.state.settings.token },
                    )
                    vm.saveSettings()
                }
                if (refresh) {
                    vm.refreshHealth()
                }
            }
            NexusDeckApp(vm)
        }
    }
}

@Composable
fun NexusDeckApp(vm: NexusDeckViewModel) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Color(0xFF4FC3F7),
            onPrimary = Color(0xFF061018),
            secondary = Color(0xFF7BE495),
            surface = Color(0xFF0F141B),
        )
    ) {
        Surface(Modifier.fillMaxSize(), color = Color(0xFF0F141B)) {
            Scaffold(
                bottomBar = {
                    NavigationBar {
                        listOf("Deck", "Agent", "Phone", "Files", "Settings").forEach { tab ->
                            NavigationBarItem(
                                selected = vm.state.selectedTab == tab,
                                onClick = { vm.select(tab) },
                                label = { Text(tab) },
                                icon = { Icon(tabIcon(tab), contentDescription = tab) },
                            )
                        }
                    }
                }
            ) { padding ->
                Column(
                    Modifier
                        .padding(padding)
                        .fillMaxSize()
                        .background(Color(0xFF0F141B))
                        .verticalScroll(rememberScrollState())
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Header(vm.state)
                    when (vm.state.selectedTab) {
                        "Deck" -> DeckTab(vm)
                        "Agent" -> AgentTab(vm)
                        "Phone" -> PhoneTab(vm)
                        "Files" -> FilesTab(vm)
                        "Settings" -> SettingsTab(vm)
                    }
                    vm.state.pendingConfirmation?.let {
                        PendingConfirmationCard(it, onConfirm = vm::confirmPending, onCancel = vm::dismissPending)
                    }
                    StatusPanels(vm.state, vm.state.selectedTab)
                }
            }
        }
    }
}

fun tabIcon(tab: String): ImageVector = when (tab) {
    "Deck" -> Icons.Filled.Dashboard
    "Agent" -> Icons.Filled.SmartToy
    "Phone" -> Icons.Filled.PhoneAndroid
    "Files" -> Icons.Filled.Folder
    else -> Icons.Filled.Settings
}

@Composable
fun Header(state: UiState) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth(),
    ) {
        BrandBadge("ND")
        Spacer(Modifier.width(8.dp))
        Column(Modifier.weight(1f)) {
            Text("NexusDeck", fontSize = 18.sp, fontWeight = FontWeight.Bold, maxLines = 1)
            Text(
                "${state.selectedTab} / ${state.settings.mode.uppercase()} / ${state.settings.permissionMode.replace("_", " ").uppercase()}",
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                color = Color(0xFFB7C4D1),
                style = MaterialTheme.typography.labelSmall,
            )
        }
        if (state.loading) {
            Text("Working", color = Color(0xFF8BD3FF), style = MaterialTheme.typography.labelMedium)
        }
    }
    if (state.error.isNotBlank()) {
        Text(state.error, color = Color(0xFFFF9D9D), style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
fun DeckTab(vm: NexusDeckViewModel) {
    ActionCard("System Deck", "Run health checks and inspect capabilities.") {
        ActionRow {
            ActionButton("Health", Icons.Filled.Refresh, primary = true, onClick = vm::refreshHealth, modifier = Modifier.weight(1f))
            ActionButton("Diagnose", Icons.Filled.PermDeviceInformation, onClick = vm::refreshDiagnostics, modifier = Modifier.weight(1f))
        }
        ActionRow {
            ActionButton("Playbooks", Icons.AutoMirrored.Filled.ListAlt, onClick = vm::loadPlaybooks, modifier = Modifier.weight(1f))
            ActionButton("Last Task", Icons.Filled.History, onClick = vm::checkCommand, modifier = Modifier.weight(1f))
        }
    }
    if (vm.state.playbooks.isNotEmpty()) {
        PlaybooksCard(vm.state.playbooks, onRun = vm::runPlaybook)
    }
}

@Composable
fun AgentTab(vm: NexusDeckViewModel) {
    var prompt by remember { mutableStateOf("") }
    var backend by remember { mutableStateOf("codex") }
    val selectedBackend = AGENT_BACKENDS.firstOrNull { it.type == backend } ?: AGENT_BACKENDS.first()
    ActionCard("Agent Chat", "Send a message to a desktop AI backend.") {
        OutlinedTextField(
            value = prompt,
            onValueChange = { prompt = it },
            label = { Text("Message") },
            minLines = 2,
            modifier = Modifier.fillMaxWidth(),
        )
        AGENT_BACKENDS.chunked(2).forEach { row ->
            ActionRow {
                row.forEach { item ->
                    BackendButton(item = item, selected = backend == item.type, onClick = { backend = item.type }, modifier = Modifier.weight(1f))
                }
                if (row.size == 1) {
                    Spacer(Modifier.weight(1f))
                }
            }
        }
        Text(
            "${selectedBackend.label}: ${selectedBackend.description}",
            color = Color(0xFFB7C4D1),
            style = MaterialTheme.typography.bodySmall,
        )
        Button(
            onClick = {
                val payload = if (backend == "openclaw") {
                    JSONObject().put("message", prompt)
                } else {
                    JSONObject().put("prompt", prompt)
                }
                payload.put("permission_mode", vm.state.settings.permissionMode)
                vm.submit(backend, payload)
            },
            enabled = prompt.isNotBlank(),
            modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
        ) {
            Icon(Icons.Filled.SmartToy, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            ButtonText("Send")
        }
    }
}

@Composable
fun PhoneTab(vm: NexusDeckViewModel) {
    var url by remember { mutableStateOf("https://example.com") }
    ActionCard("Phone via ADB", "The desktop controls the phone through the existing authorized ADB link.") {
        ActionRow {
            ActionButton("Status", Icons.Filled.PermDeviceInformation, primary = true, onClick = { vm.submit("android", JSONObject().put("action", "status")) }, modifier = Modifier.weight(1f))
            ActionButton("Current App", Icons.Filled.PhoneAndroid, onClick = { vm.submit("android", JSONObject().put("action", "current_app")) }, modifier = Modifier.weight(1f))
        }
        ActionRow {
            ActionButton("Screenshot", Icons.Filled.Dashboard, onClick = { vm.submit("android", JSONObject().put("action", "screenshot")) }, modifier = Modifier.weight(1f))
            ActionButton("UI Dump", Icons.AutoMirrored.Filled.Article, onClick = { vm.submit("android", JSONObject().put("action", "ui_dump")) }, modifier = Modifier.weight(1f))
        }
        ActionRow {
            ActionButton("Wake", Icons.Filled.Refresh, onClick = { vm.submit("android", JSONObject().put("action", "keyevent").put("key", "KEYCODE_WAKEUP")) }, modifier = Modifier.weight(1f))
            ActionButton("Unlock", Icons.Filled.PhoneAndroid, onClick = { vm.submit("android", JSONObject().put("action", "unlock")) }, modifier = Modifier.weight(1f))
        }
        OutlinedTextField(value = url, onValueChange = { url = it }, label = { Text("URL") }, modifier = Modifier.fillMaxWidth())
        Button(onClick = { vm.submit("android", JSONObject().put("action", "open_url").put("url", url)) }, modifier = Modifier.fillMaxWidth().heightIn(min = 46.dp)) {
            Icon(Icons.Filled.OpenInBrowser, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            ButtonText("Open URL On Phone")
        }
    }
}

@Composable
fun FilesTab(vm: NexusDeckViewModel) {
    val context = LocalContext.current
    var path by remember { mutableStateOf("README.md") }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) vm.uploadUri(context, uri)
    }
    ActionCard("Files", "Read desktop files or upload a selected phone file to the desktop runtime area.") {
        OutlinedTextField(value = path, onValueChange = { path = it }, label = { Text("Computer path") }, modifier = Modifier.fillMaxWidth())
        ActionRow {
            ActionButton("Read File", Icons.AutoMirrored.Filled.Article, primary = true, onClick = { vm.submit("read_file", JSONObject().put("path", path)) }, modifier = Modifier.weight(1f))
            ActionButton("Upload", Icons.Filled.CloudUpload, onClick = { launcher.launch("*/*") }, modifier = Modifier.weight(1f))
        }
    }
}

@Composable
fun SettingsTab(vm: NexusDeckViewModel) {
    val settings = vm.state.settings
    ActionCard("Connection", "Use the pairing JSON from the desktop API script.") {
        OutlinedTextField(
            value = settings.baseUrl,
            onValueChange = { vm.updateSettings(baseUrl = it) },
            label = { Text("Base URL, e.g. http://100.x.x.x:8765") },
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = settings.token,
            onValueChange = { vm.updateSettings(token = it) },
            label = { Text("Bearer token") },
            visualTransformation = PasswordVisualTransformation(),
            modifier = Modifier.fillMaxWidth(),
        )
        Text("Work mode")
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("plan", "confirm", "whitelist", "bypass").forEach { mode ->
                if (settings.mode == mode) {
                    Button(onClick = { vm.updateSettings(mode = mode) }, modifier = Modifier.fillMaxWidth().heightIn(min = 42.dp)) { ButtonText(mode) }
                } else {
                    OutlinedButton(onClick = { vm.updateSettings(mode = mode) }, modifier = Modifier.fillMaxWidth().heightIn(min = 42.dp)) { ButtonText(mode) }
                }
            }
        }
        Text("Agent permission")
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            PERMISSION_MODES.forEach { permission ->
                val selected = settings.permissionMode == permission.value
                if (selected) {
                    Button(
                        onClick = { vm.updateSettings(permissionMode = permission.value) },
                        modifier = Modifier.fillMaxWidth().heightIn(min = 46.dp),
                    ) { ButtonText(permission.label) }
                } else {
                    OutlinedButton(
                        onClick = { vm.updateSettings(permissionMode = permission.value) },
                        modifier = Modifier.fillMaxWidth().heightIn(min = 46.dp),
                    ) { ButtonText(permission.label) }
                }
            }
        }
        Text(
            PERMISSION_MODES.firstOrNull { it.value == settings.permissionMode }?.summary.orEmpty(),
            color = Color(0xFFB7C4D1),
            style = MaterialTheme.typography.bodySmall,
        )
        Button(onClick = vm::saveSettings) { ButtonText("Save") }
    }
}

@Composable
fun StatusPanels(state: UiState, selectedTab: String) {
    if (selectedTab == "Deck" && state.health.isNotBlank()) {
        OutputCard("Health", state.health)
    }
    if (selectedTab == "Agent" && state.conversation.isNotEmpty()) {
        ConversationCard(state.conversation)
    } else if (state.result.isNotBlank()) {
        OutputCard("Result", state.result)
    }
}

@Composable
fun ActionCard(title: String, subtitle: String, content: @Composable ColumnScope.() -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Color(0xFF18212B)),
        shape = RoundedCornerShape(8.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text(subtitle, color = Color(0xFFB7C4D1), style = MaterialTheme.typography.bodySmall)
            content()
        }
    }
}

@Composable
fun PlaybooksCard(playbooks: List<PlaybookItem>, onRun: (PlaybookItem) -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Color(0xFF121A22)),
        shape = RoundedCornerShape(8.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Playbooks", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
            playbooks.forEach { playbook ->
                PlaybookRow(playbook, onRun)
            }
        }
    }
}

@Composable
fun PlaybookRow(playbook: PlaybookItem, onRun: (PlaybookItem) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Box(
            modifier = Modifier
                .size(34.dp)
                .background(if (playbook.type == "android") Color(0xFF28485A) else Color(0xFF34402A), CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                if (playbook.type == "android") Icons.Filled.PhoneAndroid else Icons.Filled.OpenInBrowser,
                contentDescription = null,
                modifier = Modifier.size(18.dp),
                tint = Color(0xFFEAF3FB),
            )
        }
        Column(Modifier.weight(1f)) {
            Text(playbook.name, fontWeight = FontWeight.Bold, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                "${playbook.type} / ${playbook.risk} / ${playbook.steps} steps",
                color = Color(0xFFB7C4D1),
                style = MaterialTheme.typography.labelSmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        OutlinedButton(onClick = { onRun(playbook) }, modifier = Modifier.heightIn(min = 42.dp)) {
            ButtonText("Run")
        }
    }
}

@Composable
fun PendingConfirmationCard(pending: PendingConfirmation, onConfirm: () -> Unit, onCancel: () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Color(0xFF2B2418)),
        shape = RoundedCornerShape(8.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Confirmation Required", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
            Text(pending.title, color = Color(0xFFFFD89A), style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Bold)
            Text(pending.detail, color = Color(0xFFE8D7BD), style = MaterialTheme.typography.bodySmall)
            ActionRow {
                Button(onClick = onConfirm, modifier = Modifier.weight(1f).heightIn(min = 46.dp)) {
                    ButtonText("Confirm")
                }
                OutlinedButton(onClick = onCancel, modifier = Modifier.weight(1f).heightIn(min = 46.dp)) {
                    ButtonText("Cancel")
                }
            }
        }
    }
}

@Composable
fun ButtonText(text: String) {
    Text(text, maxLines = 1, overflow = TextOverflow.Ellipsis)
}

@Composable
fun ActionRow(content: @Composable RowScope.() -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        content = content,
    )
}

@Composable
fun ActionButton(
    label: String,
    icon: ImageVector,
    primary: Boolean = false,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val content: @Composable () -> Unit = {
        Icon(icon, contentDescription = null, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(8.dp))
        ButtonText(label)
    }
    if (primary) {
        Button(onClick = onClick, modifier = modifier.heightIn(min = 48.dp), content = { content() })
    } else {
        OutlinedButton(onClick = onClick, modifier = modifier.heightIn(min = 48.dp), content = { content() })
    }
}

@Composable
fun BrandBadge(text: String) {
    Box(
        modifier = Modifier
            .size(30.dp)
            .background(Color(0xFF4FC3F7), CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, color = Color(0xFF061018), fontWeight = FontWeight.Black, fontSize = 11.sp)
    }
}

@Composable
fun BackendButton(item: AgentBackend, selected: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val content: @Composable () -> Unit = {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Icon(item.icon, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text(item.label, fontWeight = FontWeight.Bold, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
    if (selected) {
        Button(onClick = onClick, modifier = modifier.heightIn(min = 48.dp), content = { content() })
    } else {
        OutlinedButton(onClick = onClick, modifier = modifier.heightIn(min = 48.dp), content = { content() })
    }
}

@Composable
fun OutputCard(title: String, text: String) {
    Card(colors = CardDefaults.cardColors(containerColor = Color(0xFF121A22)), shape = RoundedCornerShape(8.dp), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(8.dp))
            Text(text, color = Color(0xFFDCE6EF), style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
fun ConversationCard(messages: List<ChatMessage>) {
    Card(colors = CardDefaults.cardColors(containerColor = Color(0xFF121A22)), shape = RoundedCornerShape(8.dp), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Conversation", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
            messages.takeLast(8).forEach { message ->
                ChatBubble(message)
            }
        }
    }
}

@Composable
fun ChatBubble(message: ChatMessage) {
    val isUser = message.role == "user"
    val background = if (isUser) Color(0xFF2B5C77) else Color(0xFF1C2630)
    val foreground = Color(0xFFEAF3FB)
    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = if (isUser) Alignment.End else Alignment.Start,
    ) {
        Text(
            message.title,
            color = Color(0xFFB7C4D1),
            style = MaterialTheme.typography.labelSmall,
            modifier = Modifier.fillMaxWidth(0.86f),
            textAlign = if (isUser) TextAlign.End else TextAlign.Start,
        )
        Card(
            colors = CardDefaults.cardColors(containerColor = background),
            shape = RoundedCornerShape(8.dp),
            modifier = Modifier.fillMaxWidth(0.86f),
        ) {
            Text(
                message.body,
                color = foreground,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(10.dp),
            )
        }
    }
}
