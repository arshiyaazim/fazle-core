package com.voicedock.ai.text

/** Conservative offline cleanup. It never paraphrases or adds factual content. */
object FaithfulFormatter {
    private val repeated = Regex("(?i)\\b([\\p{L}]+)(?:\\s+\\1){1,}\\b")
    fun format(raw: String): String {
        var text = raw.trim().replace(Regex("\\s+"), " ")
        text = repeated.replace(text) { it.groupValues[1] }
        val commands = linkedMapOf(
            Regex("(?i)\\s+(full stop|period)(?=\\s|$)") to ".",
            Regex("(?i)\\s+comma(?=\\s|$)") to ",",
            Regex("(?i)\\s+question mark(?=\\s|$)") to "?",
            Regex("(?i)\\s+new paragraph(?=\\s|$)") to "\n\n",
            Regex("\\s+(দাঁড়ি|দাড়ি)(?=\\s|$)") to "।",
        )
        commands.forEach { (pattern, replacement) -> text = pattern.replace(text, replacement) }
        text = text.replace(Regex("\\s+([,.!?।])"), "$1")
        return text.replaceFirstChar { if (it.isLowerCase()) it.titlecase() else it.toString() }
    }
}
