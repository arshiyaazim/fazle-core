package com.voicedock.ai.overlay

import android.Manifest
import android.app.*
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.PixelFormat
import android.os.Build
import android.os.IBinder
import android.provider.Settings
import android.view.*
import android.widget.*
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.voicedock.ai.MainActivity
import com.voicedock.ai.R
import com.voicedock.ai.data.DraftRepository
import com.voicedock.ai.voice.*
import kotlin.math.abs

class OverlayService : Service() {
    private lateinit var windows: WindowManager
    private lateinit var params: WindowManager.LayoutParams
    private var view: View? = null
    private var expanded = false
    private var status: TextView? = null
    private var transcript: TextView? = null
    private lateinit var controller: DictationController

    override fun onCreate() {
        super.onCreate()
        createChannel()
        startForeground(NOTIFICATION_ID, notification())
        if (!Settings.canDrawOverlays(this)) { stopSelf(); return }
        windows = getSystemService(WINDOW_SERVICE) as WindowManager
        controller = DictationController(AndroidSpeechEngine(this), DraftRepository(this), ::renderState)
        showBubble()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onDestroy() {
        if (::controller.isInitialized) controller.close()
        view?.let { runCatching { windows.removeView(it) } }
        super.onDestroy()
    }

    private fun showBubble() {
        expanded = false
        val button = TextView(this).apply {
            text = "🎙"; textSize = 24f; gravity = Gravity.CENTER
            setTextColor(0xffffffff.toInt()); setBackgroundResource(R.drawable.overlay_button)
            contentDescription = "Open VoiceDock assistant"
            setOnClickListener { showPanel() }
        }
        replaceView(button, dp(58), dp(58))
    }

    private fun showPanel() {
        expanded = true
        val panel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dp(16), dp(12), dp(16), dp(12))
            setBackgroundResource(R.drawable.panel_background)
        }
        val titleRow = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
        titleRow.addView(TextView(this).apply { text = "VoiceDock AI"; textSize = 18f }, LinearLayout.LayoutParams(0, dp(44), 1f))
        titleRow.addView(action("—") { showBubble() })
        titleRow.addView(action("×") { stopSelf() })
        panel.addView(titleRow)
        status = TextView(this).apply { text = "Ready"; textSize = 13f }
        transcript = TextView(this).apply { text = controller.snapshot().visibleText.ifBlank { "Your draft appears here" }; textSize = 16f; setPadding(0, dp(8), 0, dp(8)) }
        panel.addView(status)
        panel.addView(transcript, LinearLayout.LayoutParams(dp(300), dp(120)))
        val row1 = LinearLayout(this)
        row1.addView(action("Voice") { startListening() }, weighted())
        row1.addView(action("Pause") { controller.pause() }, weighted())
        row1.addView(action("Resume") { startListening(resume = true) }, weighted())
        panel.addView(row1)
        val row2 = LinearLayout(this)
        row2.addView(action("Finish") { controller.finish() }, weighted())
        row2.addView(action("Copy") { copyDraft() }, weighted())
        row2.addView(action("Clear") { controller.clear() }, weighted())
        panel.addView(row2)
        val row3 = LinearLayout(this)
        row3.addView(action("AI Write") { openApp("write") }, weighted())
        row3.addView(action("Capture") { openApp("capture") }, weighted())
        row3.addView(action("Knowledge") { openApp("knowledge") }, weighted())
        panel.addView(row3)
        replaceView(panel, WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT)
    }

    private fun startListening(resume: Boolean = false) {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            status?.text = "Open VoiceDock and grant microphone permission"
            return
        }
        if (resume) controller.resume() else controller.start()
    }

    private fun renderState(state: DictationState) {
        status?.text = when (state.phase) {
            DictationPhase.LISTENING -> "● ${state.message ?: "Listening"}"
            else -> state.message ?: state.phase.name.lowercase().replaceFirstChar(Char::uppercase)
        }
        transcript?.text = state.visibleText.ifBlank { "Your draft appears here" }
    }

    private fun copyDraft() {
        val text = controller.snapshot().visibleText
        if (text.isBlank()) { status?.text = "Nothing to copy"; return }
        (getSystemService(CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("VoiceDock draft", text))
        status?.text = "Copied — paste into the target app"
    }

    private fun openApp(destination: String) {
        startActivity(Intent(this, MainActivity::class.java).putExtra("destination", destination).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
    private fun action(label: String, click: () -> Unit) = Button(this).apply { text = label; isAllCaps = false; setOnClickListener { click() } }
    private fun weighted() = LinearLayout.LayoutParams(0, dp(50), 1f)

    private fun replaceView(next: View, width: Int, height: Int) {
        view?.let { runCatching { windows.removeView(it) } }
        val prefs = getSharedPreferences("overlay", MODE_PRIVATE)
        params = WindowManager.LayoutParams(width, height,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT).apply {
            gravity = Gravity.TOP or Gravity.START; x = prefs.getInt("x", 24); y = prefs.getInt("y", 180)
        }
        attachDrag(next)
        windows.addView(next, params); view = next
    }

    private fun attachDrag(target: View) {
        var downX = 0f; var downY = 0f; var originX = 0; var originY = 0; var moved = false
        target.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> { downX = event.rawX; downY = event.rawY; originX = params.x; originY = params.y; moved = false; true }
                MotionEvent.ACTION_MOVE -> {
                    val dx = (event.rawX - downX).toInt(); val dy = (event.rawY - downY).toInt()
                    moved = moved || abs(dx) > 8 || abs(dy) > 8
                    if (moved) { params.x = originX + dx; params.y = originY + dy; windows.updateViewLayout(target, params) }
                    true
                }
                MotionEvent.ACTION_UP -> {
                    if (moved) getSharedPreferences("overlay", MODE_PRIVATE).edit().putInt("x", params.x).putInt("y", params.y).apply()
                    else target.performClick(); true
                }
                else -> false
            }
        }
    }

    private fun notification(): Notification {
        val pending = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Builder(this, CHANNEL_ID).setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("VoiceDock AI").setContentText(getString(R.string.overlay_active)).setOngoing(true).setContentIntent(pending).build()
    }
    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= 26) (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
            .createNotificationChannel(NotificationChannel(CHANNEL_ID, getString(R.string.overlay_channel), NotificationManager.IMPORTANCE_LOW))
    }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    companion object { private const val CHANNEL_ID = "voicedock_overlay"; private const val NOTIFICATION_ID = 42 }
}
