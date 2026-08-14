"""Unit tests — modules.bridge_poller's recruitment/master auto-reply gate
(process_bridge_inbound), covering the 2026-08-14 fix.

Regression coverage for the P17-FIX-2 defeat: get_effective_auto_reply()'s
own master-toggle check (auto_reply.all) was being applied a second time
when computing _recruit_autoreply_on, so auto_reply.recruitment='true'
could never take effect while auto_reply.all='false' -- even though the
whole point of this code block (see its own "recruit_gate — recruitment
intake bypasses SAFE MODE" comment) is for recruitment to bypass exactly
that master switch. Fixed by reading auto_reply.recruitment directly via
get_runtime_setting(), independent of the master gate.

All tests are pure unit tests: every DB/Redis/LLM/outbound-transport call
is mocked at its existing import boundary inside modules.bridge_poller
(the same pattern already used by test_bridge_poller_phone_block.py). No
real DB row, Redis key, or WhatsApp message is touched.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit


def _base_settings(**overrides) -> SimpleNamespace:
    """A _settings stub with every gate that isn't under test here
    deterministically inert (empty draft-always lists, no risk phones,
    AI_SAFE_MODE off, empty admin set) -- mirrors test_bridge_poller_
    phone_block.py's _empty_settings() helper."""
    base = dict(
        admin_meta_number="",
        admin_bridge1_number="",
        admin_bridge2_number="",
        admin_number_list=[],
        draft_always_phone_set=frozenset(),
        draft_always_role_set=frozenset(),
        draft_always_name_list=[],
        draft_name_prefix_list=[],
        contact_risk_map={},
        ai_safe_mode=False,
        auto_reply_enabled=False,
        recruitment_autoreply_enabled=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _runtime_settings(values: dict):
    """Fake modules.wa_chat_frontend.get_runtime_setting -- returns values[key]
    if present, else the caller's own default (matches the real function's
    signature/behavior exactly)."""

    async def _fake(key, default="false"):
        return values.get(key, default)

    return _fake


def _install_common_mocks(monkeypatch, *, intent="recruitment", reply_text="আপনার বয়স কত বছর?"):
    """Mocks shared by every test below: intent classification, reply
    generation (message_router.process_message), the intent-writeback DB
    call, and clean in-memory loop-detect/cooldown state. recruitment_
    eligibility and the wa_chat_frontend auto-reply reads are left for each
    test to set explicitly, since they're the thing under test.

    intent=None leaves the real modules.intent.classify() in place (used by
    TestPhaseALiveVerificationCases, where the real classification result
    for each case's actual text is itself part of what's being proven)."""
    import modules.bridge_poller as bp

    if intent is not None:
        monkeypatch.setattr(bp, "classify_intent", lambda text: intent)
    monkeypatch.setattr(bp, "process_message", AsyncMock(return_value=(reply_text, None)))
    monkeypatch.setattr(bp, "execute", AsyncMock())
    monkeypatch.setattr(bp, "_save_message", AsyncMock())
    monkeypatch.setattr(bp, "_reply_ts_window", {})
    monkeypatch.setattr(bp, "_loop_paused_until", {})
    monkeypatch.setattr(bp, "_record_reply", AsyncMock())
    enqueue_mock = AsyncMock(return_value="fake-qid-1")
    monkeypatch.setattr("modules.outbound.enqueue", enqueue_mock)
    create_draft_mock = AsyncMock(return_value=4242)
    monkeypatch.setattr(bp, "create_draft_reply", create_draft_mock)
    return enqueue_mock, create_draft_mock


class TestRecruitGateMasterToggleFix:
    """TEST 1 & TEST 2 from the fix-request: auto_reply.all=false,
    auto_reply.recruitment=true must let a genuinely-eligible recruitment
    message bypass SAFE MODE, while leaving the general (non-recruitment)
    path exactly as master-gated as before."""

    async def test_recruitment_autosend_true_reaches_outbound_when_master_off(self, monkeypatch):
        """TEST 1: auto_reply.all=false, auto_reply.recruitment=true,
        recruitment autosend=True -> _recruit_gate=True -> message reaches
        modules.outbound.enqueue()."""
        import modules.bridge_poller as bp

        enqueue_mock, create_draft_mock = _install_common_mocks(monkeypatch)
        monkeypatch.setattr(bp, "_settings", _base_settings())
        monkeypatch.setattr(
            bp,
            "recruitment_eligibility",
            AsyncMock(return_value={"eligible": True, "autosend": True, "reason": "explicit_recruitment"}),
        )
        monkeypatch.setattr(bp, "_can_reply", AsyncMock(return_value=True))
        monkeypatch.setattr(bp, "_check_keyword_flood", lambda phone, text: False)
        monkeypatch.setattr(
            "modules.wa_chat_frontend.get_effective_auto_reply",
            AsyncMock(return_value=False),  # master off -> general _auto_reply_on is False
        )
        monkeypatch.setattr(
            "modules.wa_chat_frontend.get_runtime_setting",
            _runtime_settings({"auto_reply.recruitment": "true"}),
        )

        await bp.process_bridge_inbound(
            "bridge2", "8801322982195", "Amar CV",
            id_role="candidate", id_conf=50, id_name="",
        )

        enqueue_mock.assert_awaited_once()
        create_draft_mock.assert_not_awaited()

    async def test_non_recruitment_sender_still_respects_master_switch(self, monkeypatch):
        """TEST 2: same DB state (auto_reply.all=false, auto_reply.recruitment=
        true), but the sender/message is NOT recruitment-eligible. The general
        path must be entirely unaffected by the recruitment fix -- master
        switch off means draft, not send."""
        import modules.bridge_poller as bp

        enqueue_mock, create_draft_mock = _install_common_mocks(monkeypatch, intent="greeting", reply_text="Hello!")
        monkeypatch.setattr(bp, "_settings", _base_settings())
        monkeypatch.setattr(
            bp,
            "recruitment_eligibility",
            AsyncMock(return_value={"eligible": False, "autosend": False, "reason": "no_recruitment_context"}),
        )
        monkeypatch.setattr(bp, "_can_reply", AsyncMock(return_value=True))
        monkeypatch.setattr(bp, "_check_keyword_flood", lambda phone, text: False)
        monkeypatch.setattr(
            "modules.wa_chat_frontend.get_effective_auto_reply",
            AsyncMock(return_value=False),
        )
        monkeypatch.setattr(
            "modules.wa_chat_frontend.get_runtime_setting",
            _runtime_settings({"auto_reply.recruitment": "true"}),
        )

        await bp.process_bridge_inbound(
            "bridge2", "8801999000001", "Hello sir",
            id_role="unknown", id_conf=0, id_name="",
        )

        enqueue_mock.assert_not_awaited()
        create_draft_mock.assert_awaited_once()


class TestRecruitGateCooldownStillApplies:
    """TEST 5 & TEST 6 (cooldown portion): recruit_gate=True must never
    bypass the pre-existing 60-second REPLY_COOLDOWN gate -- that gate runs
    (via _can_reply) before recruitment_eligibility/process_message are
    even invoked, entirely independent of recruit_gate."""

    async def test_second_message_within_cooldown_never_reaches_recruitment_eligibility(self, monkeypatch):
        import modules.bridge_poller as bp

        enqueue_mock, create_draft_mock = _install_common_mocks(monkeypatch)
        monkeypatch.setattr(bp, "_settings", _base_settings())
        recruit_elig_mock = AsyncMock(
            return_value={"eligible": True, "autosend": True, "reason": "explicit_recruitment"}
        )
        monkeypatch.setattr(bp, "recruitment_eligibility", recruit_elig_mock)
        monkeypatch.setattr(bp, "_check_keyword_flood", lambda phone, text: False)
        monkeypatch.setattr(
            "modules.wa_chat_frontend.get_effective_auto_reply", AsyncMock(return_value=False)
        )
        monkeypatch.setattr(
            "modules.wa_chat_frontend.get_runtime_setting",
            _runtime_settings({"auto_reply.recruitment": "true"}),
        )

        # First message: cooldown clear -> proceeds all the way to send.
        monkeypatch.setattr(bp, "_can_reply", AsyncMock(return_value=True))
        await bp.process_bridge_inbound(
            "bridge2", "8801322982195", "Amar CV",
            id_role="unknown", id_conf=0, id_name="",
        )
        assert enqueue_mock.await_count == 1
        assert recruit_elig_mock.await_count == 1

        # Second message, 146ms later in the real incident: cooldown still
        # active -> _can_reply returns False -> function must return before
        # recruitment_eligibility (or anything downstream) is ever called again.
        monkeypatch.setattr(bp, "_can_reply", AsyncMock(return_value=False))
        await bp.process_bridge_inbound(
            "bridge2", "8801322982195", "irriculam itae ... CV text",
            id_role="candidate", id_conf=50, id_name="",
        )

        assert enqueue_mock.await_count == 1, "cooldown must block the second send"
        assert recruit_elig_mock.await_count == 1, "cooldown must block BEFORE recruitment_eligibility runs"
        assert create_draft_mock.await_count == 0, "blocked-by-cooldown must not even reach the draft path"


class TestRecruitGateDoesNotBypassOtherSafetyGates:
    """TEST 6 (remaining portions): recruit_gate=True must not bypass the
    advance-request/complaint/financial draft gate, loop detection, the
    outbound poison filter, or the outbound length/structure guard.

    Structural note discovered while writing this suite (not a change made
    here): `bridge_poller.process_bridge_inbound()` unconditionally sets
    `msg_intent = "recruitment"` the moment `recruit_decision["eligible"]`
    is True (`modules/bridge_poller/__init__.py`, just after the
    `recruitment_eligibility()` call) -- *before* the financial-intent
    draft gate is ever checked. So a message that is simultaneously
    recruit-eligible and financial-intent-shaped never actually reaches
    the financial-intent gate with its original intent label; only the
    text-content-based advance-request-phrase gate below (which does not
    depend on msg_intent at all) can still fire in that combination. This
    is existing behavior, unrelated to and unchanged by this fix -- tested
    below via the advance-request-phrase gate instead, which is the
    correct way to prove a *text-content* safety gate survives recruit_gate.
    """

    async def test_advance_request_phrase_still_forces_draft(self, monkeypatch):
        import modules.bridge_poller as bp

        enqueue_mock, create_draft_mock = _install_common_mocks(
            monkeypatch, reply_text="Noted, we'll follow up."
        )
        monkeypatch.setattr(bp, "_settings", _base_settings())
        monkeypatch.setattr(
            bp, "recruitment_eligibility",
            AsyncMock(return_value={"eligible": True, "autosend": True, "reason": "explicit_recruitment"}),
        )
        monkeypatch.setattr(bp, "_can_reply", AsyncMock(return_value=True))
        monkeypatch.setattr(bp, "_check_keyword_flood", lambda phone, text: False)
        monkeypatch.setattr("modules.wa_chat_frontend.get_effective_auto_reply", AsyncMock(return_value=False))
        monkeypatch.setattr(
            "modules.wa_chat_frontend.get_runtime_setting",
            _runtime_settings({"auto_reply.recruitment": "true"}),
        )

        # Recruitment-shaped text that ALSO contains an existing
        # advance-request phrase (checked against raw text, independent of
        # msg_intent) -- proves recruit_gate cannot bypass this gate even
        # though the message is genuinely recruitment-eligible.
        await bp.process_bridge_inbound(
            "bridge2", "8801322982195", "Amar CV, advance চাই",
            id_role="candidate", id_conf=50, id_name="",
        )

        enqueue_mock.assert_not_awaited()
        create_draft_mock.assert_awaited_once()

    async def test_loop_detect_still_forces_draft_even_with_recruit_gate(self, monkeypatch):
        import modules.bridge_poller as bp

        enqueue_mock, create_draft_mock = _install_common_mocks(monkeypatch)
        monkeypatch.setattr(bp, "_settings", _base_settings())
        monkeypatch.setattr(
            bp, "recruitment_eligibility",
            AsyncMock(return_value={"eligible": True, "autosend": True, "reason": "explicit_recruitment"}),
        )
        monkeypatch.setattr(bp, "_can_reply", AsyncMock(return_value=True))
        monkeypatch.setattr(bp, "_check_keyword_flood", lambda phone, text: False)
        monkeypatch.setattr("modules.wa_chat_frontend.get_effective_auto_reply", AsyncMock(return_value=False))
        monkeypatch.setattr(
            "modules.wa_chat_frontend.get_runtime_setting",
            _runtime_settings({"auto_reply.recruitment": "true"}),
        )
        # Simulate the phone already at the loop-detect threshold.
        monkeypatch.setattr(bp, "_check_loop_detect", lambda phone: True)

        await bp.process_bridge_inbound(
            "bridge2", "8801322982195", "Amar CV",
            id_role="candidate", id_conf=50, id_name="",
        )

        enqueue_mock.assert_not_awaited()
        create_draft_mock.assert_awaited_once()

    async def test_outbound_length_guard_still_forces_draft(self, monkeypatch):
        import modules.bridge_poller as bp

        long_reply = "আপনার আবেদন গ্রহণ করা হয়েছে। " * 30  # well over 400 chars
        enqueue_mock, create_draft_mock = _install_common_mocks(monkeypatch, reply_text=long_reply)
        monkeypatch.setattr(bp, "_settings", _base_settings())
        monkeypatch.setattr(
            bp, "recruitment_eligibility",
            AsyncMock(return_value={"eligible": True, "autosend": True, "reason": "explicit_recruitment"}),
        )
        monkeypatch.setattr(bp, "_can_reply", AsyncMock(return_value=True))
        monkeypatch.setattr(bp, "_check_keyword_flood", lambda phone, text: False)
        monkeypatch.setattr("modules.wa_chat_frontend.get_effective_auto_reply", AsyncMock(return_value=False))
        monkeypatch.setattr(
            "modules.wa_chat_frontend.get_runtime_setting",
            _runtime_settings({"auto_reply.recruitment": "true"}),
        )
        monkeypatch.setattr(bp, "_record_safety_incident", AsyncMock())
        monkeypatch.setattr(bp, "_alert_admin_safety_block", AsyncMock())

        await bp.process_bridge_inbound(
            "bridge2", "8801322982195", "Amar CV",
            id_role="candidate", id_conf=50, id_name="",
        )

        enqueue_mock.assert_not_awaited()
        create_draft_mock.assert_awaited_once()

    async def test_outbound_poison_still_forces_draft(self, monkeypatch):
        import modules.bridge_poller as bp

        poisoned_reply = "Here is the chain_of_thought behind this answer."
        enqueue_mock, create_draft_mock = _install_common_mocks(monkeypatch, reply_text=poisoned_reply)
        monkeypatch.setattr(bp, "_settings", _base_settings())
        monkeypatch.setattr(
            bp, "recruitment_eligibility",
            AsyncMock(return_value={"eligible": True, "autosend": True, "reason": "explicit_recruitment"}),
        )
        monkeypatch.setattr(bp, "_can_reply", AsyncMock(return_value=True))
        monkeypatch.setattr(bp, "_check_keyword_flood", lambda phone, text: False)
        monkeypatch.setattr("modules.wa_chat_frontend.get_effective_auto_reply", AsyncMock(return_value=False))
        monkeypatch.setattr(
            "modules.wa_chat_frontend.get_runtime_setting",
            _runtime_settings({"auto_reply.recruitment": "true"}),
        )
        monkeypatch.setattr(bp, "_record_safety_incident", AsyncMock())
        monkeypatch.setattr(bp, "_alert_admin_safety_block", AsyncMock())

        await bp.process_bridge_inbound(
            "bridge2", "8801322982195", "Amar CV",
            id_role="candidate", id_conf=50, id_name="",
        )

        enqueue_mock.assert_not_awaited()
        create_draft_mock.assert_awaited_once()


class TestEmployeePathReachesSendPipelineWhenConfigured:
    """TEST 7: the existing employee path (role="employee") uses the exact
    same general _auto_reply_on gate as every non-recruitment role -- no
    new bypass. Proves the pipeline itself is intact: when the master
    switch AND the per-role employee toggle are genuinely on, an employee
    reply reaches modules.outbound.enqueue() through entirely existing
    code, with no change made anywhere on this path."""

    async def test_employee_sender_sends_when_master_and_role_toggle_on(self, monkeypatch):
        import modules.bridge_poller as bp

        enqueue_mock, create_draft_mock = _install_common_mocks(
            monkeypatch, intent="attendance", reply_text="আপনার হাজিরা রেকর্ড করা হয়েছে।"
        )
        monkeypatch.setattr(bp, "_settings", _base_settings())
        # Employee role is never recruitment-eligible (OPERATIONAL_ROLES) --
        # bridge_poller's own recruit_decision copy reflects that.
        monkeypatch.setattr(
            bp, "recruitment_eligibility",
            AsyncMock(return_value={"eligible": False, "autosend": False, "reason": "operational_identity"}),
        )
        monkeypatch.setattr(bp, "_can_reply", AsyncMock(return_value=True))
        monkeypatch.setattr(bp, "_check_keyword_flood", lambda phone, text: False)
        # Master switch AND the employee-specific toggle both on.
        monkeypatch.setattr(
            "modules.wa_chat_frontend.get_effective_auto_reply", AsyncMock(return_value=True)
        )
        monkeypatch.setattr(
            "modules.wa_chat_frontend.get_runtime_setting",
            _runtime_settings({"auto_reply.recruitment": "false"}),
        )

        await bp.process_bridge_inbound(
            "bridge1", "8801711000001", "aj upashthit",
            id_role="employee", id_conf=88, id_name="Test Employee",
        )

        enqueue_mock.assert_awaited_once()
        create_draft_mock.assert_not_awaited()

    async def test_employee_sender_drafts_when_master_off(self, monkeypatch):
        """Control: with the master switch off (today's live state), the
        SAME employee message must NOT send -- unchanged existing
        behavior, confirming this fix did not accidentally widen the
        employee path."""
        import modules.bridge_poller as bp

        enqueue_mock, create_draft_mock = _install_common_mocks(
            monkeypatch, intent="attendance", reply_text="আপনার হাজিরা রেকর্ড করা হয়েছে।"
        )
        monkeypatch.setattr(bp, "_settings", _base_settings())
        monkeypatch.setattr(
            bp, "recruitment_eligibility",
            AsyncMock(return_value={"eligible": False, "autosend": False, "reason": "operational_identity"}),
        )
        monkeypatch.setattr(bp, "_can_reply", AsyncMock(return_value=True))
        monkeypatch.setattr(bp, "_check_keyword_flood", lambda phone, text: False)
        monkeypatch.setattr(
            "modules.wa_chat_frontend.get_effective_auto_reply", AsyncMock(return_value=False)
        )
        monkeypatch.setattr(
            "modules.wa_chat_frontend.get_runtime_setting",
            _runtime_settings({"auto_reply.recruitment": "true"}),
        )

        await bp.process_bridge_inbound(
            "bridge1", "8801711000001", "aj upashthit",
            id_role="employee", id_conf=88, id_name="Test Employee",
        )

        enqueue_mock.assert_not_awaited()
        create_draft_mock.assert_awaited_once()


class TestActiveSessionFunnelAnswerReachesOutbound:
    """2026-08-15 fix (recruitment_flow.recruitment_eligibility's
    active_session_continuation branch): a plain funnel-step answer inside
    an already-active recruitment session -- exactly the class of message
    that was previously permanently stuck at draft-only after the first
    message in any funnel -- now reaches outbound.enqueue() once master
    SAFE MODE is off but auto_reply.recruitment is on, same as any other
    autosend=True recruitment message."""

    async def test_age_answer_in_active_session_reaches_outbound(self, monkeypatch):
        import modules.bridge_poller as bp

        enqueue_mock, create_draft_mock = _install_common_mocks(
            monkeypatch, intent="unknown", reply_text="আপনি কোন জেলায় থাকেন?"
        )
        monkeypatch.setattr(bp, "_settings", _base_settings())
        monkeypatch.setattr(
            bp, "recruitment_eligibility",
            AsyncMock(return_value={
                "eligible": True, "autosend": True, "reason": "active_session_continuation",
                "active_session": {"id": 28, "collection_step": "age"},
            }),
        )
        monkeypatch.setattr(bp, "_can_reply", AsyncMock(return_value=True))
        monkeypatch.setattr(bp, "_check_keyword_flood", lambda phone, text: False)
        monkeypatch.setattr("modules.wa_chat_frontend.get_effective_auto_reply", AsyncMock(return_value=False))
        monkeypatch.setattr(
            "modules.wa_chat_frontend.get_runtime_setting",
            _runtime_settings({"auto_reply.recruitment": "true"}),
        )

        await bp.process_bridge_inbound(
            "bridge2", "8801322982195", "25",
            id_role="candidate", id_conf=50, id_name="",
        )

        enqueue_mock.assert_awaited_once()
        create_draft_mock.assert_not_awaited()


class TestPhaseALiveVerificationCases:
    """2026-08-15 Phase A end-to-end proof (Cases A-D). Unlike the tests
    above, recruitment_eligibility() itself is NOT mocked here -- only
    get_active_session() (its one DB dependency) and process_message() (its
    LLM-generation dependent caller) are stubbed. Every other function in
    the real chain (is_recruitment_trigger, the 3-layer detector,
    recruitment_eligibility's own branching) runs for real, against the
    real production text of each case, proving the actual chain end to
    end rather than a mocked decision."""

    async def _run_case(self, monkeypatch, *, text, id_role, id_conf, active_session,
                         master_on=False, recruit_on=True):
        import modules.bridge_poller as bp
        import modules.recruitment_flow as rf

        # intent=None: use the REAL modules.intent.classify() for each
        # case's actual text -- both intent classification and recruitment
        # eligibility are real here, only the DB session lookup and the
        # LLM-backed reply generator are stubbed.
        enqueue_mock, create_draft_mock = _install_common_mocks(
            monkeypatch, intent=None, reply_text="reply text"
        )
        monkeypatch.setattr(bp, "_settings", _base_settings())
        monkeypatch.setattr(bp, "_can_reply", AsyncMock(return_value=True))
        monkeypatch.setattr(bp, "_check_keyword_flood", lambda phone, text: False)
        monkeypatch.setattr(rf, "get_active_session", AsyncMock(return_value=active_session))
        monkeypatch.setattr(
            "modules.wa_chat_frontend.get_effective_auto_reply", AsyncMock(return_value=master_on)
        )
        monkeypatch.setattr(
            "modules.wa_chat_frontend.get_runtime_setting",
            _runtime_settings({"auto_reply.recruitment": "true" if recruit_on else "false"}),
        )

        # Capture the real eligibility decision as bridge_poller computes it,
        # without intercepting the call.
        real_eligibility = rf.recruitment_eligibility
        captured = {}

        async def _spy(*a, **kw):
            result = await real_eligibility(*a, **kw)
            captured["decision"] = result
            return result

        monkeypatch.setattr(bp, "recruitment_eligibility", _spy)

        await bp.process_bridge_inbound(
            "bridge2", "8801322982195", text,
            id_role=id_role, id_conf=id_conf, id_name="",
        )
        return captured["decision"], enqueue_mock, create_draft_mock

    async def test_case_a_explicit_job_request_autosends(self, monkeypatch):
        """Case A: "Ami Security guard er job korte cai" -- no active
        session. Must be recognized as an explicit recruitment trigger
        (via the "job korte cai" phrase fix) with autosend=True, and with
        the master-gate fix + master off/recruitment on, must reach
        outbound.enqueue()."""
        decision, enqueue_mock, create_draft_mock = await self._run_case(
            monkeypatch,
            text="Ami Security guard er job korte cai",
            id_role="candidate", id_conf=50, active_session=None,
        )
        assert decision["eligible"] is True
        assert decision["autosend"] is True
        assert decision["reason"] == "explicit_recruitment"
        enqueue_mock.assert_awaited_once()
        create_draft_mock.assert_not_awaited()

    async def test_case_b_active_session_valid_answer_autosends(self, monkeypatch):
        """Case B: a valid follow-up answer ("25") inside an already-
        established recruitment session must be active_session_continuation
        with autosend=True, and must reach outbound.enqueue()."""
        session = {"id": 28, "phone": "8801322982195", "collection_step": "age"}
        decision, enqueue_mock, create_draft_mock = await self._run_case(
            monkeypatch, text="25", id_role="candidate", id_conf=50, active_session=session,
        )
        assert decision["eligible"] is True
        assert decision["autosend"] is True
        assert decision["reason"] == "active_session_continuation"
        enqueue_mock.assert_awaited_once()
        create_draft_mock.assert_not_awaited()

    async def test_case_c_off_topic_during_session_stays_protected(self, monkeypatch):
        """Case C: an off-topic question ("who are you") during an active
        session must remain autosend=False and must NOT reach
        outbound.enqueue() -- goes to draft instead."""
        session = {"id": 28, "phone": "8801322982195", "collection_step": "age"}
        decision, enqueue_mock, create_draft_mock = await self._run_case(
            monkeypatch, text="who are you", id_role="candidate", id_conf=50, active_session=session,
        )
        assert decision["eligible"] is True
        assert decision["autosend"] is False
        assert decision["reason"] == "session_followup_draft"
        enqueue_mock.assert_not_awaited()
        create_draft_mock.assert_awaited_once()

    async def test_case_d_non_recruitment_unknown_sender_never_autosends(self, monkeypatch):
        """Case D: a non-recruitment unknown sender with auto_reply.all=false
        must NOT reach outbound.enqueue() -- this fix must not weaken that."""
        decision, enqueue_mock, create_draft_mock = await self._run_case(
            monkeypatch, text="Hello sir", id_role="unknown", id_conf=0, active_session=None,
        )
        assert decision["eligible"] is False
        enqueue_mock.assert_not_awaited()
        create_draft_mock.assert_awaited_once()
