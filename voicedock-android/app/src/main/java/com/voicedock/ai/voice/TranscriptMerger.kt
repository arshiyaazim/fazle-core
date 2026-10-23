package com.voicedock.ai.voice

/** Joins recognition sessions while removing only an exact overlapping word sequence. */
object TranscriptMerger {
    fun merge(existing: String, incoming: String): String {
        val left = existing.trim().split(Regex("\\s+")).filter(String::isNotBlank)
        val right = incoming.trim().split(Regex("\\s+")).filter(String::isNotBlank)
        if (left.isEmpty()) return right.joinToString(" ")
        if (right.isEmpty()) return left.joinToString(" ")
        val max = minOf(left.size, right.size, 12)
        val overlap = (max downTo 1).firstOrNull { n ->
            left.takeLast(n).map(String::lowercase) == right.take(n).map(String::lowercase)
        } ?: 0
        return (left + right.drop(overlap)).joinToString(" ")
    }
}
