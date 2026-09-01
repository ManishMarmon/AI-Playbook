import { useEffect, useMemo, useState } from "react";
import { ShieldCheck, ShieldAlert } from "lucide-react";
import { useJsonResource } from "../hooks/useJsonResource";
import { ResourceStatus } from "../components/ResourceStatus";
import { StatTile } from "../components/StatTile";
import { Chip, type ChipTone } from "../components/Chip";
import { buildMpactUrl } from "../lib/mpact";

type Verification = { accurate: boolean; issue: string; corrected_clause_name?: string };

type Finding = {
  request_id: number;
  request_title?: string;
  vendor?: string;
  clause_name: string;
  location: string;
  before_text: string;
  after_text: string;
  change_type: "insertion" | "deletion" | "modification";
  spirit_before: string;
  spirit_after: string;
  negotiation_intent: string;
  significance: "high" | "medium" | "low" | "noise";
  verification?: Verification;
  // Provenance (see redline_discovery/provenance.py): which two document
  // versions this finding was derived from, and whose edits they were. Absent
  // on findings produced before provenance tracking existed.
  comparison_basis?: string | null;
  comparison_basis_label?: string | null;
  position_side?: string | null;
  position_label?: string | null;
  edit_authors?: string[];
  author_side_summary?: string | null;
  sequence_confidence?: string | null;
};

type ClauseFindingsData = {
  confirmed: Finding[];
  flagged: Finding[];
  lowOrNoiseCount: number;
  requestsProcessed: number;
  requestsTotal: number;
  generatedAt?: string;
};

// Green only for a position attributable to Marmon; red for the
// counterparty's ask, so a reader is never misled about whose position a
// finding represents.
function basisTone(f: Finding): ChipTone | undefined {
  if (f.position_side === "marmon") return "good";
  if (f.position_side === "counterparty") return "bad";
  return undefined;
}

function basisText(f: Finding): string | null {
  return f.position_label || f.comparison_basis_label || null;
}

const SIG_TONE: Record<Finding["significance"], ChipTone | undefined> = {
  high: "bad",
  medium: "warn",
  low: undefined,
  noise: undefined,
};

const PAGE_SIZE = 20;

function isClauseFindingsData(data: unknown): data is ClauseFindingsData {
  if (!data || typeof data !== "object") return false;
  const d = data as Record<string, unknown>;
  return Array.isArray(d.confirmed) && Array.isArray(d.flagged) && typeof d.lowOrNoiseCount === "number";
}

type Tab = "confirmed" | "flagged";

