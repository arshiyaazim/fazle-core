package com.voicedock.ai.voice

enum class DictationPhase { IDLE, LISTENING, TEMPORARY_PAUSE, PROCESSING, REVIEW, ERROR }

data class DictationState(
    val phase: DictationPhase = DictationPhase.IDLE,
    val committedText: String = "",
    val partialText: String = "",
    val message: String? = null,
) {
    val visibleText: String get() = listOf(committedText, partialText)
        .filter { it.isNotBlank() }.joinToString(" ")
}
