package com.voicedock.ai.voice

import android.os.Handler
import android.os.Looper
import com.voicedock.ai.data.DraftRepository

class DictationController(
    private val engine: SpeechEngine,
    private val drafts: DraftRepository,
    private val onState: (DictationState) -> Unit,
) : SpeechEngine.Listener {
    private val handler = Handler(Looper.getMainLooper())
    private var state = DictationState(committedText = drafts.read())
    private var sessionActive = false
    private var paused = false
    private var languageTag = "bn-BD"
    private var restartAttempts = 0
    private val restart = Runnable { if (sessionActive && !paused) engine.start(languageTag, this) }

    init { emit() }

    fun start(language: String = languageTag) {
        languageTag = language
        sessionActive = true; paused = false; restartAttempts = 0
        state = state.copy(phase = DictationPhase.LISTENING, message = "Starting microphone…")
        emit(); engine.start(languageTag, this)
    }
    fun pause() {
        if (!sessionActive) return
        paused = true; handler.removeCallbacks(restart); engine.cancel()
        commitPartial(); state = state.copy(phase = DictationPhase.TEMPORARY_PAUSE, message = "Paused — draft preserved")
        emit()
    }
    fun resume() { if (sessionActive) { paused = false; restartAttempts = 0; scheduleRestart(0) } else start() }
    fun finish() {
        sessionActive = false; paused = false; handler.removeCallbacks(restart); engine.stop(); commitPartial()
        state = state.copy(phase = DictationPhase.REVIEW, message = "Ready to review")
        emit()
    }
    fun cancel() {
        sessionActive = false; paused = false; handler.removeCallbacks(restart); engine.cancel()
        state = state.copy(phase = DictationPhase.REVIEW, partialText = "", message = "Listening cancelled; saved text kept")
        emit()
    }
    fun clear() { drafts.clear(); state = DictationState(phase = DictationPhase.REVIEW, message = "Draft cleared"); emit() }
    fun close() { handler.removeCallbacksAndMessages(null); engine.destroy() }
    fun snapshot(): DictationState = state

    override fun onReady() { state = state.copy(phase = DictationPhase.LISTENING, message = "Listening"); emit() }
    override fun onPartial(text: String) { state = state.copy(partialText = text); emit() }
    override fun onFinal(text: String) {
        state = state.copy(committedText = TranscriptMerger.merge(state.committedText, text), partialText = "")
        restartAttempts = 0
        drafts.save(state.committedText); emit()
    }
    override fun onRecoverableEnd(reason: String) {
        commitPartial()
        if (sessionActive && !paused) {
            if (restartAttempts >= MAX_CONSECUTIVE_RESTARTS) {
                paused = true
                state = state.copy(phase = DictationPhase.TEMPORARY_PAUSE, message = "$reason — microphone stopped; tap Resume")
                emit()
                return
            }
            state = state.copy(phase = DictationPhase.TEMPORARY_PAUSE, message = "$reason — reconnecting")
            emit(); scheduleRestart(500L * (1L shl restartAttempts.coerceAtMost(3)))
            restartAttempts++
        }
    }
    override fun onFatalError(reason: String) {
        commitPartial(); sessionActive = false
        state = state.copy(phase = DictationPhase.ERROR, message = reason); emit()
    }
    private fun scheduleRestart(delay: Long) { handler.removeCallbacks(restart); handler.postDelayed(restart, delay) }
    private fun commitPartial() {
        if (state.partialText.isNotBlank()) {
            state = state.copy(committedText = TranscriptMerger.merge(state.committedText, state.partialText), partialText = "")
            drafts.save(state.committedText)
        }
    }
    private fun emit() = onState(state)

    private companion object { const val MAX_CONSECUTIVE_RESTARTS = 5 }
}
