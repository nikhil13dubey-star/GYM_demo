"""
Communications module — admin-only visibility & control over portal emails.

Three responsibilities:
  1. EMAIL_PLAYBOOK — single source of truth describing every email the portal
     can send: trigger, preconditions, rate limits, subject. Lives next to the
     send code so the admin UI can never drift from actual behavior.
  2. CC settings  — DB-managed CC lists per email type (settings collection,
     one doc). Admin edits apply to the very next send; no deploy needed.
     The From address is env-managed and has NO write path here (by design —
     changing it would break the SendGrid verified sender).
  3. Communications log — one doc per send attempt (sent or failed) in the
     `communications` collection, written right after each SendGrid call.

NOTE: the existing per-lead `email_log` (rate-limit quota) is intentionally
untouched — it counts attempts BEFORE the send; this log records outcomes.
"""
import re
from datetime import datetime
from typing import Dict, List, Optional

from mongodb import MongoDB
from email_service import email_service, PAYMENT_CONFIRMATION_CC, FROM_EMAIL, FROM_NAME

SETTINGS_DOC_ID = "email_cc"
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

# ---------------------------------------------------------------------------
# EMAIL PLAYBOOK — keys match the email_type strings already used in
# check_and_record_email_send / lead.email_log.
# ---------------------------------------------------------------------------
EMAIL_PLAYBOOK: Dict[str, Dict] = {
    "LEAD_ACKNOWLEDGEMENT": {
        "label": "Lead Acknowledgement",
        "trigger": "auto",
        "trigger_detail": "Fires automatically the moment a customer submits the gym enquiry form on the website.",
        "conditions": [
            "Customer provided an email address on the enquiry form",
        ],
        "rate_limit": "One per form submission (sent once, at lead creation)",
        "subject": "Thank You for Your Interest - Habit Health Gym Package",
        "purpose": "Confirms to the customer that their enquiry was received and the team will reach out within 24 hours.",
        "sample_args": {"customer_name": "Rahul Sharma", "gym_name": "Cult Fit - Sector 62"},
        "builder": "build_lead_acknowledgement",
    },
    "NO_RESPONSE_FOLLOWUP": {
        "label": "No Response Follow-up",
        "trigger": "manual",
        "trigger_detail": "'No Response' email button in the lead detail view — used when the customer doesn't answer calls.",
        "conditions": [
            "Lead must have an email address",
            "Agent can act only on their own leads; admin on any lead",
        ],
        "rate_limit": "Max 1 of this type per lead per day; 8 emails/lead/day overall",
        "subject": "We Tried Reaching You - Habit Health",
        "purpose": "Asks the customer to call back or reply so the team can assist.",
        "sample_args": {"customer_name": "Rahul Sharma", "gym_name": "Cult Fit - Sector 62"},
        "builder": "build_no_response_followup",
    },
    "PAYMENT_CONFIRMATION": {
        "label": "Payment Confirmation",
        "trigger": "manual",
        "trigger_detail": "'Payment Confirmation' email button in the lead detail view.",
        "conditions": [
            "Payment must already be marked 'Paid' (strict — sending never changes payment status)",
            "Lead must have an email address",
            "Agent can act only on their own leads; admin on any lead",
        ],
        "rate_limit": "Max 1 of this type per lead per day; 8 emails/lead/day overall",
        "subject": "Payment Received - Habit Health Gym Package",
        "purpose": "Receipt to the customer: transaction ID, gym, plan, and amount paid.",
        "sample_args": {"customer_name": "Rahul Sharma", "gym_name": "Cult Fit - Sector 62",
                        "amount": 5925, "transaction_id": "GYM_20260710_0001", "plan_name": "3 Months"},
        "builder": "build_payment_confirmation",
    },
    "INTERIM_INFO": {
        "label": "Interim Info",
        "trigger": "manual",
        "trigger_detail": "'Send Interim Info' button in the lead detail view — transaction details while the tax invoice is prepared.",
        "conditions": [
            "Payment must be 'Paid'",
            "Lead must have an email address",
            "Agent can act only on their own leads; admin on any lead",
        ],
        "rate_limit": "Max 1 of this type per lead per day; 8 emails/lead/day overall",
        "subject": "Your Gym Subscription Confirmation - Habit Health",
        "purpose": "Shares name, transaction number, amount and plan; notes the final tax invoice follows in 7-10 working days.",
        "sample_args": {"customer_name": "Rahul Sharma", "reference_id": "PAY-REF-8842",
                        "transaction_amount": 5925, "plan_name": "3 Months"},
        "builder": "build_interim_info",
    },
    "NO_INTEREST_CLOSURE": {
        "label": "No Interest Closure",
        "trigger": "manual",
        "trigger_detail": "'Closure' email button in the lead detail view — closing unresponsive leads.",
        "conditions": [
            "Lead must have an email address",
            "Agent can act only on their own leads; admin on any lead",
            "On success the lead status is automatically set to 'Closed'",
        ],
        "rate_limit": "Max 1 of this type per lead per day; 8 emails/lead/day overall",
        "subject": "Your Gym Package Request - Habit Health",
        "purpose": "Tells the customer the request is closed after multiple contact attempts, with a way to get back in touch.",
        "sample_args": {"customer_name": "Rahul Sharma", "gym_name": "Cult Fit - Sector 62"},
        "builder": "build_no_interest_closure",
    },
}

EMAIL_TYPES = list(EMAIL_PLAYBOOK.keys())


