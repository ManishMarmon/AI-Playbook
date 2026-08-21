import { useEffect, useMemo, useState } from "react";
import { ShieldCheck, ShieldAlert, AlertTriangle } from "lucide-react";
import { useJsonResource } from "../hooks/useJsonResource";
import { ResourceStatus } from "../components/ResourceStatus";
import { StatTile } from "../components/StatTile";
import { Chip, type ChipTone } from "../components/Chip";

type Verification = { accurate: boolean; issue: string; corrected_status?: string };

type RuleResult = {
  request_id: number;
  request_title?: string | null;
  party_a?: string | null;
  party_b?: string | null;
  playbook_id?: string | null;
  playbook_label?: string | null;
  rule_id: string;
  title?: string | null;
  category?: string | null;
  priority?: string | null;
  applies_to?: string | null;
  status: "satisfied" | "violation" | "not_applicable" | "not_found";
  met_at?: string;
  matched_clause_text?: string;
  matched_location?: string;
  triggered_flags?: string[];
  explanation?: string;
  confidence?: "high" | "medium" | "low";
  suggested_language?: string | null;
  suggested_language_source_tag?: string | null;
  verification?: Verification | null;
};

type Skipped = {
  request_id: number;
  reason: string;
  business_sector?: string | null;
  contract_type?: string | null;
};

type GoldenRulesData = {
  violations: RuleResult[];
  flaggedInaccurate: RuleResult[];
  satisfied: RuleResult[];
  notApplicableOrNotFound: RuleResult[];
  skipped: Skipped[];
  requestsReviewed: number;
  requestsSubmitted: number;
  requestsInScope: number;
  requestsSkipped: number;
  requestsTotal: number;
  requestsFailed?: number;
  verificationFailedCount?: number;
};

// MUST PRESS first — the playbook's own escalation order, so the most negotiable
// risk sorts to the top rather than being buried by whatever order rules were
// evaluated in.
const PRIORITY_ORDER = ["MUST PRESS", "PRESS", "MANAGE", "ACCEPT+NOTE"];

const PRIORITY_TONE: Record<string, ChipTone | undefined> = {
  "MUST PRESS": "bad",
  PRESS: "warn",
  MANAGE: "info",
  "ACCEPT+NOTE": undefined,
};

const PAGE_SIZE = 20;

function isGoldenRulesData(data: unknown): data is GoldenRulesData {
  if (!data || typeof data !== "object") return false;
  const d = data as Record<string, unknown>;
  return (
    Array.isArray(d.violations) &&
    Array.isArray(d.flaggedInaccurate) &&
    Array.isArray(d.satisfied) &&
    Array.isArray(d.notApplicableOrNotFound)
  );
}

function priorityRank(p?: string | null) {
  const i = PRIORITY_ORDER.indexOf(p ?? "");
  return i === -1 ? PRIORITY_ORDER.length : i;
}

// The playbook explicitly marks some model clause wording as an unvetted draft
// ("do not auto-generate redlines from unsupervised"). That caveat has to be
// visible in the UI, not just present in the data.
function isUnvetted(tag?: string | null) {
  return !!tag && tag.toLowerCase().includes("unvetted");
}

type Tab = "violations" | "flagged" | "satisfied" | "notApplicable";

const TAB_LABEL: Record<Tab, string> = {
  violations: "Violations",
  flagged: "Flagged Inaccurate",
  satisfied: "Satisfied",
  notApplicable: "N/A or Not Found",
};

