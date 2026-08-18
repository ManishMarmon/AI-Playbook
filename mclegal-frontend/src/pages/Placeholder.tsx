export default function Placeholder({ title, note }: { title: string; note: string }) {
  return (
    <div>
      <div className="eyebrow">McLegal</div>
      <h1>{title}</h1>
      <div className="card" style={{ padding: 24, marginTop: 20 }}>
        <p className="muted">{note}</p>
      </div>
    </div>
  );
}
