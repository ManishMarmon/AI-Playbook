"""
Plain-text extraction from email attachments (.msg / .eml) — the one file
type CobbleStone's own OCR/TextExtract does NOT cover (confirmed live: both
real .msg samples in pipeline_snapshot.json come back with TextExtract==""),
unlike .docx/.pdf/.xlsx/.xls, which already arrive with real extracted text.

.msg (Outlook's OLE-compound format) needs the `extract_msg` library — it's
not a text format, so there's no stdlib option. .eml (standard MIME) is
parsed with the stdlib `email` module instead; no extra dependency needed for
that half. Both take raw bytes directly (see request_api.download_file()),
no temp file required.

Never raises: a file that fails to parse just yields no text, the same
"skip rather than crash" convention already used by _looks_like_template()/
review_selection.py's other conservative fallbacks.
"""

import email
import logging

import extract_msg

logger = logging.getLogger(__name__)


def _extract_eml_text(raw_bytes: bytes) -> str:
    msg = email.message_from_bytes(raw_bytes)
    parts = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                payload = part.get_payload(decode=True)
                if payload:
                    parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            parts.append(payload.decode(msg.get_content_charset() or "utf-8", errors="replace"))
    subject = msg.get("Subject") or ""
    return f"Subject: {subject}\n\n{''.join(parts)}".strip()


def _extract_msg_text(raw_bytes: bytes) -> str:
    m = extract_msg.openMsg(raw_bytes)
    try:
        subject = m.subject or ""
        body = m.body or ""
        return f"Subject: {subject}\n\n{body}".strip()
    finally:
        m.close()


def extract_email_text(raw_bytes: bytes, file_type: str) -> str:
    """file_type is CobbleStone's own FileType field, e.g. ".msg" or ".eml"
    (case-insensitive). Returns "" (never raises) if the type is unsupported
    or parsing fails — same "no signal available" convention as
    request_api.download_file()."""
    ext = (file_type or "").lower()
    try:
        if ext == ".msg":
            return _extract_msg_text(raw_bytes)
        if ext == ".eml":
            return _extract_eml_text(raw_bytes)
    except Exception as e:
        logger.warning(f"extract_email_text failed for {ext} file: {e}")
        return ""
    return ""
