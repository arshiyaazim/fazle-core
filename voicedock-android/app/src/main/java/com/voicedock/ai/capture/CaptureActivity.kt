package com.voicedock.ai.capture

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.voicedock.ai.data.CaptureRepository
import com.voicedock.ai.ui.VoiceDockTheme
import java.text.DateFormat
import java.util.Date

class CaptureActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val incoming = when (intent.action) {
            Intent.ACTION_PROCESS_TEXT -> intent.getCharSequenceExtra(Intent.EXTRA_PROCESS_TEXT)?.toString()
            Intent.ACTION_SEND -> intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()
            else -> null
        }.orEmpty()
        val source = callingPackage ?: intent.`package`
        setContent { VoiceDockTheme { CapturePreview(incoming, source) { title, text ->
            runCatching {
                CaptureRepository(this).save(title, text, source)
                if (intent.action == Intent.ACTION_PROCESS_TEXT && !intent.getBooleanExtra(Intent.EXTRA_PROCESS_TEXT_READONLY, true))
                    setResult(RESULT_OK, Intent().putExtra(Intent.EXTRA_PROCESS_TEXT, text))
                finish()
            }.fold(onSuccess = { null }, onFailure = { "Unable to save this capture. Your text is still shown above." })
        } } }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable private fun CapturePreview(initial: String, source: String?, save: (String, String) -> String?) {
    val activity = androidx.compose.ui.platform.LocalContext.current as? ComponentActivity
    var title by remember { mutableStateOf(initial.lineSequence().firstOrNull()?.take(60).orEmpty()) }
    var text by remember { mutableStateOf(initial) }
    var error by remember { mutableStateOf<String?>(null) }
    Scaffold(topBar = { TopAppBar(title = { Text("Capture preview") }) }) { padding ->
        Column(Modifier.padding(padding).padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            OutlinedTextField(title, { title = it }, Modifier.fillMaxWidth(), label = { Text("Title") })
            OutlinedTextField(text, { text = it }, Modifier.fillMaxWidth().weight(1f), label = { Text("Captured content") })
            Text("Source: ${source ?: "shared by user"}")
            Text("Captured: ${DateFormat.getDateTimeInstance().format(Date())}")
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(onClick = { activity?.finish() }) { Text("Discard") }
                Button(onClick = { error = save(title, text) }, enabled = text.isNotBlank()) { Text("Save locally") }
            }
        }
    }
}
