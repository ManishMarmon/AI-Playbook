"""
Works out WHICH SIDE made a tracked change — Marmon(-subsidiary) or the
counterparty — from the author names Word recorded in the redline markup.

Why it matters (Jeff, 2026-08-31): "comparing only the initial and final
contract versions made it difficult to determine which party introduced a
specific language change." Tracked changes carry a per-edit author, so for
redlined documents that ambiguity is resolvable — and a rule built from
Marmon's own edits is a genuine preferred position, while one built from the
counterparty's edits is the opposite (what they pushed back with).

Everything here is derived from data already stored: the author names in
files.tracked_change_authors, and each request's own handling-attorney email,
law-firm name and counterparty name. No LLM, no network.

Two problems the live data forced this module to solve, both found by
surveying all 2,467 scanned NDA redline files:

  1. The SAME person appears under different name formats — "Wilk, Michele"
     (1,689 files) and "Michele Wilk" (256 files) are one attorney. Without
     normalization, the single most prolific editor is double-counted and any
     per-author rollup is wrong.
  2. Some authors are not people: the literal string "Author" (51 files) and
     empty strings come from Word's privacy setting stripping the name, and
     names like "Eversheds Sutherland" are LAW FIRMS whose side varies by
     request. Both must resolve to "unknown", never be guessed at.
"""

import re

MARMON = "marmon"
COUNTERPARTY = "counterparty"
UNKNOWN = "unknown"

# Word writes these when the document's privacy settings strip author names.
# They are not people and must never be treated as one.
_ANONYMOUS_AUTHORS = {"", "author", "unknown", "user", "windows user", "unattributed"}

# Suffixes/qualifiers that appear on some corporate display names, e.g.
# "Bergener, Karin (US-AVL2-CNTR)". Stripped before comparison so the same
# person with and without a site code still matches.
_PARENTHETICAL = re.compile(r"\([^)]*\)")
_NON_NAME = re.compile(r"[^a-z\s]")


def name_tokens(name: str | None) -> frozenset:
    """Lower-cased word set for a display name, order-independent so
    "Wilk, Michele" and "Michele Wilk" produce the same tokens. Single
    initials are dropped: a middle initial present in one format and absent in
    the other must not prevent a match."""
    if not name:
        return frozenset()
    cleaned = _PARENTHETICAL.sub(" ", name.lower())
    cleaned = _NON_NAME.sub(" ", cleaned)
    return frozenset(t for t in cleaned.split() if len(t) > 1)


def normalize_name(name: str | None) -> str:
    """Stable key for grouping one person's aliases together — the token set,
    sorted, so both name orders collapse to the same key."""
    return " ".join(sorted(name_tokens(name)))


def is_anonymous(name: str | None) -> bool:
    return (name or "").strip().lower() in _ANONYMOUS_AUTHORS


def email_tokens(email: str | None) -> frozenset:
    """Name tokens from an email's local part — michele.wilk@marmon.com gives
    {michele, wilk}, which is directly comparable to a display name."""
    if not email or "@" not in email:
        return frozenset()
    local = email.split("@", 1)[0]
    return frozenset(t for t in re.split(r"[._\-+0-9]+", local.lower()) if len(t) > 1)


def _overlaps(a: frozenset, b: frozenset) -> bool:
    """A shared surname-or-given-name token is enough. Requiring BOTH tokens
    would miss real matches (display name "Wilk, Michele" vs email
    m.wilk@..., which only carries the surname), and requiring only a
    substring would over-match common words."""
    return bool(a and b and (a & b))


def classify_author(author: str | None, request: dict,
                    marmon_roster: frozenset = frozenset()) -> str:
    """MARMON / COUNTERPARTY / UNKNOWN for one author on one request.

    Order matters: the request's own handling attorney is the strongest
    signal, then a roster of authors already confirmed Marmon-side elsewhere,
    then an organisation-name match against the counterparty. Anything else
    stays UNKNOWN — a wrong side attribution is worse than none, because side
    is what makes a rule a "preferred position" claim."""
    if is_anonymous(author):
        return UNKNOWN

    tokens = name_tokens(author)
    if not tokens:
        return UNKNOWN

    # 1. Matches this request's handling attorney (email or name).
    if _overlaps(tokens, email_tokens(request.get("u_HandlingAttorneyEmail"))):
        return MARMON
    if _overlaps(tokens, name_tokens(request.get("u_HandlingAttorneyName"))):
        return MARMON

    # 2. Known Marmon-side author from any other request (see build_marmon_roster).
    if normalize_name(author) in marmon_roster:
        return MARMON

    # 3. Organisation match: the counterparty company or the OUTSIDE law firm
    #    named on the request. Note a law-firm match is deliberately NOT
    #    treated as Marmon-side — u_LawFirmName can be either party's counsel,
    #    and the survey found firm names appearing as edit authors, so
    #    guessing here would manufacture false preferred-position claims.
    counterparty_tokens = name_tokens(request.get("u_VendorCounterpartyName"))
    if _overlaps(tokens, counterparty_tokens):
        return COUNTERPARTY

    return UNKNOWN


