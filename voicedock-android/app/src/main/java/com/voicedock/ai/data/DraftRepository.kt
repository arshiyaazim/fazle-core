package com.voicedock.ai.data

import android.content.Context
import com.voicedock.ai.voice.DraftStore

/** Persists recoverable dictation text after every finalized or preserved partial segment. */
class DraftRepository(context: Context) : DraftStore {
    private val prefs = context.getSharedPreferences("dictation_draft", Context.MODE_PRIVATE)
    override fun read(): String = prefs.getString(KEY_TEXT, "").orEmpty()
    override fun save(text: String) { prefs.edit().putString(KEY_TEXT, text).apply() }
    override fun clear() { prefs.edit().remove(KEY_TEXT).apply() }
    companion object { private const val KEY_TEXT = "current_text" }
}
