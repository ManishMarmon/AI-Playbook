"""
CobbleStone (MPact) Requests API — ported from contractAbstraction's
app_utils.py (retry/token logic) and the original utils/request_api.py
(pagination pattern), trimmed to only what the Redline Discovery Engine
needs: list requests, list files per request. No file download — the
`TextExtract` field already returned by ContractFilesExt/Get is enough
for the v1 heuristic classifier.

Field names below are verified against a live sample (100 requests / 75
files), not assumed from older code — see AIPlaybook session notes.
"""

import json
import time
import logging

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


def fetch_all_requests(token: str, batch_size: int = 100, limit: int | None = None) -> list[dict]:
    """
    Cursor-paginate every CobbleStone request by RequestID. `Length` in the
    payload is a hint only — live testing showed CobbleStone caps a page at
    100 regardless of what's requested, so we advance the cursor to the max
    RequestID seen and keep going until a short/empty page comes back.
    """
    all_requests: list[dict] = []
    after_id = 0
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
            break
        all_requests.extend(batch)
        after_id = max(r.get("RequestID", after_id) for r in batch)
        if limit and len(all_requests) >= limit:
            return all_requests[:limit]
        if len(batch) < batch_size:
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
