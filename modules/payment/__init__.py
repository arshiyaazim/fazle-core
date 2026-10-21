"""
Fazle Core — Payment Module
Thin re-export of payment_workflow for backwards compatibility.
All actual logic lives in modules/fazle_payment_workflow/__init__.py.
"""
from modules.fazle_payment_workflow import (
    create_escort_payment_draft,
    create_advance_request_draft,
    finalize_payment,
    is_advance_request,
    ADVANCE_KEYWORDS,
    DEFAULT_DAILY_RATE,
)

__all__ = [
    "create_escort_payment_draft",
    "create_advance_request_draft",
    "finalize_payment",
    "is_advance_request",
    "ADVANCE_KEYWORDS",
    "DEFAULT_DAILY_RATE",
]
