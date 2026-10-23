package com.voicedock.ai.voice

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer

/** One recognition request. DictationController reconnects requests for a continuous logical session. */
class AndroidSpeechEngine(private val context: Context) : SpeechEngine {
    private var recognizer: SpeechRecognizer? = null
    private var listener: SpeechEngine.Listener? = null

    override fun start(languageTag: String, listener: SpeechEngine.Listener) {
        this.listener = listener
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            listener.onFatalError("No speech recognition service is installed")
            return
        }
        if (recognizer == null) {
            recognizer = SpeechRecognizer.createSpeechRecognizer(context).also {
                it.setRecognitionListener(callback)
            }
        }
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, languageTag)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 2_000L)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 1_000L)
        }
        recognizer?.startListening(intent)
    }

    override fun stop() { recognizer?.stopListening() }
    override fun cancel() { recognizer?.cancel() }
    override fun destroy() { recognizer?.destroy(); recognizer = null; listener = null }

    private val callback = object : RecognitionListener {
        override fun onReadyForSpeech(params: Bundle?) = listener?.onReady() ?: Unit
        override fun onPartialResults(results: Bundle?) {
            best(results)?.let { listener?.onPartial(it) }
        }
        override fun onResults(results: Bundle?) {
            listener?.onFinal(best(results).orEmpty())
            listener?.onRecoverableEnd("Recognition segment complete")
        }
        override fun onError(error: Int) {
            val message = errorMessage(error)
            when (error) {
                SpeechRecognizer.ERROR_NO_MATCH,
                SpeechRecognizer.ERROR_SPEECH_TIMEOUT,
                SpeechRecognizer.ERROR_NETWORK,
                SpeechRecognizer.ERROR_NETWORK_TIMEOUT,
                SpeechRecognizer.ERROR_RECOGNIZER_BUSY,
                SpeechRecognizer.ERROR_SERVER,
                SpeechRecognizer.ERROR_SERVER_DISCONNECTED -> listener?.onRecoverableEnd(message)
                else -> listener?.onFatalError(message)
            }
        }
        override fun onBeginningOfSpeech() = Unit
        override fun onRmsChanged(rmsdB: Float) = Unit
        override fun onBufferReceived(buffer: ByteArray?) = Unit
        override fun onEndOfSpeech() = Unit
        override fun onEvent(eventType: Int, params: Bundle?) = Unit
    }

    private fun best(bundle: Bundle?): String? =
        bundle?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()

    private fun errorMessage(code: Int): String = when (code) {
        SpeechRecognizer.ERROR_AUDIO -> "Microphone audio error"
        SpeechRecognizer.ERROR_CLIENT -> "Recognition was interrupted"
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Microphone permission is required"
        SpeechRecognizer.ERROR_NETWORK -> "Network unavailable; draft preserved"
        SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "Recognition network timeout"
        SpeechRecognizer.ERROR_NO_MATCH -> "Waiting for speech"
        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "Recognizer busy"
        SpeechRecognizer.ERROR_SERVER -> "Recognition service error"
        SpeechRecognizer.ERROR_SERVER_DISCONNECTED -> "Recognition service disconnected"
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "Silence detected; session remains open"
        else -> "Speech recognition error ($code)"
    }
}
