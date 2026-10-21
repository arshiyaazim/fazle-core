# ============================================================
# WBOM — Message Processor
# Classifies incoming WhatsApp messages and orchestrates
# data extraction + template suggestion
# Phase 3: AI Processing Logic & Algorithms
# Sprint-5 S5-02: complaint path now routes to wbom_complaints
#                 (single complaint truth) via services.complaints
# ============================================================
import logging
import re
from typing import Optional

from database import insert_row, update_row_no_ts, search_rows

logger = logging.getLogger("wbom.message_processor")

# ── Classification rules (Phase 3 spec §3.1) ─────────────────

MESSAGE_CLASSIFICATION_RULES = {
    "escort_order": {
        "keywords": ["mv", "m.v", "lighter", "escort", "capacity", "master", "mob", "dest"],
        "patterns": [
            r"m\.?v\.?\s+[\w\s-]+",       # Mother vessel pattern
            r"capacity.*\d+.*m\.?t",       # Capacity pattern
            r"0\d{10}",                    # Mobile number
        ],
        "min_keyword_matches": 3,
        "min_pattern_matches": 2,
    },
    "payment": {
        "keywords": ["id:", "bkash", "nagad", "rocket", "/-", "tk"],
        "patterns": [
            r"id:\s*0\d{10}",
            r"\d+/-",
            r"\([BbNnRr]\)",
        ],
        "min_keyword_matches": 2,
        "min_pattern_matches": 2,
    },
    "complaint": {
        "keywords": [
            "complaint", "complain", "অভিযোগ", "সমস্যা", "চুরি", "theft",
            "guard absent", "গার্ড আসে নাই", "গার্ড নাই", "রুড", "রূঢ়", "ঝামেলা",
        ],
        "patterns": [
            r"(?i)(complaint|complain|অভিযোগ|সমস্যা)",
            r"(?i)(চুরি|theft|রুড|রূঢ়|absent|আসে নাই|নেই|no\s*guard)",
        ],
        "min_keyword_matches": 1,
        "min_pattern_matches": 1,
    },
    "query": {
        "keywords": ["?", "when", "where", "how", "কবে", "কখন", "কোথায়"],
        "min_keyword_matches": 1,
    },
}


def classify_message(message_text: str) -> tuple[str, float]:
    """Classify incoming WhatsApp message (Phase 3 §3.1).

    Returns: (classification_type, confidence_score)
    """
    scores = {}

    for msg_type, rules in MESSAGE_CLASSIFICATION_RULES.items():
        score = 0

        # Keyword matching
        keyword_matches = sum(
            1 for kw in rules["keywords"] if kw.lower() in message_text.lower()
        )
        if keyword_matches >= rules.get("min_keyword_matches", 1):
            score += keyword_matches * 10

        # Pattern matching
        if "patterns" in rules:
            pattern_matches = sum(
                1
                for pattern in rules["patterns"]
                if re.search(pattern, message_text, re.IGNORECASE)
            )
            if pattern_matches >= rules.get("min_pattern_matches", 1):
                score += pattern_matches * 20

        scores[msg_type] = score

    if max(scores.values(), default=0) > 0:
        # Sort by score descending for tie-breaking (first defined type wins)
        sorted_types = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        best_type, best_score = sorted_types[0]

        # Check for tie — if top two scores are equal, fall to "general"
        if len(sorted_types) > 1 and sorted_types[1][1] == best_score:
            logger.warning(
                "Ambiguous classification: %s and %s tied at %d",
                sorted_types[0][0], sorted_types[1][0], best_score,
            )
            return "general", 0.5

        confidence = min(best_score / 100, 1.0)

        # Reject low-confidence classifications
        if confidence < 0.3:
            return "general", confidence

        return best_type, confidence

    return "general", 0.5


def identify_sender(sender_number: str) -> Optional[dict]:
    """Look up sender in contacts table."""
    rows = search_rows("fazle_contacts", "whatsapp_number", sender_number, limit=1)
    return rows[0] if rows else None


