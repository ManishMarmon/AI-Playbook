/** Shared loading/error rendering for a useJsonResource-backed page. */
export function ResourceStatus({
  status,
  error,
  onRetry,
  loadingLabel,
  errorLabel,
}: {
  status: "loading" | "error";
  error?: string | null;
  onRetry: () => void;
  loadingLabel: string;
  errorLabel: string;
}) {
  if (status === "loading") {
    return (
      <div className="placeholder skeleton" style={{ padding: 40, marginTop: 24 }}>
        {loadingLabel}
      </div>
    );
  }

  return (
    <div
      className="placeholder"
      style={{ padding: 40, marginTop: 24, gap: 10 }}
      role="alert"
    >
      <div>{errorLabel}</div>
      {error && (
        <div className="text-body-xs muted" style={{ textAlign: "center" }}>
          {error}
        </div>
      )}
      <button className="btn sm" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}
