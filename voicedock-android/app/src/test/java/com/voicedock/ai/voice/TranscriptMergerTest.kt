package com.voicedock.ai.voice

import org.junit.Assert.assertEquals
import org.junit.Test

class TranscriptMergerTest {
    @Test fun removesOverlapAcrossRecognitionSessions() {
        assertEquals("Please send the report tomorrow morning", TranscriptMerger.merge("Please send the report", "the report tomorrow morning"))
    }
    @Test fun keepsBengaliSegmentsAndFacts() {
        assertEquals("আগামীকাল রিপোর্ট পাঠাবো সকাল দশটায়", TranscriptMerger.merge("আগামীকাল রিপোর্ট পাঠাবো", "রিপোর্ট পাঠাবো সকাল দশটায়"))
    }
    @Test fun identicalSegmentIsNotDuplicated() {
        assertEquals("one two three", TranscriptMerger.merge("one two three", "one two three"))
    }
    @Test fun nonOverlappingTextIsAppended() {
        assertEquals("alpha beta gamma delta", TranscriptMerger.merge("alpha beta", "gamma delta"))
    }
}
