import { useEffect, useMemo, useState } from "react";
import { ShieldCheck, ShieldAlert } from "lucide-react";
import { useJsonResource } from "../hooks/useJsonResource";
import { ResourceStatus } from "../components/ResourceStatus";
import { StatTile } from "../components/StatTile";
import { Chip, type ChipTone } from "../components/Chip";

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
};

type ClauseFindingsData = {
  confirmed: Finding[];
  flagged: Finding[];
  lowOrNoiseCount: number;
  requestsProcessed: number;
  requestsTotal: number;
  generatedAt?: string;
};

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

  const data = resource.status === "ready" ? resource.data : null;

  const visible = useMemo(() => {
    if (!data) return [];
    const base = tab === "confirmed" ? data.confirmed : data.flagged;
    const term = search.trim().toLowerCase();
    if (!term) return base;
    return base.filter(
      (f) =>
        f.clause_name?.toLowerCase().includes(term) ||
        f.vendor?.toLowerCase().includes(term) ||
        f.request_title?.toLowerCase().includes(term)
    );
  }, [data, tab, search]);

  useEffect(() => {
    setPage(0);
  }, [tab, search]);

  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const pageItems = visible.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);

  return (
    <div>
      <div className="eyebrow">McLegal · Phase 4-5</div>
      <h1>Clause Findings</h1>
      <p className="muted" style={{ marginTop: 6 }}>
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
        Request #{f.request_id} {f.request_title ? `· ${f.request_title}` : ""}
        {f.location ? ` · ${f.location}` : ""}
      </div>

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