export default function ClauseFindings({ search }: { search: string }) {
  const resource = useJsonResource<ClauseFindingsData>("/data/clause_findings.json", isClauseFindingsData);
  const [tab, setTab] = useState<Tab>("confirmed");
  const [page, setPage] = useState(0);
  // Whose position a finding represents — Jeff (2026-08-31) wants a reader to
  // be able to separate Marmon's pre-compromise asks from the counterparty's.
  const [side, setSide] = useState("");

  const data = resource.status === "ready" ? resource.data : null;
  // Older findings files carry no provenance; hiding the filter then avoids
  // offering a control that would silently match nothing.
  const hasProvenance = useMemo(
    () => !!data && [...data.confirmed, ...data.flagged].some((f) => f.position_side || f.comparison_basis),
    [data]
  );

  const visible = useMemo(() => {
    if (!data) return [];
    let base = tab === "confirmed" ? data.confirmed : data.flagged;
    if (side) base = base.filter((f) => (f.position_side || "unknown") === side);
    const term = search.trim().toLowerCase();
    if (!term) return base;
    return base.filter(
      (f) =>
        f.clause_name?.toLowerCase().includes(term) ||
        f.vendor?.toLowerCase().includes(term) ||
        f.request_title?.toLowerCase().includes(term)
    );
  }, [data, tab, side, search]);

  useEffect(() => {
    setPage(0);
  }, [tab, side, search]);

  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const pageItems = visible.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);

  return (
    <div>
      <h1>Clause Findings</h1>
      <p className="muted page-subtitle" style={{ marginTop: 6 }}>
        Raw diff fragments merged into clause-level edits by an AI pass, then adversarially
        checked by a second, independent AI pass against the original source text.
        <strong> Flagged findings are not discarded</strong> — the checker caught real
        fabrication/mischaracterization in testing, so they're shown, not hidden.
      </p>

      {resource.status !== "ready" && (
        <ResourceStatus
          status={resource.status}
          error={resource.error}
          onRetry={resource.refetch}
          loadingLabel="Waiting on the tagging + verification workflow to produce output..."
          errorLabel="Couldn't load clause findings."
        />
      )}

      {data && (
        <>
          <div className="grid-4" style={{ marginTop: 24 }}>
            <StatTile label="Requests Tagged" value={`${data.requestsProcessed}/${data.requestsTotal}`} />
            <StatTile label="Confirmed Findings" value={data.confirmed.length} tone="good" />
            <StatTile label="Flagged Inaccurate" value={data.flagged.length} tone="bad" />
            <StatTile label="Low/Noise (unverified)" value={data.lowOrNoiseCount} />
          </div>

          <div className="between" style={{ marginTop: 28, marginBottom: 12 }}>
            <h3>Findings</h3>
            <div className="row" style={{ gap: 10 }}>
              {hasProvenance && (
                <select
                  className="select"
                  style={{ width: "auto" }}
                  value={side}
                  onChange={(e) => setSide(e.target.value)}
                  aria-label="Filter by whose position the finding represents"
                >
                  <option value="">All positions</option>
                  <option value="marmon">Marmon preferred position</option>
                  <option value="counterparty">Counterparty position</option>
                  <option value="unknown">Side unconfirmed</option>
                </select>
              )}
              <div className="toggle-group" role="tablist" aria-label="Finding filter">
                <button
                  role="tab"
                  aria-selected={tab === "confirmed"}
                  className={tab === "confirmed" ? "active" : ""}
                  onClick={() => setTab("confirmed")}
                >
                  Confirmed ({data.confirmed.length})
                </button>
                <button
                  role="tab"
                  aria-selected={tab === "flagged"}
                  className={tab === "flagged" ? "active" : ""}
                  onClick={() => setTab("flagged")}
                >
                  Flagged ({data.flagged.length})
                </button>
              </div>
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {pageItems.map((f, i) => (
              <FindingCard key={i} f={f} />
            ))}
            {visible.length === 0 && (
              <div className="placeholder" style={{ padding: 32 }}>
                No {tab} findings.
              </div>
            )}
          </div>

          {visible.length > PAGE_SIZE && (
            <div className="between" style={{ marginTop: 12 }}>
              <div className="text-body-xs muted">
                Page {page + 1} of {pageCount} ({visible.length.toLocaleString()} findings)
              </div>
              <div className="row">
                <button className="btn sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                  Previous
                </button>
                <button className="btn sm" disabled={page >= pageCount - 1} onClick={() => setPage((p) => p + 1)}>
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

function FindingCard({ f }: { f: Finding }) {
  const isFlagged = f.verification && !f.verification.accurate;
  return (
    <div className="card" style={{ padding: 16, borderColor: isFlagged ? "var(--bad)" : undefined }}>
      <div className="between">
        <div className="row">
          <Chip tone={SIG_TONE[f.significance]}>{f.significance}</Chip>
          <Chip tone="info">{f.clause_name}</Chip>
          {basisText(f) && <Chip tone={basisTone(f)}>{basisText(f)}</Chip>}
        </div>
        <div className="row">
          {isFlagged ? (
            <span className="row text-body-xs" style={{ color: "var(--bad)" }}>
              <ShieldAlert size={14} /> flagged
            </span>
          ) : (
            <span className="row text-body-xs" style={{ color: "var(--good)" }}>
              <ShieldCheck size={14} /> verified
            </span>
          )}
        </div>
      </div>

      <div className="text-body-xs muted" style={{ marginTop: 8 }}>
        {(() => {
          const mpactUrl = buildMpactUrl(f.request_id);
          return mpactUrl ? (
            <a href={mpactUrl} target="_blank" rel="noopener noreferrer" title="Open this request in mpact">
              Request #{f.request_id} ↗
            </a>
          ) : (
            <>Request #{f.request_id}</>
          );
        })()}
        {f.request_title ? ` · ${f.request_title}` : ""}
        {f.location ? ` · ${f.location}` : ""}
      </div>

      {/* Who actually made these edits — the per-finding authorship the
          tracked-change markup recorded, which is what makes the position
          attributable to one side rather than assumed. */}
      {f.edit_authors && f.edit_authors.some((a) => a !== "unattributed") && (
        <div className="text-body-xs muted" style={{ marginTop: 2 }}>
          Edited by {f.edit_authors.filter((a) => a !== "unattributed").join(", ")}
          {f.author_side_summary ? ` — ${f.author_side_summary}` : ""}
        </div>
      )}

      <div className="divider" />

      {f.before_text && (
        <div className="text-body-sm" style={{ color: "var(--bad)", marginBottom: 4 }}>
          − {f.before_text}
        </div>
      )}
      {f.after_text && (
        <div className="text-body-sm" style={{ color: "var(--good)" }}>
          + {f.after_text}
        </div>
      )}

      <div className="grid-2" style={{ marginTop: 12, gap: 10 }}>
        <div>
          <div className="text-label muted">Before</div>
          <div className="text-body-sm">{f.spirit_before}</div>
        </div>
        <div>
          <div className="text-label muted">After</div>
          <div className="text-body-sm">{f.spirit_after}</div>
        </div>
      </div>

      <div style={{ marginTop: 10 }}>
        <div className="text-label muted">Negotiation intent</div>
        <div className="text-body-sm">{f.negotiation_intent}</div>
      </div>

      {isFlagged && f.verification?.issue && (
        <div style={{ marginTop: 10, padding: 10, background: "oklch(0.93 0.05 25)", borderRadius: 8 }}>
          <div className="text-label" style={{ color: "var(--bad)" }}>
            Why this was flagged
          </div>
          <div className="text-body-sm">{f.verification.issue}</div>
          {f.verification.corrected_clause_name && (
            <div className="text-body-xs muted" style={{ marginTop: 4 }}>
              Suggested correct clause: {f.verification.corrected_clause_name}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
