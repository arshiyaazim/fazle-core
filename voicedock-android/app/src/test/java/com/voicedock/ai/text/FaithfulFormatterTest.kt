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
    @Test fun removesImmediateRepeatedRecognitionArtifact() {
        assertEquals("Hello world", FaithfulFormatter.format("hello hello world"))
    }
    @Test fun preservesNamesAmountsAndDates() {
        assertEquals("Pay Arif 5000 on 12 May.", FaithfulFormatter.format("pay Arif 5000 on 12 May period"))
    }
}