def side_from_filename(file_name: str | None, request: dict) -> str:
    """Secondary signal when tracked-change authorship can't place the editor:
    who the FILENAME says redlined it. Live examples this resolves —
    "...Liberty Packaging - LP REDLINE 2026.08.04.docx" against counterparty
    "Liberty Packaging" (counterparty's redline), and
    "...NDA (marmon redline 8.28.26).docx" (ours).

    Only used to break a tie the author names left open, and only on an
    unambiguous hit: if the filename names both parties as editors, or names
    neither, it returns UNKNOWN rather than picking one."""
    name = (file_name or "").lower()
    if not name:
        return UNKNOWN

    tokens = [t for t in re.split(r"[^a-z]+", name) if t]
    marker_positions = [i for i, t in enumerate(tokens)
                        if t in ("redline", "redlines", "redlined", "revisions", "edits", "markup")]
    if not marker_positions:
        return UNKNOWN

    counterparty_tokens = {t for t in name_tokens(request.get("u_VendorCounterpartyName"))
                           if len(t) > 3}
    business_tokens = {t for t in name_tokens(request.get("u_BusinessUnit")) if len(t) > 3}
    # Initials of a multi-word counterparty ("Liberty Packaging" -> "lp"),
    # because that abbreviation-before-marker form is common in this data.
    ordered_cp = [t for t in re.split(r"[^a-z]+", (request.get("u_VendorCounterpartyName") or "").lower()) if t]
    cp_initials = "".join(t[0] for t in ordered_cp) if len(ordered_cp) > 1 else ""

    # Whose name sits immediately before the markup marker. Looking only at
    # the preceding two tokens is what makes this reliable: virtually every
    # file is NAMED AFTER the counterparty, so their name appearing somewhere
    # in the filename says nothing about who edited it — but the name directly
    # in front of "redline"/"edits" is the editor.
    says_marmon = says_counterparty = False
    for pos in marker_positions:
        for prev in tokens[max(0, pos - 2):pos]:
            if prev == "marmon" or prev in business_tokens:
                says_marmon = True
            if prev in counterparty_tokens or (cp_initials and prev == cp_initials):
                says_counterparty = True

    # Marmon named right before the marker ("marmon redline") is a positive
    # claim that we edited it, and wins outright.
    if says_marmon:
        return MARMON
    # Counterparty attribution is held to a stricter test: our name must not
    # appear anywhere in the filename. Otherwise a plain contract title listing
    # both parties ("Marmon Liberty Packaging redline.docx") would be read as
    # the counterparty's redline purely because their name happens to sit last
    # — an arbitrary guess that could mislabel our own position as theirs.
    if says_counterparty and "marmon" not in tokens and not (business_tokens & set(tokens)):
        return COUNTERPARTY
    return UNKNOWN


def build_marmon_roster(requests_with_authors) -> frozenset:
    """Authors confirmed Marmon-side by matching the handling attorney on at
    least one request, as normalized keys. Applying this across the whole
    population is what lets an attorney be recognised on requests where the
    handling-attorney field is blank — the same person, one alias list."""
    roster = set()
    for request, authors in requests_with_authors:
        attorney = email_tokens(request.get("u_HandlingAttorneyEmail")) | name_tokens(
            request.get("u_HandlingAttorneyName"))
        if not attorney:
            continue
        for author in authors or []:
            if is_anonymous(author):
                continue
            if _overlaps(name_tokens(author), attorney):
                roster.add(normalize_name(author))
    return frozenset(roster)


def summarize_sides(authors_by_side: dict) -> str:
    """One human-readable line for a finding or rule, e.g.
    "Marmon-side edits only" / "both sides edited this clause"."""
    marmon = authors_by_side.get(MARMON) or []
    counter = authors_by_side.get(COUNTERPARTY) or []
    unknown = authors_by_side.get(UNKNOWN) or []
    if marmon and counter:
        return "both sides edited this clause"
    if marmon:
        return "Marmon-side edits only"
    if counter:
        return "counterparty edits only"
    if unknown:
        return "editor's side could not be determined"
    return "no recorded editors"


def group_authors_by_side(authors, request: dict,
                          marmon_roster: frozenset = frozenset()) -> dict:
    """{side: [author, ...]} for a collection of author names, aliases merged
    so one person counted twice under two name formats appears once."""
    out: dict = {MARMON: [], COUNTERPARTY: [], UNKNOWN: []}
    seen: set = set()
    for author in authors or []:
        key = normalize_name(author)
        if key in seen:
            continue
        seen.add(key)
        out[classify_author(author, request, marmon_roster)].append(author)
    return out