export default function GoldenRules({ search }: { search: string }) {
  const resource = useJsonResource<GoldenRulesData>("/data/golden_rules_findings.json", isGoldenRulesData);
  const [tab, setTab] = useState<Tab>("violations");
  const [page, setPage] = useState(0);

  const data = resource.status === "ready" ? resource.data : null;

  const rowsForTab = useMemo<RuleResult[]>(() => {
    if (!data) return [];
    if (tab === "violations") return data.violations;
    if (tab === "flagged") return data.flaggedInaccurate;
    if (tab === "satisfied") return data.satisfied;
    return data.notApplicableOrNotFound;
  }, [data, tab]);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    const filtered = term
      ? rowsForTab.filter(
          (r) =>
            r.rule_id?.toLowerCase().includes(term) ||
            r.title?.toLowerCase().includes(term) ||
            r.category?.toLowerCase().includes(term) ||
            r.request_title?.toLowerCase().includes(term) ||
            r.party_b?.toLowerCase().includes(term)
        )
      : rowsForTab;
    return [...filtered].sort(
      (a, b) => priorityRank(a.priority) - priorityRank(b.priority) || a.rule_id.localeCompare(b.rule_id)
    );
  }, [rowsForTab, search]);

  useEffect(() => {
    setPage(0);
  }, [tab, search]);

  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const pageItems = visible.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);

  const mustPressCount = data?.violations.filter((v) => v.priority === "MUST PRESS").length ?? 0;

  return (
    <div>
      <div className="eyebrow">McLegal · Golden Rules (B2)</div>
      <h1>Golden Rules Review</h1>
      <p className="muted" style={{ marginTop: 6 }}>
        Each contract's <strong>full current text</strong> is checked against every rule in its
        applicable playbook — not just the parts that were negotiated. A rule can be violated by
        boilerplate that was accepted as-is and never edited, which a diff-based review would never
        see. High-priority violations are then re-checked by a second, independent AI pass.
      </p>

      {resource.status !== "ready" && (
        <ResourceStatus
          status={resource.status}
          error={resource.error}
          onRetry={resource.refetch}
          loadingLabel="Waiting on the Golden Rules review workflow to produce output..."
          errorLabel="Couldn't load Golden Rules findings."
        />
      )}

      {data && (
        <>
          <div className="grid-4" style={{ marginTop: 24 }}>
            <StatTile label="Violations" value={data.violations.length} tone="bad" />
            <StatTile label="MUST PRESS Violations" value={mustPressCount} tone="bad" />
            <StatTile label="Satisfied" value={data.satisfied.length} tone="good" />
            <StatTile
              label="Contracts Reviewed"
              value={`${data.requestsReviewed}/${data.requestsInScope}`}
            />
          </div>

          <div className="card" style={{ padding: 14, marginTop: 12 }}>
            <div className="text-body-xs muted">
              Coverage: <strong>{data.requestsReviewed}</strong> contract
              {data.requestsReviewed === 1 ? "" : "s"} reviewed out of{" "}
              <strong>{data.requestsInScope}</strong> in scope for an existing playbook.{" "}
              <strong>{data.requestsSkipped}</strong> of {data.requestsTotal} requests scanned have
              no matching playbook yet — those are not reviewed, not passed.
              {!!data.requestsFailed && (
                <>
                  {" "}
                  <span style={{ color: "var(--bad)" }}>
                    {data.requestsFailed} contract(s) failed to scan completely and are excluded.
                  </span>
                </>
              )}
              {!!data.verificationFailedCount && (
                <> {data.verificationFailedCount} verification call(s) failed.</>
              )}
            </div>
          </div>

          <div className="between" style={{ marginTop: 28, marginBottom: 12 }}>
            <h3>Rule results</h3>
            <div className="toggle-group" role="tablist" aria-label="Rule result filter">
              {(Object.keys(TAB_LABEL) as Tab[]).map((t) => {
                const count =
                  t === "violations"
                    ? data.violations.length
                    : t === "flagged"
                      ? data.flaggedInaccurate.length
                      : t === "satisfied"
                        ? data.satisfied.length
                        : data.notApplicableOrNotFound.length;
                return (
                  <button
                    key={t}
                    role="tab"
                    aria-selected={tab === t}
                    className={tab === t ? "active" : ""}
                    onClick={() => setTab(t)}
                  >
                    {TAB_LABEL[t]} ({count})
                  </button>
                );
              })}
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {pageItems.map((r, i) => (
              <RuleCard key={`${r.request_id}-${r.rule_id}-${i}`} r={r} />
            ))}
            {visible.length === 0 && (
              <div className="placeholder" style={{ padding: 32 }}>
                No results in {TAB_LABEL[tab]}.
              </div>
            )}
          </div>

          {visible.length > PAGE_SIZE && (
            <div className="between" style={{ marginTop: 12 }}>
              <div className="text-body-xs muted">
                Page {page + 1} of {pageCount} ({visible.length.toLocaleString()} results)
              </div>
              <div className="row">
                <button className="btn sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                  Previous
                </button>
                <button
                  className="btn sm"
                  disabled={page >= pageCount - 1}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function RuleCard({ r }: { r: RuleResult }) {
  const isFlagged = !!r.verification && !r.verification.accurate;
  const wasVerified = !!r.verification;
  const unvetted = isUnvetted(r.suggested_language_source_tag);

  return (
    <div className="card" style={{ padding: 16, borderColor: isFlagged ? "var(--bad)" : undefined }}>
      <div className="between">
        <div className="row">
          {r.priority && <Chip tone={PRIORITY_TONE[r.priority]}>{r.priority}</Chip>}
          <Chip tone="info">{r.rule_id}</Chip>
          {r.status === "not_found" && <Chip tone="warn">not found</Chip>}
          {r.status === "not_applicable" && <Chip>not applicable</Chip>}
          {r.status === "satisfied" && (
            <Chip tone="good">satisfied{r.met_at === "fallback" ? " (fallback)" : ""}</Chip>
          )}
        </div>
        <div className="row">
          {wasVerified ? (
            isFlagged ? (
              <span className="row text-body-xs" style={{ color: "var(--bad)" }}>
                <ShieldAlert size={14} /> flagged
              </span>
            ) : (
              <span className="row text-body-xs" style={{ color: "var(--good)" }}>
                <ShieldCheck size={14} /> verified
              </span>
            )
          ) : (
            <span className="text-body-xs muted">not re-checked</span>
          )}
        </div>
      </div>

      <div className="text-body-sm" style={{ marginTop: 8, fontWeight: 600 }}>
        {r.title}
      </div>

      <div className="text-body-xs muted" style={{ marginTop: 4 }}>
        Request #{r.request_id}
        {r.request_title ? ` · ${r.request_title}` : ""}
        {r.category ? ` · ${r.category}` : ""}
        {r.matched_location ? ` · ${r.matched_location}` : ""}
        {r.confidence ? ` · confidence: ${r.confidence}` : ""}
      </div>

      <div className="divider" />

      {r.explanation && <div className="text-body-sm">{r.explanation}</div>}

      {r.matched_clause_text && (
        <div style={{ marginTop: 10 }}>
          <div className="text-label muted">Clause text found</div>
          <div className="text-body-sm" style={{ fontStyle: "italic" }}>
            "{r.matched_clause_text}"
          </div>
        </div>
      )}

      {!!r.triggered_flags?.length && (
        <div style={{ marginTop: 10 }}>
          <div className="text-label muted">Triggered flags</div>
          <ul className="text-body-sm" style={{ margin: "4px 0 0", paddingLeft: 18 }}>
            {r.triggered_flags.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}

      {r.suggested_language && (
        <div style={{ marginTop: 12 }}>
          <div className="between" style={{ alignItems: "center" }}>
            <div className="text-label muted">Suggested replacement language</div>
            {unvetted ? (
              <span className="row text-body-xs" style={{ color: "var(--bad)" }}>
                <AlertTriangle size={14} /> Unvetted draft — counsel review required
              </span>
            ) : (
              r.suggested_language_source_tag && (
                <span className="text-body-xs muted">Source: {r.suggested_language_source_tag}</span>
              )
            )}
          </div>
          <div
            className="text-body-sm"
            style={{
              marginTop: 6,
              padding: 10,
              borderRadius: 8,
              border: unvetted ? "1px solid var(--bad)" : "1px solid var(--border)",
            }}
          >
            {r.suggested_language}
          </div>
          {unvetted && (
            <div className="text-body-xs" style={{ marginTop: 4, color: "var(--bad)" }}>
              The playbook marks this wording as an unvetted draft. Do not send it to a
              counterparty without counsel review.
            </div>
          )}
        </div>
      )}

      {isFlagged && r.verification?.issue && (
        <div style={{ marginTop: 10, padding: 10, background: "oklch(0.93 0.05 25)", borderRadius: 8 }}>
          <div className="text-label" style={{ color: "var(--bad)" }}>
            Why this was flagged
          </div>
          <div className="text-body-sm">{r.verification.issue}</div>
          {r.verification.corrected_status && (
            <div className="text-body-xs muted" style={{ marginTop: 4 }}>
              Second pass suggests the correct status is: {r.verification.corrected_status}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