def process_incoming_message(
    sender_number: str,
    message_body: str,
    whatsapp_msg_id: str = None,
    content_type: str = "text",
) -> dict:
    """Full pipeline: classify → extract → suggest template → return draft.

    Returns dict with:
        - message_id: int
        - classification: str
        - confidence: float
        - extracted_data: dict
        - suggested_template: dict | None
        - draft_reply: str | None
        - requires_admin_input: bool
        - missing_fields: list[str]
        - unfilled_fields: list[str]
        - confidence_scores: dict
    """
    # 1. Identify sender
    contact = identify_sender(sender_number)
    contact_id = contact["contact_id"] if contact else None

    # 2. Classify message (Phase 3 algorithm)
    classification, confidence = classify_message(message_body)
    from services.case_workflow import is_complaint_text as _is_complaint_text
    if classification == "general" and _is_complaint_text(message_body):
        classification, confidence = "complaint", max(confidence, 0.75)

    # 3. Store raw message
    msg_data = {
        "whatsapp_msg_id": whatsapp_msg_id,
        "contact_id": contact_id,
        "sender_number": sender_number,
        "message_type": "incoming",
        "content_type": content_type,
        "message_body": message_body,
        "classification": classification,
    }
    stored_msg = insert_row("fazle_whatsapp_messages", msg_data)
    message_id = stored_msg["message_id"]

    # 3b. Multi-lighter detection (Phase 8 §Scenario 3)
    from services.data_extractor import extract_all_fields, detect_multi_lighter

    is_multi_lighter = (
        classification == "escort_order" and detect_multi_lighter(message_body)
    )

    # Boost confidence for multi-lighter (numbered entries are a strong signal)
    if is_multi_lighter:
        confidence = min(confidence + 0.15, 1.0)

    # 4. Extract data (Phase 3 §3.2)
    # Map classification → required fields
    required_fields_map = {
        "escort_order": [
            "mother_vessel", "lighter_vessel", "mobile_number",
            "destination", "capacity", "date",
        ],
        "payment": [
            "employee_name", "amount", "payment_method", "mobile_number",
        ],
        "complaint": [],
        "query": ["mother_vessel", "date"],
        "general": [],
    }
    required = required_fields_map.get(classification, [])
    extracted = extract_all_fields(message_body, required)

    # Store extracted fields
    for field_name, field_info in extracted.items():
        if field_info.get("value"):
            insert_row("wbom_extracted_data", {
                "message_id": message_id,
                "field_name": field_name,
                "field_value": str(field_info["value"]),
                "confidence_score": field_info.get("confidence", 0.0),
            })

    # 5. Select template (Phase 3 §3.3)
    from services.template_engine import select_template_for_contact, generate_template

    template = select_template_for_contact(contact_id, classification)
    draft_reply = None
    missing_fields = []
    unfilled_fields = []
    confidence_scores = {}

    if template:
        result = generate_template(
            template, extracted, {"sender": sender_number, "contact": contact}
        )
        draft_reply = result["template"]
        unfilled_fields = result["unfilled_fields"]
        confidence_scores = result["confidence_scores"]
        missing_fields = unfilled_fields

    # 6. Mark as processed
    update_row_no_ts("fazle_whatsapp_messages", "message_id", message_id, {
        "is_processed": True,
        "classification": classification,
        "template_used_id": template["template_id"] if template else None,
    })

    # Sprint-5 S5-02: complaints go to wbom_complaints (single truth).
    # wbom_cases is no longer used for complaint-type messages.
    complaint_result = None
    if classification == "complaint":
        from services.case_workflow import is_complaint_text
        from services.complaints import ingest_complaint, _detect_category_from_text

        # Determine complaint_type: look up contact → if employee-linked, use 'employee'
        complaint_type = "client"
        if contact_id:
            from database import get_row as _get_row
            c = _get_row("fazle_contacts", "contact_id", contact_id)
            if c and c.get("relation") in ("employee", "staff"):
                complaint_type = "employee"

        category = _detect_category_from_text(message_body, complaint_type)
        complaint_result = ingest_complaint(
            complaint_type=complaint_type,
            category=category,
            description=message_body,
            reporter_phone=sender_number,
            source="whatsapp",
        )
        logger.info(
            "Complaint ingested via message_processor: complaint_id=%s priority=%s",
            complaint_result.get("complaint_id"),
            complaint_result.get("priority"),
        )

    result = {
        "message_id": message_id,
        "classification": classification,
        "confidence": confidence,
        "is_multi_lighter": is_multi_lighter,
        "extracted_data": {
            k: v.get("value") for k, v in extracted.items() if v.get("value")
        },
        "suggested_template": template,
        "draft_reply": draft_reply,
        "requires_admin_input": bool(missing_fields),
        "missing_fields": missing_fields,
        "unfilled_fields": unfilled_fields,
        "confidence_scores": confidence_scores,
    }
    if complaint_result:
        result["complaint_id"] = complaint_result.get("complaint_id")
        result["complaint_priority"] = complaint_result.get("priority")
    return result
