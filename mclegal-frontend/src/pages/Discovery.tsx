import { useEffect, useMemo, useState } from "react";

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

const CHIP_CLASS: Record<CatalogRow["category"], string> = {
  Redline: "chip warn",
  "Draft/Negotiation Copy": "chip info",
  "Likely Executed/Signed": "chip good",
  "Unclassified/Supporting": "chip",
};

export default function Discovery() {
  const [rows, setRows] = useState<CatalogRow[]>([]);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    fetch("/data/redline_catalog.json")
      .then((r) => r.json())
      .then(setRows)
      .catch(() => setRows([]));
  }, []);

  const stats = useMemo(() => {
    const requests = new Set(rows.map((r) => r.request_id)).size;
    const redlines = rows.filter((r) => r.is_likely_redline).length;
    const highConfidence = rows.filter((r) => r.is_likely_redline && r.confidence >= 50).length;
    return { requests, attachments: rows.length, redlines, highConfidence };
  }, [rows]);

  const visible = showAll ? rows : rows.filter((r) => r.is_likely_redline);

  return (
    <div>
      <div className="eyebrow">McLegal · Phase 1-3 PoC</div>
      <h1>Redline Discovery</h1>
      <p className="muted" style={{ marginTop: 6 }}>
        Filename + text-signal classification over CobbleStone requests. No download, no OCR —
        runs directly off CobbleStone's own extracted text.
      </p>

      <div className="grid-4" style={{ marginTop: 24 }}>
        <StatTile label="Requests Scanned" value={stats.requests} />
        <StatTile label="Attachments Found" value={stats.attachments} />
        <StatTile label="Potential Redlines" value={stats.redlines} />
        <StatTile label="High Confidence (≥50)" value={stats.highConfidence} />
      </div>

      <div className="between" style={{ marginTop: 28, marginBottom: 12 }}>
        <h3>Files</h3>
        <div className="toggle-group">
          <button className={!showAll ? "active" : ""} onClick={() => setShowAll(false)}>
            Redlines only
          </button>
          <button className={showAll ? "active" : ""} onClick={() => setShowAll(true)}>
            All attachments
          </button>
        </div>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
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
                <td className="text-body-sm">{r.file_name}</td>
                <td>
                  <span className={CHIP_CLASS[r.category]}>{r.category}</span>
                </td>
                <td className="text-body-sm">{r.confidence}</td>
                <td className="text-body-xs muted">{r.signals}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {visible.length === 0 && (
          <div className="placeholder" style={{ padding: 40 }}>
            {rows.length === 0 ? "Loading catalog..." : "No matching files."}
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
