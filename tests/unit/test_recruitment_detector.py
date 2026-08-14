"""
Unit tests — modules/recruitment_detector (2026-07-11)

3-layer recruitment intent detection, additive to the existing flat
keyword check in modules.recruitment_flow.is_recruitment_trigger.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit


class TestEntityScoring:
    def test_decisive_category_triggers_alone(self):
        from modules.recruitment_detector import _score_entities, ENTITY_THRESHOLD
        score, cats = _score_entities("ভাই সুযোগ দেন")
        assert score >= ENTITY_THRESHOLD
        assert "opportunity_ask" in cats

    def test_two_supporting_categories_combine(self):
        from modules.recruitment_detector import _score_entities, ENTITY_THRESHOLD
        score, cats = _score_entities("আমি available আছি, আগে security তে ছিলাম")
        assert score >= ENTITY_THRESHOLD
        assert "availability" in cats and "experience_mention" in cats

    def test_single_supporting_category_alone_is_not_enough(self):
        from modules.recruitment_detector import _score_entities, ENTITY_THRESHOLD
        score, _ = _score_entities("আমি available আছি এখন")
        assert score < ENTITY_THRESHOLD

    def test_weak_category_alone_never_triggers(self):
        """'আমার নাম রহিম' appears constantly in non-recruitment contexts."""
        from modules.recruitment_detector import _score_entities, ENTITY_THRESHOLD
        score, _ = _score_entities("আমার নাম রহিম")
        assert score < ENTITY_THRESHOLD

    def test_unrelated_message_scores_zero(self):
        from modules.recruitment_detector import _score_entities
        score, cats = _score_entities("কাল payment কবে হবে?")
        assert score == 0
        assert cats == []

    def test_empty_message_scores_zero(self):
        from modules.recruitment_detector import _score_entities
        score, cats = _score_entities("")
        assert score == 0


class TestDetectRecruitmentIntent:
    async def test_layer1_entity_detects_decisive_phrase(self):
        from modules.recruitment_detector import detect_recruitment_intent
        result = await detect_recruitment_intent(text="ভাই সুযোগ দেন", phone="8801999000111", intent="unknown")
        assert result["is_recruitment"] is True
        assert result["layer"] == "entity"

    async def test_layer2_reuses_already_computed_intent_no_new_llm_call(self):
        """Layer 2 must not fire a second LLM call -- it only reads the
        intent value message_router already computed this turn."""
        from modules.recruitment_detector import detect_recruitment_intent
        with patch("app.llm.classify_intent_llm", new_callable=AsyncMock) as mock_llm:
            result = await detect_recruitment_intent(
                text="এই বিষয়ে জানতে চাই", phone="8801999000111", intent="recruitment",
            )
        assert result["is_recruitment"] is True
        assert result["layer"] == "intent"
        assert not mock_llm.called

    async def test_no_layer_matches_returns_false(self):
        from modules.recruitment_detector import detect_recruitment_intent
        with patch("modules.recruitment_flow.get_active_session", new=AsyncMock(return_value=None)), \
             patch("modules.message_router.get_recent_history", new=AsyncMock(return_value=[])):
            result = await detect_recruitment_intent(text="হ্যালো", phone="8801999000111", intent="unknown")
        assert result["is_recruitment"] is False
        assert result["layer"] == "none"

    async def test_layer3_active_session_detects(self):
        from modules.recruitment_detector import detect_recruitment_intent
        with patch(
            "modules.recruitment_flow.get_active_session",
            new=AsyncMock(return_value={"collection_step": "age"}),
        ):
            result = await detect_recruitment_intent(text="২৮", phone="8801999000111", intent="unknown")
        assert result["is_recruitment"] is True
        assert result["layer"] == "context"

    async def test_context_check_never_raises_on_db_error(self):
        from modules.recruitment_detector import detect_recruitment_intent
        with patch(
            "modules.recruitment_flow.get_active_session",
            new=AsyncMock(side_effect=RuntimeError("db down")),
        ):
            result = await detect_recruitment_intent(text="হ্যালো", phone="8801999000111", intent="unknown")
        assert result["is_recruitment"] is False  # degrades safely, never raises

    async def test_empty_text_returns_false_immediately(self):
        from modules.recruitment_detector import detect_recruitment_intent
        result = await detect_recruitment_intent(text="", phone="8801999000111", intent="unknown")
        assert result["is_recruitment"] is False
        assert result["layer"] == "none"


class TestRecruitmentEligibilityIntegration:
    """The detector is wired into recruitment_flow.recruitment_eligibility(),
    not message_router directly -- that's the single existing decision
    function message_router already calls."""

    async def test_natural_phrase_now_eligible_via_detector(self):
        from modules.recruitment_flow import recruitment_eligibility
        with patch("modules.recruitment_flow.get_active_session", new=AsyncMock(return_value=None)):
            result = await recruitment_eligibility(
                "8801999000111", "ভাই সুযোগ দেন", role="candidate", intent="unknown",
            )
        assert result["eligible"] is True
        assert result["reason"] == "detector_entity"
        assert result["autosend"] is True  # entity layer is high-confidence -> autosend

    async def test_intent_layer_result_is_draft_only_not_autosend(self):
        """Lower-confidence layers (intent/context) must go to draft review,
        matching the existing session_followup_draft precedent -- never
        autosend on a fuzzy signal."""
        from modules.recruitment_flow import recruitment_eligibility
        with patch("modules.recruitment_flow.get_active_session", new=AsyncMock(return_value=None)):
            result = await recruitment_eligibility(
                "8801999000111", "এই বিষয়ে আরেকটু বলুন", role="candidate", intent="recruitment",
            )
        assert result["eligible"] is True
        assert result["reason"] == "detector_intent"
        assert result["autosend"] is False

    async def test_operational_role_still_excluded_before_detector_runs(self):
        """Hard exclusion gates (role/intent) must still short-circuit before
        the detector ever runs -- an accountant's message about vacancies
        must never be treated as a recruitment inquiry."""
        from modules.recruitment_flow import recruitment_eligibility
        result = await recruitment_eligibility(
            "8801999000111", "ভাই সুযোগ দেন", role="accountant", intent="unknown",
        )
        assert result["eligible"] is False
        assert result["reason"] == "operational_identity"


class TestActiveSessionContinuationAutosend:
    """2026-08-15 fix: a direct step-by-step answer inside an already-active
    (already high-confidence-vetted) recruitment session must autosend, not
    fall through to the 3-layer detector's Layer 3 (active_session context
    match), which is intentionally autosend=False for the *first-contact*
    ambiguous case. Left unfixed, this meant a candidate answering "25" to
    "what's your age?" -- or any other structured funnel step -- could
    never autosend, so the entire multi-step intake funnel was stuck
    requiring manual admin approval on every single message after the
    first, defeating the point of an automated step-by-step intake."""

    async def test_plain_age_answer_during_active_session_now_autosends(self):
        from modules.recruitment_flow import recruitment_eligibility

        session = {"id": 28, "phone": "8801322982195", "collection_step": "age"}
        with patch("modules.recruitment_flow.get_active_session", new=AsyncMock(return_value=session)):
            result = await recruitment_eligibility(
                "8801322982195", "25", role="candidate", intent="unknown",
            )
        assert result["eligible"] is True
        assert result["autosend"] is True
        assert result["reason"] == "active_session_continuation"
        assert result["active_session"] == session

    async def test_district_name_answer_during_active_session_autosends(self):
        """Control: an area/district answer is exactly as unmatchable by
        entity/explicit-trigger detection as an age -- must behave the same."""
        from modules.recruitment_flow import recruitment_eligibility

        session = {"id": 28, "phone": "8801322982195", "collection_step": "area"}
        with patch("modules.recruitment_flow.get_active_session", new=AsyncMock(return_value=session)):
            result = await recruitment_eligibility(
                "8801322982195", "Cox's Bazar", role="candidate", intent="unknown",
            )
        assert result["autosend"] is True
        assert result["reason"] == "active_session_continuation"

    async def test_off_topic_question_during_active_session_still_drafts(self):
        """session_followup_draft must be checked FIRST and still win over
        the new continuation branch -- an off-topic side-question mid-
        session ("who are you?") is not a trusted funnel answer and must
        still go to draft review, exactly as before this fix."""
        from modules.recruitment_flow import recruitment_eligibility

        session = {"id": 28, "phone": "8801322982195", "collection_step": "age"}
        with patch("modules.recruitment_flow.get_active_session", new=AsyncMock(return_value=session)):
            result = await recruitment_eligibility(
                "8801322982195", "who are you", role="candidate", intent="unknown",
            )
        assert result["eligible"] is True
        assert result["autosend"] is False
        assert result["reason"] == "session_followup_draft"

    async def test_no_active_session_behavior_is_completely_unaffected(self):
        """Control: the fix must not change anything about first-contact
        (no active session) eligibility -- still gated by explicit trigger
        / 3-layer detector exactly as before."""
        from modules.recruitment_flow import recruitment_eligibility

        with patch("modules.recruitment_flow.get_active_session", new=AsyncMock(return_value=None)):
            result = await recruitment_eligibility(
                "8801999000222", "25", role="candidate", intent="unknown",
            )
        assert result["eligible"] is False
        assert result["reason"] == "no_recruitment_context"


class TestUnknownSenderSoftAsk:
    """
    A brand-new number with zero prior history anywhere (identity_brain's
    phone-only secondary-evidence checks already ran and found nothing,
    hence role='unknown' rather than 'employee') gets a soft ask prepended
    to the first recruitment reply -- covers an existing employee texting
    from a genuinely new SIM. This is a soft ask, not a gate: the funnel
    proceeds identically either way.
    """

    async def test_unknown_role_gets_soft_ask_prepended(self):
        from modules.recruitment_flow import intake_message, UNKNOWN_SENDER_SOFT_ASK
        with patch("modules.recruitment_flow._get_session", new=AsyncMock(return_value=None)), \
             patch("modules.recruitment_flow._create_session", new=AsyncMock(return_value=99)):
            result = await intake_message("8801999000111", "চাকরি দরকার", role="unknown")
        assert result["action"] == "created"
        assert result["reply"].startswith(UNKNOWN_SENDER_SOFT_ASK)

    async def test_candidate_role_does_not_get_soft_ask(self):
        """role='candidate' already means identity_brain matched an explicit
        job-related keyword -- not the 'truly unrecognized' case this ask
        targets."""
        from modules.recruitment_flow import intake_message, STEP_QUESTIONS
        with patch("modules.recruitment_flow._get_session", new=AsyncMock(return_value=None)), \
             patch("modules.recruitment_flow._create_session", new=AsyncMock(return_value=99)):
            result = await intake_message("8801999000111", "চাকরি দরকার", role="candidate")
        assert result["reply"] == STEP_QUESTIONS["name"]

    async def test_default_role_matches_previous_no_role_behavior(self):
        """Backward compatibility: intake_message's role param defaults to
        'unknown', so any existing caller that never passed role keeps
        getting the soft ask -- not a silent behavior change to 'no ask'."""
        from modules.recruitment_flow import intake_message, UNKNOWN_SENDER_SOFT_ASK
        with patch("modules.recruitment_flow._get_session", new=AsyncMock(return_value=None)), \
             patch("modules.recruitment_flow._create_session", new=AsyncMock(return_value=99)):
            result = await intake_message("8801999000111", "চাকরি দরকার")
        assert result["reply"].startswith(UNKNOWN_SENDER_SOFT_ASK)


class TestIsRecruitmentTrigger:
    """2026-08-14 fix regression coverage: the explicit trigger list had
    "job korte chai" but not the very common no-"h" transliteration "job
    korte cai" ("+8801322982195" incident, message 4: "Ami Security guard
    er job korte cai"), so that message only ever qualified via the
    3-layer detector's intent layer (autosend=False), never via the
    explicit-trigger path (which would have set autosend=True)."""

    def test_amar_cv_matches_bare_cv_keyword(self):
        from modules.recruitment_flow import is_recruitment_trigger
        assert is_recruitment_trigger("Amar CV") is True

    def test_job_korte_chai_still_matches(self):
        """Pre-existing phrase must be unaffected by the addition."""
        from modules.recruitment_flow import is_recruitment_trigger
        assert is_recruitment_trigger("ami job korte chai") is True

    def test_job_korte_cai_now_matches(self):
        """The fix: the common no-'h' transliteration must now match too."""
        from modules.recruitment_flow import is_recruitment_trigger
        assert is_recruitment_trigger("Ami Security guard er job korte cai") is True

    def test_unrelated_message_still_does_not_match(self):
        """Control: the new phrase must not widen matching to unrelated text."""
        from modules.recruitment_flow import is_recruitment_trigger
        assert is_recruitment_trigger("Hello sir, how are you?") is False
