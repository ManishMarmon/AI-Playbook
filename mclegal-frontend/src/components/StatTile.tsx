export function StatTile({
  label,
  value,
  tone,
  compact,
}: {
  label: string;
  value: number | string;
  tone?: "good" | "bad";
  compact?: boolean;
}) {
  return (
    /* Horizontal padding is wider than vertical on purpose: label and value sit
       at opposite ends of the tile, so at an even 14px both read as stuck to
       the border. Vertical stays put — these tiles sit above data tables on
       short laptop screens where extra height costs a visible row. */
    <div className="card" style={{ padding: compact ? "10px 14px" : "14px 20px" }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12 }}>
        <div className="text-label muted">{label}</div>
        <div
          className={compact ? "text-heading-sm" : "text-title-sm"}
          style={{
            whiteSpace: "nowrap",
            color: tone === "good" ? "var(--good)" : tone === "bad" ? "var(--bad)" : undefined,
          }}
        >
          {typeof value === "number" ? value.toLocaleString() : value}
        </div>
      </div>
    </div>
  );
}
