export type PlaybookMeta = {
  id: string;
  label: string;
  jurisdiction?: string;
  status?: "attorney_reviewed" | "ai_draft";
  contractTypes: string[];
  businessSectors?: string[];
  /**
   * Sub-kind within the contract type — for an NDA, its direction ("Mutual",
   * "One-way (Marmon Receiving)", ...). Two US NDA playbooks both claim
   * contractType "NDA", so jurisdiction + type alone can't pick one; this is
   * what makes the selection unique. Absent on playbooks whose contract type
   * has no meaningful sub-kind.
   */
  variant?: string;
  file: string;
  // Present only when synthesis drafted rule candidates that had real but
  // below-threshold evidence (2+ findings, under the min-evidence-pct bar) —
  // see azure_playbook_synthesis.py's evidence tiering. Browsed on the
  // Suggested Rules page rather than silently discarded.
  suggestedRulesFile?: string;
  // How this playbook's rules were derived — the sample, the comparison
  // bases, what was machine-verified, and the caveats that this particular
  // run's data warrants. Built by redline_discovery/methodology.py and
  // rendered as a preface page in the exported Word document so a reviewing
  // attorney can judge how much weight the rules deserve. Absent on
  // attorney-authored playbooks and on AI drafts generated before this
  // existed.
  methodology?: PlaybookMethodology;
};

export type LabelledCount = { label: string; count: number };

export type PlaybookMethodology = {
  sample?: {
    scope?: Record<string, string | number>;
    funnel?: LabelledCount[];
    subsetSize?: number | null;
    dateRange?: string | null;
    // Contracts grouped by the year of their earliest tracked edit. Reported
    // next to dateRange because the range alone misleads when one outlier
    // stretches it (live: a single March-2025 redline inside an otherwise
    // all-2026 sample).
    editYears?: LabelledCount[];
    byYear?: Record<string, number> | null;
  };
  comparisonBasis?: LabelledCount[];
  positionSides?: LabelledCount[];
  verification?: {
    requestsTagged?: number | null;
    requestsTotal?: number | null;
    confirmed?: number;
    flagged?: number;
    verifyFailed?: number;
  };
  evidenceThresholdPct?: number | null;
  models?: Record<string, string>;
  caveats?: string[];
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
