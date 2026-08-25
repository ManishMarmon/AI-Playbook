export type PlaybookMeta = {
  id: string;
  label: string;
  jurisdiction?: string;
  status?: "attorney_reviewed" | "ai_draft";
  contractTypes: string[];
  businessSectors?: string[];
  file: string;
  // Present only when synthesis drafted rule candidates that had real but
  // below-threshold evidence (2+ findings, under the min-evidence-pct bar) —
  // see azure_playbook_synthesis.py's evidence tiering. Browsed on the
  // Suggested Rules page rather than silently discarded.
  suggestedRulesFile?: string;
};

export function isPlaybookManifest(data: unknown): data is PlaybookMeta[] {
  return (
    Array.isArray(data) &&
    data.every(
      (p) =>
        p &&
        typeof p === "object" &&
        typeof (p as PlaybookMeta).id === "string" &&
        typeof (p as PlaybookMeta).label === "string" &&
        Array.isArray((p as PlaybookMeta).contractTypes)
    )
  );
}
