package com.voicedock.ai.voice

interface SpeechEngine {
    interface Listener {
        fun onReady()
        fun onPartial(text: String)
        fun onFinal(text: String)
        fun onRecoverableEnd(reason: String)
        fun onFatalError(reason: String)
    }
    fun start(languageTag: String, listener: Listener)
    fun stop()
    fun cancel()
    fun destroy()
}
