import { useEffect, useMemo, useState } from "react";
import { ShieldCheck, ShieldAlert } from "lucide-react";

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

const SIG_CHIP: Record<Finding["significance"], string> = {
  high: "chip bad",
  medium: "chip warn",
  low: "chip",
  noise: "chip",
};

type Tab = "confirmed" | "flagged";

export default function ClauseFindings() {
  const [data, setData] = useState<ClauseFindingsData | null>(null);
  const [tab, setTab] = useState<Tab>("confirmed");

  useEffect(() => {
    fetch("/data/clause_findings.json")
      .then((r) => (r.ok ? r.json() : null))
      .then(setData)
      .catch(() => setData(null));
  }, []);

  const visible = useMemo(() => (data ? (tab === "confirmed" ? data.confirmed : data.flagged) : []), [data, tab]);

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

      {!data && (
        <div className="placeholder" style={{ padding: 40, marginTop: 24 }}>
          No clause-findings export yet — waiting on the tagging + verification workflow to
          produce output.
        </div>
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
            <div className="toggle-group">
              <button className={tab === "confirmed" ? "active" : ""} onClick={() => setTab("confirmed")}>
                Confirmed ({data.confirmed.length})
              </button>
              <button className={tab === "flagged" ? "active" : ""} onClick={() => setTab("flagged")}>
                Flagged ({data.flagged.length})
              </button>
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {visible.map((f, i) => (
              <FindingCard key={i} f={f} />
            ))}
            {visible.length === 0 && (
              <div className="placeholder" style={{ padding: 32 }}>
                No {tab} findings.
              </div>
            )}
          </div>
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
          <span className={SIG_CHIP[f.significance]}>{f.significance}</span>
          <span className="chip info">{f.clause_name}</span>
        </div>
        <div className="row">
          {isFlagged ? (
            <span className="row text-body-xs" style={{ color: "var(--bad)" }}>
              <ShieldAlert size={14} /> flagged
            </span>
          ) : (
            <span className="row text-body-xs" style={{ color: "oklch(0.45 0.12 150)" }}>
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
        <div className="text-body-sm" style={{ color: "oklch(0.45 0.12 150)" }}>
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

function StatTile({ label, value, tone }: { label: string; value: number | string; tone?: "good" | "bad" }) {
  return (
    <div className="card" style={{ padding: 18 }}>
      <div className="text-label muted">{label}</div>
      <div
        className="text-title-md"
        style={{ marginTop: 4, color: tone === "good" ? "oklch(0.45 0.12 150)" : tone === "bad" ? "var(--bad)" : undefined }}
      >
        {value}
      </div>
    </div>
  );
}
