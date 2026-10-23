package com.voicedock.ai.voice

import android.os.Handler
import android.os.Looper

class AndroidRestartScheduler : RestartScheduler {
    private val handler = Handler(Looper.getMainLooper())
    private var pending: Runnable? = null

    override fun schedule(delayMillis: Long, action: () -> Unit) {
        cancel()
        Runnable(action).also {
            pending = it
            handler.postDelayed(it, delayMillis)
        }
    }

    override fun cancel() {
        pending?.let(handler::removeCallbacks)
        pending = null
    }
}
