export type PlaybookMeta = {
  id: string;
  label: string;
  jurisdiction?: string;
  status?: "attorney_reviewed" | "ai_draft";
  contractTypes: string[];
  businessSectors?: string[];
  file: string;
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
