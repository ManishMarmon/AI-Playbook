"""
Builds the methodology block that goes into a generated playbook's manifest
entry and is rendered as a preface page in the Word document (Jeff, 2026-08-31:
"provenance metadata per rule" plus a stated sample definition, so a reviewing
attorney can judge how much weight the rules deserve).

Everything here is DERIVED from the actual pipeline artefacts — the selection
funnel, the provenance diff records, and the tagging output. Nothing is
hardcoded prose about the data, because hardcoded prose drifts out of step with
reality: an earlier version of this pipeline would have printed Jeff's
"intermediates were missing, so these are agreed outcomes" caveat on a run where
every single rule came from a real redline, which would have understated the
evidence. The caveats are computed, so they can only ever describe what
actually happened.

Deterministic, free, no LLM, no network.
"""

from collections import Counter

import provenance

# Human-facing wording for each funnel stage, in order. Keys are the count keys
# report_redline_funnel.py writes.
FUNNEL_STEPS = [
    ("total_requests", "requests of this type and jurisdiction in CobbleStone"),
    ("with_docx", "with at least one Word (.docx) document"),
    ("scanned_requests", "scanned for Word tracked changes"),
    ("with_tracked_changes_redline", "with at least one tracked-changes redline"),
    ("mutual_with_redline", "classified as mutual by the directionality classifier"),
    ("subset_size", "analysed in this playbook"),
]


def _fmt_date(value) -> str | None:
    if value is None:
        return None
    text = str(value)[:10]
    parts = text.split("-")
    if len(parts) != 3:
        return text
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    try:
        return f"{int(parts[2])} {months[int(parts[1]) - 1]} {parts[0]}"
    except (ValueError, IndexError):
        return text


def date_range_label(dates: list) -> str | None:
    """'23 Jun 2026 - 28 Aug 2026', or a single date when they coincide."""
    usable = sorted(str(d)[:10] for d in dates if d)
    if not usable:
        return None
    lo, hi = _fmt_date(usable[0]), _fmt_date(usable[-1])
    return lo if lo == hi else f"{lo} - {hi}"


def _counted(counter: Counter, labeller=None) -> list:
    """Counter -> [{'label','count'}], highest first, ties broken by label so
    the rendered document is byte-stable across runs."""
    items = sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
    return [{"label": (labeller(k) if labeller else str(k)), "count": v} for k, v in items]


def build_caveats(funnel_counts: dict, diff_records: list, position_sides: Counter,
                   verify_failed: int, tagging_failed_ids: list,
                   contributing_request_ids: set | None = None) -> list:
    """Only the caveats that this run's data actually warrants.

    Each is phrased so a reviewer knows what it changes about the rules'
    weight, not merely that a number exists."""
    caveats = []
    counts = funnel_counts or {}

    # 1. Coverage of the classifier. This is the biggest honest limitation:
    # the mutual pool is what has been CLASSIFIED mutual, not every mutual NDA.
    redline_having = counts.get("with_tracked_changes_redline")
    classified = counts.get("mutual_with_redline")
    unclassified = counts.get("unclassified_with_redline")
    if redline_having and unclassified:
        caveats.append(
            f"Directionality (mutual vs one-way) has been classified for "
            f"{redline_having - unclassified:,} of the {redline_having:,} requests that carry a "
            f"Word redline; {unclassified:,} are not yet classified. The sample is therefore the "
            f"most recent contracts among the {classified:,} confirmed mutual ones, not the most "
            f"recent of all mutual NDAs that exist. Classification is ongoing and the sample can "
            f"be widened without redoing any of this analysis."
        )
    elif redline_having and classified:
        # The positive counterpart, stated for the same reason the
        # agreed-outcome caveat has one: once coverage is complete, printing a
        # "sample may be incomplete" hedge would understate the evidence, and
        # printing nothing would leave the reader unsure whether coverage was
        # checked at all.
        caveats.append(
            f"Every one of the {redline_having:,} requests carrying a Word redline has been "
            f"classified as mutual or one-way, and all {classified:,} mutual ones are included "
            f"here. This is the complete population of US mutual NDAs with a negotiated redline, "
            f"not a sample of it."
        )

    # 2. Agreed-outcome fallback — Jeff's caveat, stated ONLY if it applies.
    basis_counter = Counter(r.get("comparison_basis") for r in diff_records)
    fallback = basis_counter.get(provenance.INITIAL_VS_FINAL, 0)
    total = sum(basis_counter.values())
    if fallback:
        caveats.append(
            f"{fallback} of {total} contracts had no usable redline markup, so their rules were "
            f"derived by comparing the initial draft with the final executed version. Those blend "
            f"both parties' edits and are labelled an agreed outcome, not a Marmon preferred "
            f"position."
        )
    elif total:
        caveats.append(
            f"Every one of the {total} contracts analysed had usable tracked-change markup, so no "
            f"rule here rests on an initial-versus-final comparison. Each rule's edits are "
            f"attributable to one party's markup in one round of negotiation."
        )

    # 3. Non-first rounds — disclosed because a later round has already
    # absorbed some of the other side's changes.
    later_round = [r for r in diff_records
                   if any("rather than a first redline" in n for n in (r.get("notes") or []))]
    if later_round:
        caveats.append(
            f"For {len(later_round)} contract(s) the first redline contained only formatting "
            f"changes, so a later round was used. Those edits show that party's position at that "
            f"round of negotiation, which may already reflect some compromise, rather than its "
            f"opening ask."
        )

    # 4. Unattributed sides.
    unknown = position_sides.get(provenance.SIDE_UNKNOWN, 0)
    if unknown:
        caveats.append(
            f"{unknown} finding(s) could not be attributed to one side — either both parties "
            f"edited the same passage, or Word's privacy settings stripped the author name. Those "
            f"are labelled \"side unconfirmed\" rather than assumed to be ours."
        )

    # 5. Contracts that contributed nothing. "100 contracts analysed" reads as
    # 100 contracts' worth of evidence; where some yielded only low-significance
    # edits, the effective sample is smaller and the reader should know.
    if contributing_request_ids is not None:
        analysed = {r.get("request_id") for r in diff_records if (r.get("edits") or [])}
        silent = sorted(rid for rid in analysed if rid not in contributing_request_ids)
        if silent:
            caveats.append(
                f"{len(silent)} of the {len(analysed)} contracts analysed produced no finding of "
                f"high or medium significance — their tracked changes were minor or "
                f"administrative — so the rules rest on {len(analysed) - len(silent)} contracts' "
                f"evidence rather than all {len(analysed)}"
                + (f" (requests {', '.join(str(i) for i in silent)})." if len(silent) <= 6 else ".")
            )

    # 6. Machine-checking gaps, so nothing looks more verified than it is.
    if verify_failed:
        caveats.append(
            f"{verify_failed} finding(s) could not complete the second-pass accuracy check and "
            f"were excluded from the evidence counts rather than counted as verified."
        )
    if tagging_failed_ids:
        caveats.append(
            f"{len(tagging_failed_ids)} contract(s) failed the tagging step and contributed no "
            f"findings: {', '.join(str(i) for i in tagging_failed_ids)}."
        )

    return caveats


