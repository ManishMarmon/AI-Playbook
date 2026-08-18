import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

type Edit = {
  type: "replace" | "delete" | "insert";
  before: string;
  after: string;
  context_before: string;
  context_after: string;
};

type DiffRecord = {
  request_id: number;
  request_title: string;
  requestor: string;
  vendor: string;
  process_status: string;
  process_status_tag: "contract_already_exists" | "no_contract_expected" | "in_progress";
  file_count: number;
  total_file_count: number;
  pairing_method: string;
  original_file: string | null;
  redline_file: string | null;
  final_executed_file: string | null;
  edits: Edit[];
};

const STATUS_CHIP: Record<DiffRecord["process_status_tag"], string> = {
  contract_already_exists: "chip good",
  no_contract_expected: "chip",
  in_progress: "chip warn",
};

const PREVIEW_EDITS = 5;

export default function RedlineDiffs() {
  const [records, setRecords] = useState<DiffRecord[]>([]);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  useEffect(() => {
    fetch("/data/redline_diffs.json")
      .then((r) => r.json())
      .then((data: DiffRecord[]) => setRecords(data.filter((r) => r.edits && r.edits.length > 0)))
      .catch(() => setRecords([]));
  }, []);

  const stats = useMemo(() => {
    const totalEdits = records.reduce((sum, r) => sum + r.edits.length, 0);
    return { pairs: records.length, totalEdits };
  }, [records]);

  function toggle(id: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  return (
    <div>
      <div className="eyebrow">McLegal · Phase 4 (raw)</div>
      <h1>Redline Diffs</h1>
      <p className="muted" style={{ marginTop: 6 }}>
        Word-level diff between each request's original and redlined file text. Raw diff
        fragments shown below — clause-level tagging (which clause, spirit of the change,
        negotiation intent) runs as a separate AI pass and isn't merged in here yet.
      </p>

      <div className="grid-2" style={{ marginTop: 24, maxWidth: 500 }}>
        <StatTile label="Requests with a Diffed Pair" value={stats.pairs} />
        <StatTile label="Total Raw Edits" value={stats.totalEdits} />
      </div>

      <div style={{ marginTop: 28, display: "flex", flexDirection: "column", gap: 12 }}>
        {records.map((r) => {
          const isOpen = expanded.has(r.request_id);
          const preview = isOpen ? r.edits : r.edits.slice(0, PREVIEW_EDITS);
          return (
            <div key={r.request_id} className="card" style={{ padding: 0, overflow: "hidden" }}>
              <button
                onClick={() => toggle(r.request_id)}
                className="between"
                style={{ width: "100%", padding: 16, background: "none", border: "none", cursor: "pointer" }}
              >
                <div className="row">
                  {isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  <div style={{ textAlign: "left" }}>
                    <div className="text-heading-sm">{r.request_title || `Request ${r.request_id}`}</div>
                    <div className="text-body-xs muted">
                      #{r.request_id} · {r.vendor || "unknown vendor"} · {r.edits.length} edits
                    </div>
                  </div>
                </div>
                <span className={STATUS_CHIP[r.process_status_tag]}>{r.process_status || "unknown status"}</span>
              </button>

              <div style={{ padding: "0 16px 16px 16px" }}>
                <div className="text-body-xs muted" style={{ marginBottom: 10 }}>
                  <strong>Original:</strong> {r.original_file || "—"} &nbsp;→&nbsp;{" "}
                  <strong>Redline:</strong> {r.redline_file || "—"}
                  {r.final_executed_file && (
                    <>
                      {" "}
                      &nbsp;·&nbsp; <em>Final executed (excluded from diff):</em> {r.final_executed_file}
                    </>
                  )}
                </div>

                <div className="divider" />

                {preview.map((e, i) => (
                  <div key={i} style={{ padding: "8px 0", borderBottom: "1px solid var(--line-2)" }}>
                    <span className="chip" style={{ marginBottom: 4 }}>{e.type}</span>
                    {e.before && (
                      <div className="text-body-sm" style={{ color: "var(--bad)" }}>
                        − {e.before}
                      </div>
                    )}
                    {e.after && (
                      <div className="text-body-sm" style={{ color: "oklch(0.45 0.12 150)" }}>
                        + {e.after}
                      </div>
                    )}
                  </div>
                ))}

                {!isOpen && r.edits.length > PREVIEW_EDITS && (
                  <button className="btn ghost sm" style={{ marginTop: 8 }} onClick={() => toggle(r.request_id)}>
                    +{r.edits.length - PREVIEW_EDITS} more edits
                  </button>
                )}
              </div>
            </div>
          );
        })}
        {records.length === 0 && (
          <div className="placeholder" style={{ padding: 40 }}>
            Loading diffs...
          </div>
        )}
      </div>
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="card" style={{ padding: 18 }}>
      <div className="text-label muted">{label}</div>
      <div className="text-title-md" style={{ marginTop: 4 }}>
        {value.toLocaleString()}
      </div>
    </div>
  );
}
