package com.voicedock.ai.overlay

import android.Manifest
import android.app.*
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.PixelFormat
import android.os.Build
import android.os.IBinder
import android.provider.Settings
import android.text.InputType
import android.view.*
import android.view.accessibility.AccessibilityEvent
import android.widget.*
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.voicedock.ai.MainActivity
import com.voicedock.ai.R
import com.voicedock.ai.data.CaptureRepository
import com.voicedock.ai.data.DraftRepository
import com.voicedock.ai.voice.*
import java.text.DateFormat
import java.util.Date
import kotlin.math.abs

/**
 * Permission-aware floating operational workspace. On phones the panel is a bottom sheet;
 * on larger displays it is a compact draggable window. It never reads the underlying app.
 */
class OverlayService : Service() {
    private lateinit var windows: WindowManager
    private lateinit var params: WindowManager.LayoutParams
    private var view: View? = null
    private var panelExpanded = false
    private var localCaptureCount = 0
    private var pendingComposerText = ""
    private var activeTool = AssistantTool.CAPTURE
    private var latestState = DictationState()
    private var micStatus: TextView? = null
    private var aiStatus: TextView? = null
    private var dataStatus: TextView? = null
    private var detailStatus: TextView? = null
    private var conversation: TextView? = null
    private var composer: EditText? = null
    private var toolContent: LinearLayout? = null
    private var tabButtons = emptyMap<AssistantTool, Button>()
    private lateinit var controller: DictationController