def build_methodology(*, funnel: dict, diff_records: list, findings: dict,
                      evidence_threshold_pct: float | None = None,
                      tag_model: str | None = None,
                      classifier_model: str | None = None) -> dict:
    """Assembles the block. `findings` is the tagger's output payload (either
    the whole file or its "result" object)."""
    counts = (funnel or {}).get("counts", {}) or {}
    scope = (funnel or {}).get("scope", {}) or {}

    # `--findings` means different shapes to different scripts in this pipeline:
    # synthesis takes the flat confirmed ARRAY, this takes the tagger's whole
    # payload (it needs the flagged and verify-failure counts too, which the
    # array does not carry). Passing the array here would otherwise blow up with
    # an opaque AttributeError several frames deep.
    if isinstance(findings, list):
        raise TypeError(
            "build_methodology needs the tagger's full payload ({'result': {...}}), not the "
            "flat confirmed-findings array. The array has no flagged/verification counts, so a "
            "methodology page built from it would understate what was checked. Pass the file "
            "azure_clause_tagging.py --out wrote (or export_clause_findings.py's output)."
        )
    result = findings.get("result", findings) if findings else {}

    confirmed = result.get("confirmed") or []
    flagged = result.get("flagged") or []
    all_findings = confirmed + flagged

    position_sides = Counter(f.get("position_side") or provenance.SIDE_UNKNOWN
                             for f in all_findings)
    basis_counter = Counter(r.get("comparison_basis") for r in diff_records)

    funnel_steps = [
        {"label": label, "count": counts[key]}
        for key, label in FUNNEL_STEPS if counts.get(key) is not None
    ]

    # Dates come from the documents actually analysed, not from the request
    # records, so the range describes the negotiated language's vintage.
    #
    # The range ALONE can mislead, and does on live data: one 2026 request
    # (#20095) carries a redline authored in March 2025, which stretches the
    # stated span to 17 months when 98 of 99 dated contracts have all their
    # edits inside 2026. So the per-year spread is reported alongside it — a
    # single old outlier must not make a recent sample look broad.
    dates = []
    year_of_request = {}
    for r in diff_records:
        request_dates = [d for e in (r.get("edits") or []) for d in (e.get("edit_dates") or [])]
        dates.extend(request_dates)
        if request_dates:
            year_of_request[r.get("request_id")] = min(request_dates)[:4]
    edit_years = _counted(Counter(year_of_request.values()))

    return {
        "sample": {
            "scope": scope,
            "funnel": funnel_steps,
            "subsetSize": counts.get("subset_size"),
            "dateRange": date_range_label(dates),
            # Per-year count of CONTRACTS by their earliest edit, so the reader
            # sees where the sample actually sits rather than only its extremes.
            "editYears": edit_years,
            "byYear": (funnel or {}).get("by_year", {}).get("mutual_subset"),
        },
        "comparisonBasis": _counted(basis_counter, provenance.label),
        "positionSides": _counted(position_sides, lambda s: provenance.side_label(s)),
        "verification": {
            "requestsTagged": result.get("requestsProcessed"),
            "requestsTotal": result.get("requestsTotal"),
            "confirmed": len(confirmed),
            "flagged": len(flagged),
            "verifyFailed": result.get("verificationFailedCount") or 0,
        },
        "evidenceThresholdPct": evidence_threshold_pct,
        "models": {k: v for k, v in
                   {"clauseTagging": tag_model, "directionality": classifier_model}.items() if v},
        "caveats": build_caveats(
            counts, diff_records, position_sides,
            result.get("verificationFailedCount") or 0,
            result.get("failedRequestIds") or [],
            contributing_request_ids={f.get("request_id") for f in all_findings},
        ),
    }
