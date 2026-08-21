"""
CobbleStone (MPact) Requests API — ported from contractAbstraction's
app_utils.py (retry/token logic) and the original utils/request_api.py
(pagination pattern), trimmed to only what the Redline Discovery Engine
needs: list requests, list files per request, and (for files the text
heuristic can't classify) download the actual file bytes for structural
inspection — see structure_check.py.

Field names below are verified against a live sample (100 requests / 75
files), not assumed from older code — see AIPlaybook session notes.
"""

import email
import json
import time
import logging
from pathlib import Path

import requests

import config

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF_BASE_SECONDS = 1.5
_RETRYABLE_EXCEPTIONS = (requests.exceptions.Timeout, requests.exceptions.ConnectionError)

_TOKEN_CACHE = {"token": None, "expires_at": 0.0}
_TOKEN_REFRESH_BUFFER_SECONDS = 60
_TOKEN_FALLBACK_TTL_SECONDS = 300


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            return requests.request(method, url, **kwargs)
        except _RETRYABLE_EXCEPTIONS as e:
            last_exc = e
            if attempt < _MAX_RETRIES - 1:
                wait = _BACKOFF_BASE_SECONDS * (2 ** attempt)
                logger.warning(f"Request to {url} failed ({e}) — retrying in {wait:.1f}s")
                time.sleep(wait)
    raise last_exc