    override fun onCreate() {
        super.onCreate()
        createChannel()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED ||
            !Settings.canDrawOverlays(this)
        ) {
            stopSelf()
            return
        }
        try {
            startForeground(NOTIFICATION_ID, notification())
        } catch (_: SecurityException) {
            stopSelf()
            return
        }
        windows = getSystemService(WINDOW_SERVICE) as WindowManager
        val overlayPreferences = getSharedPreferences("overlay", MODE_PRIVATE)
        panelExpanded = overlayPreferences.getBoolean("panel_expanded", false)
        activeTool = runCatching {
            AssistantTool.valueOf(overlayPreferences.getString("active_tool", AssistantTool.CAPTURE.name)!!)
        }.getOrDefault(AssistantTool.CAPTURE)
        controller = DictationController(
            AndroidSpeechEngine(this),
            DraftRepository(this),
            AndroidRestartScheduler(),
            ::renderState,
        )
        showBubble()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_NOT_STICKY
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        if (::controller.isInitialized) controller.close()
        view?.let { current -> if (::windows.isInitialized) runCatching { windows.removeView(current) } }
        view = null
        super.onDestroy()
    }

    private fun showBubble() {
        clearPanelReferences()
        val button = TextView(this).apply {
            text = "AI"
            textSize = 16f
            gravity = Gravity.CENTER
            setTextColor(Color.WHITE)
            setBackgroundResource(R.drawable.overlay_button)
            contentDescription = "Open Al-Rifa’i Assistant"
            elevation = dp(8).toFloat()
            setOnClickListener { showPanel() }
        }
        replaceBubble(button)
    }

    private fun showPanel() {
        localCaptureCount = CaptureRepository(this).list().size
        val compact = isCompactScreen()
        val panel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(10), dp(16), dp(12))
            setBackgroundResource(R.drawable.panel_background)
            elevation = dp(12).toFloat()
        }

        val header = LinearLayout(this).apply {
            gravity = Gravity.CENTER_VERTICAL
            contentDescription = if (compact) "Assistant header" else "Assistant drag handle"
        }
        val heading = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(TextView(this@OverlayService).apply {
                text = "Al-Rifa’i Assistant"
                textSize = 18f
                setTextColor(Color.rgb(35, 31, 42))
            })
            addView(TextView(this@OverlayService).apply {
                text = "Operational workspace • Local mode"
                textSize = 12f
                setTextColor(Color.DKGRAY)
            })
        }
        header.addView(heading, LinearLayout.LayoutParams(0, dp(50), 1f))
        header.addView(iconAction(if (panelExpanded) "↙" else "↗", "${if (panelExpanded) "Collapse" else "Expand"} assistant") {
            rememberComposer()
            panelExpanded = !panelExpanded
            getSharedPreferences("overlay", MODE_PRIVATE).edit()
                .putBoolean("panel_expanded", panelExpanded).apply()
            showPanel()
        })
        header.addView(iconAction("—", "Minimize assistant") { rememberComposer(); showBubble() })
        header.addView(iconAction("×", "Close assistant") { stopSelf() })
        panel.addView(header)

        val statuses = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        micStatus = statusChip("○ Mic off", Color.rgb(95, 89, 99))
        aiStatus = statusChip("AI offline", Color.rgb(121, 85, 72))
        dataStatus = statusChip(localDataLabel(), Color.rgb(0, 105, 92))
        statuses.addView(micStatus, weighted(dp(34)))
        statuses.addView(aiStatus, weighted(dp(34)))
        statuses.addView(dataStatus, weighted(dp(34)))
        panel.addView(statuses)

        detailStatus = TextView(this).apply {
            text = "Ready. No audio is being captured."
            textSize = 12f
            setPadding(0, dp(8), 0, dp(4))
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        panel.addView(detailStatus)

        val body = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        body.addView(TextView(this).apply {
            text = "How can I help? Dictate a draft, capture authorized information, or search your local knowledge."
            textSize = 14f
            setTextColor(Color.rgb(50, 47, 54))
            setPadding(0, dp(4), 0, dp(6))
        })

        val conversationScroll = ScrollView(this).apply {
            isFillViewport = true
            contentDescription = "Current dictation and assistant activity"
        }
        conversation = TextView(this).apply {
            textSize = 15f
            setTextColor(Color.rgb(35, 31, 42))
            setPadding(dp(12), dp(10), dp(12), dp(10))
            setBackgroundColor(Color.rgb(245, 242, 247))
        }
        conversationScroll.addView(conversation, ViewGroup.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT,
        ))
        val conversationHeight = if (panelExpanded) availablePanelHeight(compact) / 3 else dp(96)
        body.addView(conversationScroll, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            conversationHeight,
        ))

        val composerRow = LinearLayout(this).apply {
            gravity = Gravity.BOTTOM
            setPadding(0, dp(8), 0, dp(4))
        }
        composer = EditText(this).apply {
            hint = "Ask a question or give an instruction…"
            contentDescription = "Assistant instruction"
            minLines = 1
            maxLines = 3
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE or InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
            setTextSize(14f)
            setPadding(dp(12), dp(8), dp(12), dp(8))
            setText(pendingComposerText)
            setSelection(text.length)
        }
        composerRow.addView(composer, LinearLayout.LayoutParams(0, WindowManager.LayoutParams.WRAP_CONTENT, 1f))
        composerRow.addView(iconAction("＋", "Attach or capture information") { selectTool(AssistantTool.CAPTURE) })
        composerRow.addView(iconAction("🎙", "Start or pause microphone") { toggleMicrophone() })
        composerRow.addView(iconAction("➤", "Review instruction in editor") { reviewComposer() })
        body.addView(composerRow)

        val dictationControls = LinearLayout(this)
        dictationControls.addView(smallAction("Pause") { controller.pause() }, weighted(dp(44)))
        dictationControls.addView(smallAction("Resume") { resumeListening() }, weighted(dp(44)))
        dictationControls.addView(smallAction("Finish") { controller.finish() }, weighted(dp(44)))
        dictationControls.addView(smallAction("Cancel") { controller.cancel() }, weighted(dp(44)))
        dictationControls.addView(smallAction("Clear") { controller.clear() }, weighted(dp(44)))
        body.addView(dictationControls)

        toolContent = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(10), dp(8), dp(10), dp(8))
            setBackgroundColor(Color.rgb(250, 248, 252))
        }
        body.addView(toolContent)

        if (compact || panelExpanded) {
            val bodyScroll = ScrollView(this).apply {
                isFillViewport = true
                addView(body, ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                ))
            }
            panel.addView(bodyScroll, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                0,
                1f,
            ))
        } else {
            panel.addView(body)
        }

        val navigation = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(6), 0, 0)
        }
        tabButtons = AssistantTool.entries.associateWith { tool ->
            smallAction(tool.label) { selectTool(tool) }.also { button ->
                navigation.addView(button, weighted(dp(48)))
            }
        }
        panel.addView(navigation)

        replacePanel(panel, compact)
        if (!compact) attachDrag(header, panel)
        selectTool(activeTool)
        renderState(latestState)
    }

    private fun selectTool(tool: AssistantTool) {
        activeTool = tool
        getSharedPreferences("overlay", MODE_PRIVATE).edit().putString("active_tool", tool.name).apply()
        tabButtons.forEach { (candidate, button) ->
            button.isSelected = candidate == tool
            button.alpha = if (candidate == tool) 1f else 0.68f
            button.contentDescription = "${candidate.label} tab${if (candidate == tool) ", selected" else ""}"
        }
        val content = toolContent ?: return
        content.removeAllViews()
        when (tool) {
            AssistantTool.CAPTURE -> {
                content.addView(toolTitle("Capture information"))
                content.addView(toolDescription("Save manual text or use Android Share from an authorized message. Original content is reviewed before each local save."))
                content.addView(action("Open capture preview") { openApp("capture") })
            }
            AssistantTool.KNOWLEDGE -> {
                content.addView(toolTitle("Local knowledge"))
                content.addView(toolDescription("$localCaptureCount explicit capture(s). Cloud accounts and business APIs are not connected in this MVP."))
                content.addView(action("Open knowledge library") { openApp("knowledge") })
            }
            AssistantTool.AI_WRITE -> {
                content.addView(toolTitle("AI Write"))
                content.addView(toolDescription("Review dictation and apply faithful local cleanup. External AI generation remains disabled until a provider is configured and approved."))
                content.addView(action("Review draft") { openApp("write") })
            }
            AssistantTool.SETTINGS -> {
                content.addView(toolTitle("Settings"))
                content.addView(toolDescription("Choose Bengali or English recognition and review microphone, overlay, and privacy permissions."))
                content.addView(action("Open settings") { openApp("privacy") })
            }
        }
    }

    private fun toggleMicrophone() {
        when (latestState.phase) {
            DictationPhase.LISTENING -> controller.pause()
            DictationPhase.TEMPORARY_PAUSE -> resumeListening()
            else -> startListening()
        }
    }

    private fun startListening() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            detailStatus?.text = "Microphone permission is unavailable. Open Settings to review it."
            return
        }
        val language = getSharedPreferences("settings", MODE_PRIVATE)
            .getString("speech_language", "bn-BD") ?: "bn-BD"
        controller.start(language)
    }

    private fun resumeListening() {
        if (latestState.phase == DictationPhase.TEMPORARY_PAUSE) controller.resume() else startListening()
    }

    private fun reviewComposer() {
        val instruction = composer?.text?.toString()?.trim().orEmpty()
        pendingComposerText = instruction
        if (instruction.isBlank()) {
            detailStatus?.text = "Enter an instruction first. Nothing was sent."
            return
        }
        controller.updateDraft(instruction)
        detailStatus?.text = "Draft saved locally. Opening review; no message was sent."
        openApp("write")
    }

    private fun renderState(state: DictationState) {
        latestState = state
        val presentation = AssistantStatusPresentation.from(state.phase)
        micStatus?.text = presentation.microphoneLabel
        micStatus?.setTextColor(if (presentation.microphoneActive) Color.rgb(183, 28, 28) else Color.DKGRAY)
        aiStatus?.text = presentation.aiLabel
        dataStatus?.text = localDataLabel()
        detailStatus?.text = state.message ?: when (state.phase) {
            DictationPhase.LISTENING -> "Microphone active. AI processing is not running."
            DictationPhase.IDLE, DictationPhase.REVIEW -> "Ready. No audio is being captured."
            else -> state.phase.name.lowercase().replaceFirstChar(Char::uppercase)
        }
        val text = state.visibleText
        conversation?.text = if (text.isBlank()) {
            "No draft yet. Tap the microphone once to begin, or type an instruction below."
        } else {
            "Draft • ${DateFormat.getTimeInstance(DateFormat.SHORT).format(Date())}\n\n$text"
        }
        if (state.phase == DictationPhase.ERROR) {
            micStatus?.sendAccessibilityEvent(AccessibilityEvent.TYPE_ANNOUNCEMENT)
        }
    }

    private fun openApp(destination: String) {
        rememberComposer()
        showBubble()
        startActivity(
            Intent(this, MainActivity::class.java)
                .putExtra("destination", destination)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }

    private fun replaceBubble(next: View) {
        removeCurrentView()
        val prefs = getSharedPreferences("overlay", MODE_PRIVATE)
        params = WindowManager.LayoutParams(
            dp(58), dp(58), WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = prefs.getInt("launcher_x", 0)
            y = prefs.getInt("launcher_y", 0)
        }
        attachDrag(next, next, "launcher_x", "launcher_y")
        windows.addView(next, params)
        view = next
        next.post {
            if (!prefs.contains("launcher_x")) {
                params.x = (resources.displayMetrics.widthPixels - next.width - dp(16)).coerceAtLeast(0)
                params.y = (resources.displayMetrics.heightPixels - next.height - dp(96)).coerceAtLeast(0)
            }
            clampToScreen(next)
        }
    }

    private fun replacePanel(next: View, compact: Boolean) {
        removeCurrentView()
        val width = if (compact) WindowManager.LayoutParams.MATCH_PARENT else dp(400)
        val height = if (compact || panelExpanded) availablePanelHeight(compact) else WindowManager.LayoutParams.WRAP_CONTENT
        params = WindowManager.LayoutParams(
            width, height, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = if (compact) Gravity.BOTTOM or Gravity.START else Gravity.TOP or Gravity.START
            if (!compact) {
                val prefs = getSharedPreferences("overlay", MODE_PRIVATE)
                x = prefs.getInt("panel_x", dp(24))
                y = prefs.getInt("panel_y", dp(120))
            }
            softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
        }
        windows.addView(next, params)
        view = next
        if (!compact) next.post { clampToScreen(next) }
    }

    private fun removeCurrentView() {
        view?.let { current -> runCatching { windows.removeView(current) } }
        view = null
    }

    private fun attachDrag(
        handle: View,
        target: View,
        xKey: String = "panel_x",
        yKey: String = "panel_y",
    ) {
        var downX = 0f
        var downY = 0f
        var originX = 0
        var originY = 0
        var moved = false
        handle.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    downX = event.rawX
                    downY = event.rawY
                    originX = params.x
                    originY = params.y
                    moved = false
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = (event.rawX - downX).toInt()
                    val dy = (event.rawY - downY).toInt()
                    moved = moved || abs(dx) > dp(4) || abs(dy) > dp(4)
                    if (moved) {
                        params.x = originX + dx
                        params.y = originY + dy
                        clampToScreen(target)
                    }
                    true
                }
                MotionEvent.ACTION_UP -> {
                    if (moved) {
                        getSharedPreferences("overlay", MODE_PRIVATE).edit()
                            .putInt(xKey, params.x).putInt(yKey, params.y).apply()
                    } else {
                        handle.performClick()
                    }
                    true
                }
                else -> false
            }
        }
    }

    private fun clampToScreen(target: View) {
        val metrics = resources.displayMetrics
        params.x = params.x.coerceIn(0, (metrics.widthPixels - target.width).coerceAtLeast(0))
        params.y = params.y.coerceIn(0, (metrics.heightPixels - target.height).coerceAtLeast(0))
        runCatching { windows.updateViewLayout(target, params) }
    }

    private fun rememberComposer() {
        pendingComposerText = composer?.text?.toString().orEmpty()
    }

    private fun clearPanelReferences() {
        micStatus = null
        aiStatus = null
        dataStatus = null
        detailStatus = null
        conversation = null
        composer = null
        toolContent = null
        tabButtons = emptyMap()
    }

    private fun statusChip(label: String, color: Int) = TextView(this).apply {
        text = label
        textSize = 11f
        gravity = Gravity.CENTER
        setTextColor(color)
        setPadding(dp(4), dp(4), dp(4), dp(4))
        accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
    }

    private fun toolTitle(label: String) = TextView(this).apply {
        text = label
        textSize = 14f
        setTextColor(Color.rgb(35, 31, 42))
    }

    private fun toolDescription(label: String) = TextView(this).apply {
        text = label
        textSize = 12f
        setTextColor(Color.DKGRAY)
        setPadding(0, dp(3), 0, dp(5))
    }

    private fun iconAction(label: String, description: String, click: () -> Unit) = Button(this).apply {
        text = label
        textSize = 15f
        minWidth = dp(44)
        minHeight = dp(44)
        minimumWidth = dp(44)
        minimumHeight = dp(44)
        contentDescription = description
        setPadding(dp(6), 0, dp(6), 0)
        setOnClickListener { click() }
    }

    private fun action(label: String, click: () -> Unit) = Button(this).apply {
        text = label
        isAllCaps = false
        minHeight = dp(44)
        contentDescription = label
        setOnClickListener { click() }
    }

    private fun smallAction(label: String, click: () -> Unit) = action(label, click).apply {
        textSize = 11f
        setPadding(dp(3), 0, dp(3), 0)
    }

    private fun weighted(height: Int) = LinearLayout.LayoutParams(0, height, 1f)
    private fun isCompactScreen() = resources.configuration.screenWidthDp < 600
    private fun availablePanelHeight(compact: Boolean): Int {
        val fraction = if (compact) {
            if (panelExpanded) 0.78f else 0.68f
        } else {
            0.75f
        }
        return (resources.displayMetrics.heightPixels * fraction).toInt()
    }
    private fun localDataLabel() = "Local • $localCaptureCount"
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    private fun notification(): Notification {
        val pending = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("Al-Rifa’i Assistant")
            .setContentText(getString(R.string.overlay_active))
            .setOngoing(true)
            .setContentIntent(pending)
            .build()
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    getString(R.string.overlay_channel),
                    NotificationManager.IMPORTANCE_LOW,
                ),
            )
        }
    }

    private enum class AssistantTool(val label: String) {
        CAPTURE("Capture"), KNOWLEDGE("Knowledge"), AI_WRITE("AI Write"), SETTINGS("Settings")
    }

    companion object {
        private const val CHANNEL_ID = "voicedock_overlay"
        private const val NOTIFICATION_ID = 42
    }
}
