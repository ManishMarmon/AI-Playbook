import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useJsonResource } from "../hooks/useJsonResource";
import { ResourceStatus } from "../components/ResourceStatus";
import { StatTile } from "../components/StatTile";
import { Chip, type ChipTone } from "../components/Chip";

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

const STATUS_TONE: Record<DiffRecord["process_status_tag"], ChipTone | undefined> = {
  contract_already_exists: "good",
  no_contract_expected: undefined,
  in_progress: "warn",
};

const PREVIEW_EDITS = 5;

function isDiffRecords(data: unknown): data is DiffRecord[] {
  return Array.isArray(data);
}

export default function RedlineDiffs({ search }: { search: string }) {
  const resource = useJsonResource<DiffRecord[]>("/data/redline_diffs.json", isDiffRecords);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const records = useMemo(
    () => (resource.status === "ready" ? resource.data.filter((r) => r.edits && r.edits.length > 0) : []),
    [resource]
  );

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return records;
    return records.filter(
      (r) => r.request_title?.toLowerCase().includes(term) || r.vendor?.toLowerCase().includes(term)
    );
  }, [records, search]);

  const stats = useMemo(() => {
    const totalEdits = filtered.reduce((sum, r) => sum + r.edits.length, 0);
    return { pairs: filtered.length, totalEdits };
  }, [filtered]);

  function toggle(id: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  return (
    <div>
      <h1>Redline Diffs</h1>
      <p className="muted page-subtitle" style={{ marginTop: 6 }}>
        Word-level diff between each request's original and redlined file text. Raw diff
        fragments shown below — clause-level tagging (which clause, spirit of the change,
        negotiation intent) runs as a separate AI pass and isn't merged in here yet.
      </p>

      {resource.status !== "ready" && (
        <ResourceStatus
          status={resource.status}
          error={resource.error}
          onRetry={resource.refetch}
          loadingLabel="Loading diffs..."
          errorLabel="Couldn't load the redline diffs."
        />
      )}

      {resource.status === "ready" && (
        <>
          <div className="grid-2" style={{ marginTop: 24, maxWidth: 500 }}>
            <StatTile label="Requests with a Diffed Pair" value={stats.pairs} />
            <StatTile label="Total Raw Edits" value={stats.totalEdits} />
          </div>

          <div style={{ marginTop: 28, display: "flex", flexDirection: "column", gap: 12 }}>
            {filtered.map((r) => {
              const isOpen = expanded.has(r.request_id);
              const preview = isOpen ? r.edits : r.edits.slice(0, PREVIEW_EDITS);
              return (
                <div key={r.request_id} className="card" style={{ padding: 0, overflow: "hidden" }}>
                  <button
                    onClick={() => toggle(r.request_id)}
                    aria-expanded={isOpen}
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
                    <Chip tone={STATUS_TONE[r.process_status_tag]}>{r.process_status || "unknown status"}</Chip>
                  </button>

                  <div style={{ padding: "0 16px 16px 16px" }}>
                    <div
                      className="text-body-xs muted"
                      style={{ marginBottom: 10, overflowWrap: "anywhere" }}
                    >
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
                          <div className="text-body-sm" style={{ color: "var(--good)" }}>
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
            {filtered.length === 0 && (
              <div className="placeholder" style={{ padding: 40 }}>
                No matching diffed requests.
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
