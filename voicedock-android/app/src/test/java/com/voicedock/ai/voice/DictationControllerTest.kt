package com.voicedock.ai.voice

import org.junit.Assert.*
import org.junit.Test

class DictationControllerTest {
    @Test fun pausePreservesPartialAndIgnoresCancellationError() {
        val fixture = Fixture(cancelEmitsError = true)
        fixture.controller.start("en-US")
        fixture.engine.listener!!.onPartial("draft words")

        fixture.controller.pause()

        assertEquals(DictationPhase.TEMPORARY_PAUSE, fixture.controller.snapshot().phase)
        assertEquals("draft words", fixture.store.text)
        assertTrue(fixture.controller.snapshot().message!!.startsWith("Paused"))
    }

    @Test fun resumeStartsAReplacementRecognitionRequest() {
        val fixture = Fixture()
        fixture.controller.start()
        fixture.controller.pause()
        fixture.controller.resume()
        assertEquals(1, fixture.engine.starts)

        fixture.scheduler.runPending()

        assertEquals(2, fixture.engine.starts)
    }

    @Test fun finishAcceptsSynchronousFinalResultAndEntersReview() {
        val fixture = Fixture(stopFinal = "final words")
        fixture.controller.start()

        fixture.controller.finish()

        assertEquals(DictationPhase.REVIEW, fixture.controller.snapshot().phase)
        assertEquals("final words", fixture.store.text)
    }

    @Test fun cancelPreservesCapturedPartialAndIgnoresLateFatalError() {
        val fixture = Fixture(cancelEmitsError = true)
        fixture.controller.start()
        fixture.engine.listener!!.onPartial("keep this")

        fixture.controller.cancel()

        assertEquals(DictationPhase.REVIEW, fixture.controller.snapshot().phase)
        assertEquals("keep this", fixture.store.text)
        assertFalse(fixture.controller.snapshot().message!!.contains("fatal"))
    }

    @Test fun recoverableFailuresStopAfterBoundedRestarts() {
        val fixture = Fixture()
        fixture.controller.start()
        repeat(5) {
            fixture.engine.listener!!.onRecoverableEnd("network")
            assertTrue(fixture.scheduler.hasPending)
            fixture.scheduler.runPending()
        }

        fixture.engine.listener!!.onRecoverableEnd("network")

        assertFalse(fixture.scheduler.hasPending)
        assertEquals(DictationPhase.TEMPORARY_PAUSE, fixture.controller.snapshot().phase)
        assertTrue(fixture.controller.snapshot().message!!.contains("tap Resume"))
        assertEquals(6, fixture.engine.starts)
    }

    @Test fun finalizedSegmentsResetConsecutiveFailureBudget() {
        val fixture = Fixture()
        fixture.controller.start()
        repeat(5) {
            fixture.engine.listener!!.onRecoverableEnd("timeout")
            fixture.scheduler.runPending()
        }
        fixture.engine.listener!!.onFinal("saved segment")

        fixture.engine.listener!!.onRecoverableEnd("timeout")

        assertTrue(fixture.scheduler.hasPending)
        assertEquals("saved segment", fixture.store.text)
    }

    private class Fixture(cancelEmitsError: Boolean = false, stopFinal: String? = null) {
        val engine = FakeEngine(cancelEmitsError, stopFinal)
        val store = FakeStore()
        val scheduler = FakeScheduler()
        val states = mutableListOf<DictationState>()
        val controller = DictationController(engine, store, scheduler) { states.add(it) }
    }

    private class FakeEngine(
        private val cancelEmitsError: Boolean,
        private val stopFinal: String?,
    ) : SpeechEngine {
        var listener: SpeechEngine.Listener? = null
        var starts = 0
        override fun start(languageTag: String, listener: SpeechEngine.Listener) {
            this.listener = listener
            starts++
        }
        override fun stop() { stopFinal?.let { listener?.onFinal(it) } }
        override fun cancel() { if (cancelEmitsError) listener?.onFatalError("late fatal") }
        override fun destroy() = Unit
    }

    private class FakeStore : DraftStore {
        var text = ""
        override fun read(): String = text
        override fun save(text: String) { this.text = text }
        override fun clear() { text = "" }
    }

    private class FakeScheduler : RestartScheduler {
        private var action: (() -> Unit)? = null
        val hasPending: Boolean get() = action != null
        override fun schedule(delayMillis: Long, action: () -> Unit) { this.action = action }
        override fun cancel() { action = null }
        fun runPending() { action.also { action = null }?.invoke() }
    }
}
