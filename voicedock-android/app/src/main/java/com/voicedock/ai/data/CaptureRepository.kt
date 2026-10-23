package com.voicedock.ai.data

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.util.UUID

data class CaptureRecord(val id: String, val title: String, val text: String, val source: String?, val createdAt: Long)

/** Each explicit capture is an independent local record; repeated content never overwrites prior records. */
class CaptureRepository(context: Context) {
    private val directory = File(context.filesDir, "captures").apply { mkdirs() }
    fun save(title: String, text: String, source: String?): CaptureRecord {
        val record = CaptureRecord(UUID.randomUUID().toString(), title.trim().ifBlank { "Untitled capture" }, text, source, System.currentTimeMillis())
        val json = JSONObject().put("id", record.id).put("title", record.title).put("text", record.text)
            .put("source", record.source ?: JSONObject.NULL).put("createdAt", record.createdAt)
        val destination = File(directory, "${record.id}.json")
        val temporary = File(directory, ".${record.id}.tmp")
        temporary.writeText(json.toString())
        check(temporary.renameTo(destination)) { "Unable to persist capture atomically" }
        return record
    }
    fun list(): List<CaptureRecord> = directory.listFiles { file -> file.extension == "json" }.orEmpty().mapNotNull { file ->
        runCatching {
            val json = JSONObject(file.readText())
            CaptureRecord(json.getString("id"), json.getString("title"), json.getString("text"),
                json.optString("source").takeUnless { it.isBlank() || it == "null" }, json.getLong("createdAt"))
        }.getOrNull()
    }.sortedByDescending { it.createdAt }
    fun delete(id: String): Boolean = File(directory, "$id.json").delete()
}