def get_bearer_token(force_refresh: bool = False) -> str:
    now = time.time()
    if not force_refresh and _TOKEN_CACHE["token"] and now < _TOKEN_CACHE["expires_at"]:
        return _TOKEN_CACHE["token"]

    payload = (
        f"grant_type=client_credentials"
        f"&client_id={config.MPACT_CLIENT_ID}"
        f"&client_secret={config.MPACT_CLIENT_SECRET}"
    )
    resp = _request_with_retry(
        "POST", config.MPACT_OAUTH_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=payload, timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    expires_in = data.get("expires_in", _TOKEN_FALLBACK_TTL_SECONDS)

    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["expires_at"] = now + max(expires_in - _TOKEN_REFRESH_BUFFER_SECONDS, 30)
    return token


def _headers(token: str) -> dict:
    return {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}


def iter_request_pages(token: str, batch_size: int = 100, limit: int | None = None,
                        start_after_id: int = 0):
    """
    Cursor-paginate every CobbleStone request by RequestID, yielding ONE PAGE
    AT A TIME. `Length` in the payload is a hint only — live testing showed
    CobbleStone caps a page at 100 regardless of what's requested, so we
    advance the cursor to the max RequestID seen and keep going until a
    short/empty page comes back.

    `start_after_id` lets a resumable backfill/sync continue from the last
    RequestID already persisted instead of always starting from 0.

    Yielding per page (rather than accumulating everything and returning once)
    matters at full-population scale: 19,701 requests is ~197 pages, and
    listing them all up front took ~25min before a single row could be
    persisted — so an interrupted run threw away all of that work. A consumer
    that upserts each page as it arrives makes progress durable from the first
    page on.
    """
    yielded = 0
    after_id = start_after_id
    while True:
        payload = json.dumps({
            # A non-empty Fields list — even with an unrelated field name — makes
            # CobbleStone return the FULL ~140-field record (all u_* custom fields
            # included, e.g. u_RequestProcessStatus, u_HandlingAttorney,
            # u_Requestor). An empty list returns only ~25 base fields. Verified
            # live; not documented anywhere.
            "Fields": ["RequestID"],
            "Clause": {
                "condition": "AND",
                "rules": [{"id": "RequestID", "field": "RequestID", "type": "int",
                           "input": "null", "operator": "greater", "value": after_id}],
                "GroupByTag": [], "StartIndex": 0, "Length": batch_size,
            }
        })
        resp = _request_with_retry("POST", config.REQUEST_GET_URL,
                                    headers=_headers(token), data=payload, timeout=60)
        resp.raise_for_status()
        batch = resp.json() or []
        if not batch:
            return
        after_id = max(r.get("RequestID", after_id) for r in batch)
        if limit is not None and yielded + len(batch) >= limit:
            yield batch[:limit - yielded]
            return
        yielded += len(batch)
        yield batch
        if len(batch) < min(batch_size, 100):
            return


def fetch_all_requests(token: str, batch_size: int = 100, limit: int | None = None,
                        start_after_id: int = 0) -> list[dict]:
    """Eager wrapper around iter_request_pages — returns every request in one
    list. Fine for bounded fetches; prefer iter_request_pages when persisting
    incrementally at full-population scale."""
    all_requests: list[dict] = []
    for page in iter_request_pages(token, batch_size=batch_size, limit=limit,
                                    start_after_id=start_after_id):
        all_requests.extend(page)
    return all_requests


def fetch_requests_updated_since(token: str, since, batch_size: int = 100) -> list[dict]:
    """
    Requests whose DateUpdated is after `since` (a datetime) — the
    incremental-sync path for catching metadata changes on requests that
    already exist locally, as opposed to fetch_all_requests's RequestID
    cursor, which only ever finds brand-new requests.

    Uses the same generic Clause/rules query shape as fetch_all_requests,
    just filtering on DateUpdated instead of RequestID — unverified against
    the live API until the incremental sync's first real run; if CobbleStone
    doesn't support a "greater" comparison on this field the same way, this
    will need to fall back to re-checking all currently-active requests
    instead (see sync_updates.py).
    """
    since_str = since.strftime("%Y-%m-%dT%H:%M:%S")
    all_requests: list[dict] = []
    start_index = 0
    while True:
        payload = json.dumps({
            "Fields": ["RequestID"],
            "Clause": {
                "condition": "AND",
                "rules": [{"id": "DateUpdated", "field": "DateUpdated", "type": "date",
                           "input": "null", "operator": "greater", "value": since_str}],
                "GroupByTag": [], "StartIndex": start_index, "Length": batch_size,
            }
        })
        resp = _request_with_retry("POST", config.REQUEST_GET_URL,
                                    headers=_headers(token), data=payload, timeout=60)
        resp.raise_for_status()
        batch = resp.json() or []
        if not batch:
            break
        all_requests.extend(batch)
        start_index += len(batch)
        if len(batch) < min(batch_size, 100):
            break
    return all_requests


def fetch_request_file_list(request_id: int, token: str) -> list[dict]:
    """Raw (undeleted) file records attached to one request, including
    the CobbleStone-provided `TextExtract` field."""
    payload = json.dumps({
        "Fields": [],
        "Clause": {
            "condition": "AND",
            "rules": [
                {"id": "RequestID", "field": "RequestID", "type": "int",
                 "input": "null", "operator": "equal", "value": request_id},
                {"id": "IsDeleted", "field": "IsDeleted", "type": "int",
                 "input": "null", "operator": "equal", "value": "0"},
            ],
            "GroupByTag": [], "StartIndex": 0, "Length": 1000,
        }
    })
    resp = _request_with_retry("POST", config.REQUEST_FILE_GET_URL,
                                headers=_headers(token), data=payload, timeout=30)
    resp.raise_for_status()
    return resp.json() or []


def fetch_pipeline_data(token: str, limit: int | None = None) -> dict:
    """
    Fetch every request plus its file list once. `run_discovery.py` and
    `run_pairing.py` each independently call `fetch_all_requests` +
    `fetch_request_file_list` per request — running both back-to-back (the
    normal pipeline invocation) doubled every API call for no reason, since
    both scripts want the identical data. Callers that want to reuse a single
    fetch across both scripts should go through this + a saved snapshot
    (see save_pipeline_snapshot/load_pipeline_snapshot) instead.
    """
    requests_ = fetch_all_requests(token, limit=limit)
    files_by_request = {
        req.get("RequestID"): fetch_request_file_list(req.get("RequestID"), token)
        for req in requests_
    }
    return {"requests": requests_, "files_by_request": files_by_request}


def save_pipeline_snapshot(data: dict, path) -> None:
    """Writes fetch_pipeline_data's result to disk. JSON object keys must be
    strings, so files_by_request's int RequestID keys are stringified here and
    restored to int in load_pipeline_snapshot."""
    payload = {
        "requests": data["requests"],
        "files_by_request": {str(k): v for k, v in data["files_by_request"].items()},
    }
    Path(path).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def load_pipeline_snapshot(path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        "requests": payload["requests"],
        "files_by_request": {int(k): v for k, v in payload["files_by_request"].items()},
    }


def download_file(file_id: int, token: str) -> bytes | None:
    """
    Raw bytes of one file's current version, via the Files/ContractFilesEXt/
    Download endpoint. The response is multipart/mixed: one part is the file
    itself (application/octet-stream), the other is a redundant metadata JSON
    blob we already have from fetch_request_file_list — we only want the
    former. Returns None (never raises) on any download/parse problem; a
    missing file body just means "no structural signal available", not a
    fatal error for the caller.
    """
    payload = json.dumps({
        "Fields": [],
        "Clause": {
            "condition": "AND",
            "rules": [{"id": "ID", "field": "ID", "type": "int",
                       "input": "null", "operator": "equal", "value": str(file_id)}],
            "valid": True,
        }
    })
    try:
        resp = _request_with_retry("POST", config.FILE_DOWNLOAD_URL,
                                    headers=_headers(token), data=payload, timeout=60)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.warning(f"download_file({file_id}) failed: {e}")
        return None

    content_type = resp.headers.get("Content-Type", "")
    if "multipart" not in content_type.lower():
        logger.warning(f"download_file({file_id}): expected multipart response, got {content_type!r}")
        return None

    try:
        # requests doesn't parse multipart responses for us — reuse the stdlib
        # email parser by synthesizing the header block it expects.
        raw_message = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + resp.content
        msg = email.message_from_bytes(raw_message)
        for part in msg.walk():
            if part.get_content_type() == "application/octet-stream":
                return part.get_payload(decode=True)
    except Exception as e:
        logger.warning(f"download_file({file_id}): failed to parse multipart response: {e}")
        return None

    logger.warning(f"download_file({file_id}): no application/octet-stream part found in response")
    return None
