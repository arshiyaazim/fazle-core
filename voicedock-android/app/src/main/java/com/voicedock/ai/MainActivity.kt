package com.voicedock.ai

import android.Manifest
import android.content.*
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.voicedock.ai.data.CaptureRepository
import com.voicedock.ai.data.DraftRepository
import com.voicedock.ai.overlay.OverlayService
import com.voicedock.ai.text.FaithfulFormatter
import com.voicedock.ai.ui.VoiceDockTheme

class MainActivity : ComponentActivity() {
    private var overlayGranted by mutableStateOf(false)
    private var microphoneGranted by mutableStateOf(false)
    private val microphoneRequest = registerForActivityResult(ActivityResultContracts.RequestPermission()) { microphoneGranted = it }
    private val notificationsRequest = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        refreshPermissions()
        setContent { VoiceDockTheme { VoiceDockApp(
            overlayGranted = overlayGranted,
            microphoneGranted = microphoneGranted,
            requestMicrophone = { microphoneRequest.launch(Manifest.permission.RECORD_AUDIO) },
            requestOverlay = { startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))) },
            startOverlay = ::startOverlay,
            initialDestination = intent.getStringExtra("destination") ?: "home",
        ) } }
    }
    override fun onResume() { super.onResume(); refreshPermissions() }
    private fun refreshPermissions() {
        overlayGranted = Settings.canDrawOverlays(this)
        microphoneGranted = ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
    }
    private fun startOverlay() {
        refreshPermissions()
        if (!microphoneGranted) { microphoneRequest.launch(Manifest.permission.RECORD_AUDIO); return }
        if (!overlayGranted) { startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))); return }
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            notificationsRequest.launch(Manifest.permission.POST_NOTIFICATIONS)
        ContextCompat.startForegroundService(this, Intent(this, OverlayService::class.java))
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable private fun VoiceDockApp(
    overlayGranted: Boolean, microphoneGranted: Boolean, requestMicrophone: () -> Unit,
    requestOverlay: () -> Unit, startOverlay: () -> Unit, initialDestination: String,
) {
    var screen by remember { mutableStateOf(initialDestination) }
    Scaffold(topBar = { TopAppBar(title = { Text(if (screen == "home") "VoiceDock AI" else screen.replaceFirstChar(Char::uppercase)) }, navigationIcon = {
        if (screen != "home") IconButton(onClick = { screen = "home" }) { Icon(Icons.Default.ArrowBack, "Back") }
    }) }) { padding ->
        Box(Modifier.padding(padding).fillMaxSize()) {
            when (screen) {
                "write" -> EditorScreen()
                "knowledge", "capture" -> KnowledgeScreen()
                "privacy" -> PrivacyScreen(overlayGranted, microphoneGranted, requestMicrophone, requestOverlay)
                else -> Dashboard(overlayGranted, microphoneGranted, startOverlay, { screen = it })
            }
        }
    }
}

@Composable private fun Dashboard(overlay: Boolean, microphone: Boolean, startOverlay: () -> Unit, navigate: (String) -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("Speak, refine, and carry your words anywhere.", style = MaterialTheme.typography.headlineSmall)
        Card { Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Floating assistant", style = MaterialTheme.typography.titleLarge)
            Text(if (overlay && microphone) "Permissions ready" else "Setup required: ${if (!microphone) "microphone " else ""}${if (!overlay) "overlay" else ""}")
            Button(onClick = startOverlay, modifier = Modifier.fillMaxWidth()) { Icon(Icons.Default.Mic, null); Spacer(Modifier.width(8.dp)); Text("Open floating assistant") }
            Text("Android recognition may pause between segments. VoiceDock preserves the draft and reconnects; it does not claim unlimited provider recording.", style = MaterialTheme.typography.bodySmall)
        } }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            FeatureButton("Write", Icons.Default.Edit, Modifier.weight(1f)) { navigate("write") }
            FeatureButton("Knowledge", Icons.Default.Folder, Modifier.weight(1f)) { navigate("knowledge") }
        }
        FeatureButton("Privacy & permissions", Icons.Default.Security, Modifier.fillMaxWidth()) { navigate("privacy") }
        Text("Coming in later phases", style = MaterialTheme.typography.titleMedium)
        Text("AI providers, cloud accounts, IME keyboard, accessibility insertion, Room search, and document OCR are not enabled in this MVP.")
    }
}

@Composable private fun FeatureButton(label: String, icon: androidx.compose.ui.graphics.vector.ImageVector, modifier: Modifier, click: () -> Unit) {
    OutlinedButton(onClick = click, modifier = modifier.height(64.dp)) { Icon(icon, null); Spacer(Modifier.width(8.dp)); Text(label) }
}

@Composable private fun EditorScreen() {
    val context = LocalContext.current
    var text by remember { mutableStateOf(DraftRepository(context).read()) }
    Column(Modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Review before inserting", style = MaterialTheme.typography.titleLarge)
        OutlinedTextField(text, { text = it; DraftRepository(context).save(it) }, Modifier.fillMaxWidth().weight(1f), label = { Text("Dictation draft") })
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { text = FaithfulFormatter.format(text); DraftRepository(context).save(text) }) { Text("Faithful cleanup") }
            OutlinedButton(onClick = { copy(context, text) }) { Text("Copy") }
            OutlinedButton(onClick = { share(context, text) }) { Text("Share") }
        }
    }
}

@Composable private fun KnowledgeScreen() {
    val context = LocalContext.current
    var records by remember { mutableStateOf(CaptureRepository(context).list()) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Local captures", style = MaterialTheme.typography.titleLarge)
        Text("Share selected text to VoiceDock AI from another app. Each save creates a separate local record.")
        if (records.isEmpty()) Text("No captures yet.", style = MaterialTheme.typography.bodyLarge)
        records.forEach { item -> Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp)) {
            Text(item.title, style = MaterialTheme.typography.titleMedium); Text(item.text, maxLines = 4)
            Text(item.source ?: "Shared content", style = MaterialTheme.typography.labelSmall)
            TextButton(onClick = { CaptureRepository(context).delete(item.id); records = CaptureRepository(context).list() }) { Text("Delete local copy") }
        } } }
    }
}

@Composable private fun PrivacyScreen(overlay: Boolean, microphone: Boolean, requestMicrophone: () -> Unit, requestOverlay: () -> Unit) {
    Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("VoiceDock only starts recognition after you tap Voice. Captured drafts and shared text stay on this device in this MVP. No cloud AI or account connector is active.")
        PermissionCard("Microphone", microphone, "Required only while you actively dictate.", requestMicrophone)
        PermissionCard("Display over other apps", overlay, "Shows the movable assistant. It cannot read arbitrary screen content.", requestOverlay)
    }
}
@Composable private fun PermissionCard(title: String, granted: Boolean, detail: String, action: () -> Unit) = Card { Column(Modifier.padding(16.dp)) {
    Text("$title — ${if (granted) "Granted" else "Not granted"}", style = MaterialTheme.typography.titleMedium); Text(detail)
    if (!granted) TextButton(onClick = action) { Text("Review permission") }
} }
private fun copy(context: Context, text: String) { (context.getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager).setPrimaryClip(android.content.ClipData.newPlainText("VoiceDock draft", text)) }
private fun share(context: Context, text: String) { context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text), "Share VoiceDock draft")) }
