package com.voicedock.ai.data

import android.content.Context

/** Persists recoverable dictation text synchronously after every finalized segment. */
class DraftRepository(context: Context) {
    private val prefs = context.getSharedPreferences("dictation_draft", Context.MODE_PRIVATE)
    fun read(): String = prefs.getString(KEY_TEXT, "").orEmpty()
    fun save(text: String) { prefs.edit().putString(KEY_TEXT, text).apply() }
    fun clear() { prefs.edit().remove(KEY_TEXT).apply() }
    companion object { private const val KEY_TEXT = "current_text" }
}
