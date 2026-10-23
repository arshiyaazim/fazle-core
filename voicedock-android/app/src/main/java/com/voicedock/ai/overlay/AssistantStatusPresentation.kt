package com.voicedock.ai.overlay

import com.voicedock.ai.voice.DictationPhase

data class AssistantStatusPresentation(
    val microphoneLabel: String,
    val microphoneActive: Boolean,
    val aiLabel: String,
) {
    companion object {
        fun from(phase: DictationPhase): AssistantStatusPresentation = AssistantStatusPresentation(
            microphoneLabel = when (phase) {
                DictationPhase.LISTENING -> "● Listening"
                DictationPhase.TEMPORARY_PAUSE -> "◐ Mic paused"
                DictationPhase.PROCESSING -> "… Mic finishing"
                DictationPhase.ERROR -> "⚠ Mic error"
                else -> "○ Mic off"
            },
            microphoneActive = phase == DictationPhase.LISTENING,
            // AI state is intentionally independent from microphone/recognition state.
            aiLabel = "AI offline",
        )
    }
}
