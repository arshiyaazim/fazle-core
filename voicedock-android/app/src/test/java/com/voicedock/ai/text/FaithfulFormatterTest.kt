package com.voicedock.ai.text

import org.junit.Assert.assertEquals
import org.junit.Test

class FaithfulFormatterTest {
    @Test fun appliesEnglishSpokenPunctuationWithoutParaphrasing() {
        assertEquals("Please send it, tomorrow.", FaithfulFormatter.format("please send it comma tomorrow full stop"))
    }

    @Test fun appliesBengaliDari() {
        assertEquals("আজ রিপোর্ট পাঠাবো।", FaithfulFormatter.format("আজ রিপোর্ট পাঠাবো দাঁড়ি"))
    }

    @Test fun formatsParagraphAndQuestionCommands() {
        assertEquals("First point.\n\nSecond point?", FaithfulFormatter.format("first point period new paragraph second point question mark"))
    }

    @Test fun formatsJoinedAndParenthesizedExpressions() {
        assertEquals("User_name (primary)", FaithfulFormatter.format("user underscore name open parenthesis primary close parenthesis"))
    }

    @Test fun removesThreefoldRecognitionArtifactButPreservesIntentionalDoubleWord() {
        assertEquals("Hello very very important", FaithfulFormatter.format("hello hello hello very very important"))
    }

    @Test fun preservesNamesAmountsAndDates() {
        assertEquals("Pay Arif 5000 on 12 May.", FaithfulFormatter.format("pay Arif 5000 on 12 May period"))
    }
}
