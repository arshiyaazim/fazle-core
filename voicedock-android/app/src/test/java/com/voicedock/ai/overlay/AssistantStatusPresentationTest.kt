package com.voicedock.ai.overlay

import com.voicedock.ai.voice.DictationPhase
import org.junit.Assert.*
import org.junit.Test

class AssistantStatusPresentationTest {
    @Test fun listeningDoesNotImplyAiProcessing() {
        val status = AssistantStatusPresentation.from(DictationPhase.LISTENING)
        assertTrue(status.microphoneActive)
        assertEquals("● Listening", status.microphoneLabel)
        assertEquals("AI offline", status.aiLabel)
    }

    @Test fun recognitionProcessingDoesNotClaimMicrophoneIsListening() {
        val status = AssistantStatusPresentation.from(DictationPhase.PROCESSING)
        assertFalse(status.microphoneActive)
        assertEquals("… Mic finishing", status.microphoneLabel)
        assertEquals("AI offline", status.aiLabel)
    }

    @Test fun idleClearlyReportsMicrophoneOff() {
        val status = AssistantStatusPresentation.from(DictationPhase.IDLE)
        assertFalse(status.microphoneActive)
        assertEquals("○ Mic off", status.microphoneLabel)
    }
}
