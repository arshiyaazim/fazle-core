package com.voicedock.ai.voice

interface DraftStore {
    fun read(): String
    fun save(text: String)
    fun clear()
}

interface RestartScheduler {
    fun schedule(delayMillis: Long, action: () -> Unit)
    fun cancel()
}

/**
 * Owns one logical dictation session across multiple provider recognition requests.
 * This class has no Android dependency, so lifecycle/error transitions are JVM-testable.
 */
class DictationController(
    private val engine: SpeechEngine,
    private val drafts: DraftStore,
    private val scheduler: RestartScheduler,
    private val onState: (DictationState) -> Unit,
) : SpeechEngine.Listener {
    private var state = DictationState(committedText = drafts.read())
    private var sessionActive = false
    private var paused = false
    private var acceptFinalAfterStop = false
    private var languageTag = "bn-BD"
    private var restartAttempts = 0

    init { emit() }

    fun start(language: String = languageTag) {
        scheduler.cancel()
        languageTag = language
        sessionActive = true
        paused = false
        acceptFinalAfterStop = false
        restartAttempts = 0
        state = state.copy(phase = DictationPhase.LISTENING, message = "Starting microphone…")
        emit()
        engine.start(languageTag, this)
    }

    fun pause() {
        if (!sessionActive || paused) return
        paused = true
        scheduler.cancel()
        commitPartial()
        // Set state before cancel: synchronous ERROR_CLIENT callbacks are then ignored.
        state = state.copy(phase = DictationPhase.TEMPORARY_PAUSE, message = "Paused — draft preserved")
        emit()
        engine.cancel()
    }

    fun resume() {
        if (!sessionActive) {
            start()
            return
        }
        if (!paused) return
        paused = false
        restartAttempts = 0
        state = state.copy(phase = DictationPhase.TEMPORARY_PAUSE, message = "Resuming…")
        emit()
        scheduleRestart(0)
    }

    fun finish() {
        if (!sessionActive && !paused) return
        scheduler.cancel()
        commitPartial()
        sessionActive = false
        paused = false
        acceptFinalAfterStop = true
        state = state.copy(phase = DictationPhase.PROCESSING, message = "Finishing recognition…")
        emit()
        engine.stop()
        // Some engines do not issue a final callback after stop. The committed draft is stable now.
        state = state.copy(phase = DictationPhase.REVIEW, message = "Ready to review")
        emit()
    }

    fun cancel() {
        sessionActive = false
        paused = false
        acceptFinalAfterStop = false
        scheduler.cancel()
        commitPartial()
        state = state.copy(
            phase = DictationPhase.REVIEW,
            partialText = "",
            message = "Listening cancelled; captured text preserved",
        )
        emit()
        engine.cancel()
    }

    fun clear() {
        drafts.clear()
        state = DictationState(phase = DictationPhase.REVIEW, message = "Draft cleared")
        emit()
    }

    fun updateDraft(text: String) {
        val wasActive = sessionActive || paused
        sessionActive = false
        paused = false
        acceptFinalAfterStop = false
        scheduler.cancel()
        val normalized = text.trim()
        state = state.copy(
            phase = DictationPhase.REVIEW,
            committedText = normalized,
            partialText = "",
            message = "Draft saved locally for review",
        )
        drafts.save(normalized)
        emit()
        if (wasActive) engine.cancel()
    }

    fun close() {
        sessionActive = false
        paused = false
        acceptFinalAfterStop = false
        scheduler.cancel()
        engine.destroy()
    }

    fun snapshot(): DictationState = state

    override fun onReady() {
        if (!sessionActive || paused) return
        state = state.copy(phase = DictationPhase.LISTENING, message = "Listening")
        emit()
    }

    override fun onPartial(text: String) {
        if (!sessionActive || paused) return
        state = state.copy(partialText = text)
        emit()
    }

    override fun onFinal(text: String) {
        if ((!sessionActive || paused) && !acceptFinalAfterStop) return
        state = state.copy(
            committedText = TranscriptMerger.merge(state.committedText, text),
            partialText = "",
        )
        acceptFinalAfterStop = false
        restartAttempts = 0
        drafts.save(state.committedText)
        emit()
    }

    override fun onRecoverableEnd(reason: String) {
        if (!sessionActive || paused) return
        commitPartial()
        if (restartAttempts >= MAX_CONSECUTIVE_RESTARTS) {
            paused = true
            state = state.copy(
                phase = DictationPhase.TEMPORARY_PAUSE,
                message = "$reason — microphone stopped; tap Resume",
            )
            emit()
            return
        }
        state = state.copy(
            phase = DictationPhase.TEMPORARY_PAUSE,
            message = "$reason — reconnecting",
        )
        emit()
        scheduleRestart(BASE_RESTART_DELAY_MS * (1L shl restartAttempts.coerceAtMost(3)))
        restartAttempts++
    }

    override fun onFatalError(reason: String) {
        if (!sessionActive || paused) return
        commitPartial()
        sessionActive = false
        scheduler.cancel()
        state = state.copy(phase = DictationPhase.ERROR, message = reason)
        emit()
    }

    private fun scheduleRestart(delay: Long) {
        scheduler.cancel()
        scheduler.schedule(delay) {
            if (sessionActive && !paused) engine.start(languageTag, this)
        }
    }

    private fun commitPartial() {
        if (state.partialText.isBlank()) return
        state = state.copy(
            committedText = TranscriptMerger.merge(state.committedText, state.partialText),
            partialText = "",
        )
        drafts.save(state.committedText)
    }

    private fun emit() = onState(state)

    private companion object {
        const val MAX_CONSECUTIVE_RESTARTS = 5
        const val BASE_RESTART_DELAY_MS = 500L
    }
}
