// Pure assembly logic for the contract-drafting tool ("Job B") — no PDF/React
// concerns here, so a different output format could reuse this later without
// rewriting the assembly step. See renderContractPdf.ts for rendering.

export type Rule = {
  rule_id: string;
  title: string;
  category: string;
  priority: string;
  applies_to: string;
  where_to_look: string;
  required: string;
  fallback: string;
  escalate_if: string;
  flag_if: string[];
  preferred_language: string | null;
  source_tag: string | null;
};

export type AssembledClause = {
  number: string;
  title: string;
  body: string;
  sourceTag: string | null;
  ruleId: string;
};

export type AssembledSection = {
  number: number;
  title: string;
  clauses: AssembledClause[];
};

export type NeedsManualDraftItem = {
  ruleId: string;
  title: string;
  category: string;
  required: string;
};

export type AssembledContract = {
  contractType: string;
  partyA: string;
  partyB: string;
  generatedAt: string;
  sections: AssembledSection[];
  needsManualDraft: NeedsManualDraftItem[];
  rulesTotal: number;
  rulesSelected: number;
};

// Conventional contract drafting order — deliberately NOT the playbook's own
// risk-review category order (Liability & Indemnity first makes sense for an
// audit checklist, not for a document someone is meant to read start to end).
export const CONTRACT_SECTION_ORDER = [
  "Scope, Site & Operations",
  "Payment & Money",
  "Liquidated Damages & Delay",
  "Standby, Suspension & Termination",
  "Defects & Warranties",
  "Insurance",
  "Liability & Indemnity",
  "Security & Guarantees",
  "IP, Confidentiality & Data",
  "Equipment",
  "Commercial & Structural",
  "Flow-down & Upstream Risk",
];

const BRACKET_RE = /\[[^\]]+\]/g;

// Bracket placeholders (cross-references to another clause, or
// jurisdiction-specific statute alternatives) are flagged for a human to
// resolve, never auto-filled — correctly inferring which clause or which
// jurisdiction's wording applies isn't reliably derivable from the data, and
// a wrong guess baked silently into a legal document is worse than a
// visibly incomplete one.
function flagBracketPlaceholders(text: string): string {
  return text.replace(BRACKET_RE, (match) => `[[NEEDS REVIEW: ${match}]]`);
}

// playbookContractTypes is the manifest entry's full declared contractTypes
// list for the playbook `rules` came from — NOT just the one the user picked.
// A playbook declared for exactly one contract type (e.g. US Real Estate) has
// nothing to disambiguate against: every rule in that file belongs to it,
// whatever instrument-level wording its own applies_to happens to use
// ("Lease" vs "Commercial lease" vs "Services agreement" are all still Real
// Estate). Only a playbook that bundles multiple contract types in one file
// (e.g. Freo's Equipment hire / Mining master supply agreement / Wind
// subcontract) needs applies_to to pick out which of ITS rules apply to the
// one the user selected — that exact-match behavior is preserved below.
// Skipping the filter entirely for single-type playbooks is also what fixes
// the shipped bug where applies_to values ("Lease" etc.) never equaled the
// manifest's own contract-type label ("Real Estate"), silently dropping 18
// of 29 rules from every drafted contract.
export function selectRules(rules: Rule[], contractType: string, playbookContractTypes: string[]): Rule[] {
  if (playbookContractTypes.length <= 1) return rules;
  return rules.filter((r) => r.applies_to === "All contract types" || r.applies_to === contractType);
}

export function assembleContract(
  rules: Rule[],
  contractType: string,
  playbookContractTypes: string[],
  partyA: string,
  partyB: string
): AssembledContract {
  const selected = selectRules(rules, contractType, playbookContractTypes);
  const insertable = selected.filter((r) => r.preferred_language);
  const needsManualDraft: NeedsManualDraftItem[] = selected
    .filter((r) => !r.preferred_language)
    .map((r) => ({ ruleId: r.rule_id, title: r.title, category: r.category, required: r.required }));

  const byCategory = new Map<string, Rule[]>();
  for (const r of insertable) {
    if (!byCategory.has(r.category)) byCategory.set(r.category, []);
    byCategory.get(r.category)!.push(r);
  }

  // CONTRACT_SECTION_ORDER is a curated reading order for Freo's own category
  // names. A different playbook brings its own category set — rather than
  // requiring a manual update here for every future playbook, known
  // categories keep their curated position and any category this order
  // doesn't recognize is appended afterward in the order it first appears in
  // `rules` (which is itself usually already a sensible drafting order, since
  // it reflects how the playbook's own categories were authored/derived).
  const categoriesInRules = [...byCategory.keys()];
  const orderedCategories = [
    ...CONTRACT_SECTION_ORDER.filter((c) => categoriesInRules.includes(c)),
    ...categoriesInRules.filter((c) => !CONTRACT_SECTION_ORDER.includes(c)),
  ];

  const sections: AssembledSection[] = [];
  let sectionNumber = 0;
  for (const category of orderedCategories) {
    const categoryRules = byCategory.get(category);
    if (!categoryRules || categoryRules.length === 0) continue;
    sectionNumber += 1;
    const clauses: AssembledClause[] = categoryRules.map((r, i) => ({
      number: `${sectionNumber}.${i + 1}`,
      title: r.title,
      body: flagBracketPlaceholders(r.preferred_language as string),
      sourceTag: r.source_tag,
      ruleId: r.rule_id,
    }));
    sections.push({ number: sectionNumber, title: category, clauses });
  }

  return {
    contractType,
    partyA,
    partyB,
    generatedAt: new Date().toISOString(),
    sections,
    needsManualDraft,
    rulesTotal: rules.length,
    rulesSelected: selected.length,
  };
}