# ---------------------------------------------------------------------------
# CC SETTINGS (settings collection, single doc)
# ---------------------------------------------------------------------------
async def seed_email_settings() -> None:
    """
    Create the CC settings doc on startup if it doesn't exist.
    Seeds PAYMENT_CONFIRMATION with the historical hardcoded list; every other
    type starts with no CC. Never overwrites an existing doc (admin edits win).
    """
    existing = await MongoDB.db.settings.find_one({"_id": SETTINGS_DOC_ID})
    if existing:
        # Backfill any email type added after the doc was first created
        missing = {f"cc_lists.{t}": [] for t in EMAIL_TYPES if t not in existing.get("cc_lists", {})}
        if missing:
            await MongoDB.db.settings.update_one({"_id": SETTINGS_DOC_ID}, {"$set": missing})
        return
    await MongoDB.db.settings.insert_one({
        "_id": SETTINGS_DOC_ID,
        "cc_lists": {t: (list(PAYMENT_CONFIRMATION_CC) if t == "PAYMENT_CONFIRMATION" else [])
                     for t in EMAIL_TYPES},
        "updated_by": "system (seed)",
        "updated_at": datetime.utcnow(),
    })
    print("[Communications] [OK] Email CC settings seeded")


async def get_cc_list(email_type: str) -> List[str]:
    """CC list for one email type, read fresh so admin edits apply instantly."""
    doc = await MongoDB.db.settings.find_one({"_id": SETTINGS_DOC_ID}, {f"cc_lists.{email_type}": 1})
    return (doc or {}).get("cc_lists", {}).get(email_type, [])


async def get_all_cc_lists() -> Dict[str, List[str]]:
    doc = await MongoDB.db.settings.find_one({"_id": SETTINGS_DOC_ID})
    lists = (doc or {}).get("cc_lists", {})
    return {t: lists.get(t, []) for t in EMAIL_TYPES}


def validate_cc_emails(emails: List[str]) -> List[str]:
    """
    Validate + canonicalize a CC list. Returns the cleaned list.
    Raises ValueError naming the first invalid address.
    """
    cleaned, seen = [], set()
    for raw in emails:
        addr = (raw or "").strip()
        if not addr:
            continue
        if not EMAIL_REGEX.match(addr):
            raise ValueError(f"Invalid email address: {addr}")
        key = addr.lower()
        if key in seen:
            continue  # silently drop duplicates (case-insensitive)
        seen.add(key)
        cleaned.append(addr)
    if len(cleaned) > 10:
        raise ValueError("Maximum 10 CC addresses per email type.")
    return cleaned


async def set_cc_list(email_type: str, emails: List[str], updated_by: str) -> List[str]:
    """Replace one email type's CC list. Raises ValueError on bad input."""
    if email_type not in EMAIL_TYPES:
        raise ValueError(f"Unknown email type: {email_type}")
    cleaned = validate_cc_emails(emails)
    await MongoDB.db.settings.update_one(
        {"_id": SETTINGS_DOC_ID},
        {"$set": {
            f"cc_lists.{email_type}": cleaned,
            f"cc_meta.{email_type}": {"updated_by": updated_by, "updated_at": datetime.utcnow()},
        }},
        upsert=True,
    )
    return cleaned


# ---------------------------------------------------------------------------
# COMMUNICATIONS LOG
# ---------------------------------------------------------------------------
async def log_communication(lead: dict, email_type: str, trigger: str,
                            sent_by: str, result: dict) -> None:
    """
    Record one send attempt. `result` is the dict returned by email_service
    (carries the actual from/to/cc/subject envelope + success/error).
    Logging must never break the send flow — failures are printed, not raised.
    """
    try:
        await MongoDB.db.communications.insert_one({
            "sent_at": datetime.utcnow(),
            "lead_id": lead.get("lead_id"),
            "lead_name": lead.get("full_name", ""),
            "email_type": email_type,
            "trigger": trigger,                       # 'auto' | 'manual'
            "sent_by": sent_by,                        # user email or 'system'
            "from": result.get("from", FROM_EMAIL),
            "to": result.get("to", lead.get("email")),
            "cc": result.get("cc", []),
            "subject": result.get("subject", ""),
            "status": "sent" if result.get("success") else "failed",
            "error": None if result.get("success") else result.get("error"),
        })
    except Exception as e:
        print(f"[Communications] [WARNING] Failed to log {email_type} for {lead.get('lead_id')}: {e}")


def render_preview(email_type: str) -> dict:
    """
    Render the REAL template with sample data for the admin preview modal.
    Uses the same build_* functions the send paths use, so preview == reality.
    """
    entry = EMAIL_PLAYBOOK.get(email_type)
    if not entry:
        raise ValueError(f"Unknown email type: {email_type}")
    builder = getattr(email_service, entry["builder"])
    subject, html = builder(**entry["sample_args"])
    return {"email_type": email_type, "subject": subject, "html": html,
            "sample_note": "Rendered with sample data — actual emails use the lead's real details."}


def playbook_public(cc_lists: Dict[str, List[str]], cc_meta: Optional[Dict] = None) -> list:
    """Playbook entries merged with live CC lists, in a UI-friendly shape."""
    out = []
    for t, e in EMAIL_PLAYBOOK.items():
        out.append({
            "email_type": t,
            "label": e["label"],
            "trigger": e["trigger"],
            "trigger_detail": e["trigger_detail"],
            "conditions": e["conditions"],
            "rate_limit": e["rate_limit"],
            "subject": e["subject"],
            "purpose": e["purpose"],
            "from_email": FROM_EMAIL,
            "from_name": FROM_NAME,
            "cc": cc_lists.get(t, []),
            "cc_meta": (cc_meta or {}).get(t),
        })
    return out
