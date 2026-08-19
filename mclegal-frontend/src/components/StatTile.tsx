export function StatTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: "good" | "bad";
}) {
  return (
    <div className="card" style={{ padding: 18 }}>
      <div className="text-label muted">{label}</div>
      <div
        className="text-title-md"
        style={{ marginTop: 4, color: tone === "good" ? "var(--good)" : tone === "bad" ? "var(--bad)" : undefined }}
      >
        {typeof value === "number" ? value.toLocaleString() : value}
      </div>
    </div>
  );
}
