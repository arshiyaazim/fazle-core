package com.voicedock.ai.text

/** Conservative offline cleanup. It never paraphrases or adds factual content. */
object FaithfulFormatter {
    // Two repeated words may be intentional emphasis; collapse only 3+ identical consecutive tokens.
    private val repeatedArtifact = Regex("(?i)\\b([\\p{L}]+)(?:\\s+\\1){2,}\\b")

    fun format(raw: String): String {
        var text = raw.trim().replace(Regex("[ \\t]+"), " ")
        text = repeatedArtifact.replace(text) { it.groupValues[1] }
        val commands = linkedMapOf(
            Regex("(?i)\\s+(full stop|period)(?=\\s|$)") to ".",
            Regex("(?i)\\s+comma(?=\\s|$)") to ",",
            Regex("(?i)\\s+question mark(?=\\s|$)") to "?",
            Regex("(?i)\\s+exclamation mark(?=\\s|$)") to "!",
            Regex("(?i)\\s+new paragraph(?=\\s|$)") to "\n\n",
            Regex("(?i)\\s+underscore\\s+") to "_",
            Regex("(?i)\\s+hyphen\\s+") to "-",
            Regex("(?i)\\s+open parenthesis\\s+") to " (",
            Regex("(?i)\\s+close parenthesis(?=\\s|$)") to ")",
            Regex("\\s+(দাঁড়ি|দাড়ি)(?=\\s|$)") to "।",
        )
        commands.forEach { (pattern, replacement) -> text = pattern.replace(text, replacement) }
        text = text.replace(Regex("[ \\t]+([,.!?।)])"), "$1")
            .replace(Regex("\\n[ \\t]+"), "\n")
            .replace(Regex("[ \\t]+\\)"), ")")
        return text.replaceFirstChar { if (it.isLowerCase()) it.titlecase() else it.toString() }
    }
}
