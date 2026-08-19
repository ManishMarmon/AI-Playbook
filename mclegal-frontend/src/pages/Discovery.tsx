import { useEffect, useMemo, useState } from "react";
import { useJsonResource } from "../hooks/useJsonResource";
import { ResourceStatus } from "../components/ResourceStatus";
import { StatTile } from "../components/StatTile";
import { Chip, type ChipTone } from "../components/Chip";

type CatalogRow = {
  request_id: number;
  request_title: string;
  request_status: string;
  file_name: string;
  file_type: string;
  category: "Redline" | "Draft/Negotiation Copy" | "Likely Executed/Signed" | "Unclassified/Supporting";
  score: number;
  confidence: number;
  is_likely_redline: boolean;
  signals: string;
};

const CHIP_TONE: Record<CatalogRow["category"], ChipTone | undefined> = {
  Redline: "warn",
  "Draft/Negotiation Copy": "info",
  "Likely Executed/Signed": "good",
  "Unclassified/Supporting": undefined,
};

const PAGE_SIZE = 25;

function isCatalogRows(data: unknown): data is CatalogRow[] {
  return Array.isArray(data);
}

export default function Discovery({ search }: { search: string }) {
  const resource = useJsonResource<CatalogRow[]>("/data/redline_catalog.json", isCatalogRows);
  const [showAll, setShowAll] = useState(false);
  const [page, setPage] = useState(0);

  const rows = resource.status === "ready" ? resource.data : [];

  const stats = useMemo(() => {
    const requests = new Set(rows.map((r) => r.request_id)).size;
    const redlines = rows.filter((r) => r.is_likely_redline).length;
    const highConfidence = rows.filter((r) => r.is_likely_redline && r.confidence >= 50).length;
    return { requests, attachments: rows.length, redlines, highConfidence };
  }, [rows]);

  const filtered = useMemo(() => {
    const byToggle = showAll ? rows : rows.filter((r) => r.is_likely_redline);
    const term = search.trim().toLowerCase();
    if (!term) return byToggle;
    return byToggle.filter(
      (r) =>
        r.request_title?.toLowerCase().includes(term) ||
        r.file_name?.toLowerCase().includes(term) ||
        r.category?.toLowerCase().includes(term)
    );
  }, [rows, showAll, search]);

  useEffect(() => {
    setPage(0);
  }, [showAll, search]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const visible = filtered.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);

  return (
    <div>
      <div className="eyebrow">McLegal · Phase 1-3 PoC</div>
      <h1>Redline Discovery</h1>
      <p className="muted" style={{ marginTop: 6 }}>
        Filename + text-signal classification over CobbleStone requests. No download, no OCR —
        runs directly off CobbleStone's own extracted text.
      </p>

      {resource.status !== "ready" && (
        <ResourceStatus
          status={resource.status}
          error={resource.error}
          onRetry={resource.refetch}
          loadingLabel="Loading catalog..."
          errorLabel="Couldn't load the redline catalog."
        />
      )}

      {resource.status === "ready" && (
        <>
          <div className="grid-4" style={{ marginTop: 24 }}>
            <StatTile label="Requests Scanned" value={stats.requests} />
            <StatTile label="Attachments Found" value={stats.attachments} />
            <StatTile label="Potential Redlines" value={stats.redlines} />
            <StatTile label="High Confidence (≥50)" value={stats.highConfidence} />
          </div>

          <div className="between" style={{ marginTop: 28, marginBottom: 12 }}>
            <h3>Files</h3>
            <div className="toggle-group" role="tablist" aria-label="File filter">
              <button
                role="tab"
                aria-selected={!showAll}
                className={!showAll ? "active" : ""}
                onClick={() => setShowAll(false)}
              >
                Redlines only
              </button>
              <button
                role="tab"
                aria-selected={showAll}
                className={showAll ? "active" : ""}
                onClick={() => setShowAll(true)}
              >
                All attachments
              </button>
            </div>
          </div>

          <div className="card" style={{ overflow: "hidden" }}>
            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Request</th>
                    <th>File</th>
                    <th>Category</th>
                    <th>Confidence</th>
                    <th>Signals</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((r, i) => (
                    <tr key={`${r.request_id}-${r.file_name}-${i}`}>
                      <td>
                        <div className="text-body">{r.request_title || `Request ${r.request_id}`}</div>
                        <div className="text-body-xs muted">#{r.request_id}</div>
                      </td>
                      <td className="text-body-sm" style={{ maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.file_name}>
                        {r.file_name}
                      </td>
                      <td>
                        <Chip tone={CHIP_TONE[r.category]}>{r.category}</Chip>
                      </td>
                      <td className="text-body-sm">{r.confidence}</td>
                      <td
                        className="text-body-xs muted"
                        style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                        title={r.signals}
                      >
                        {r.signals}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {visible.length === 0 && (
              <div className="placeholder" style={{ padding: 40 }}>
                No matching files.
              </div>
            )}
          </div>

          {filtered.length > PAGE_SIZE && (
            <div className="between" style={{ marginTop: 12 }}>
              <div className="text-body-xs muted">
                Page {page + 1} of {pageCount} ({filtered.length.toLocaleString()} files)
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
