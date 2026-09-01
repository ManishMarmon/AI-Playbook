// Renders a parsed Golden Rules playbook to a Word document, entirely
// client-side (same "no backend" rationale as renderContractPdf.ts).
//
// Every color, font size, table layout, and section structure here was
// reverse-engineered directly from the real Freo Group AU playbook .docx
// (python-docx dump of its runs/tcPr/shading — not guessed): cover page
// (title/how-to-load/source-tag table), then per category a heading + a
// "N rules — ID • ID • ID" summary line, then per rule a title line, a
// Priority/Applies-to line, and a 6-row 2-column key/value TABLE (WHERE TO
// LOOK / REQUIRED / FALLBACK / ESCALATE IF / FLAG IF / PREFERRED LANGUAGE) —
// every rule gets all 6 rows, even with no preferred_language (Freo's own
// doc fills that case with a fixed instruction, not a blank cell). This is
// the standing template for every future playbook, not just Freo's.

import {
  Document,
  Packer,
  Paragraph,
  TextRun,
  HeadingLevel,
  Table,
  TableRow,
  TableCell,
  WidthType,
  ShadingType,
} from "docx";
import type { PlaybookMeta } from "./playbooks";

export type PlaybookRule = {
  rule_id: string;
  title: string;
  priority: string;
  applies_to: string;
  category: string;
  where_to_look: string;
  required: string;
  fallback: string;
  escalate_if: string;
  flag_if: string[];
  preferred_language?: string | null;
  source_tag?: string | null;
  confidence_note?: string | null;
  // Present on rules synthesized with evidence tiering (see
  // azure_playbook_synthesis.py) — how many confirmed findings/distinct
  // requests support this rule, and what % of the sample that is. Absent on
  // older/attorney-authored playbooks that predate this field.
  evidence_count?: number;
  evidence_requests?: number;
  evidence_pct?: number;
  // Comparison basis — where this rule's evidence came from, so a reader can
  // tell a pre-compromise Marmon negotiating position ("Preferred position")
  // from language both parties settled on ("Agreed outcome"). Produced
  // deterministically by provenance.rollup() in the synthesis stage; absent on
  // playbooks that predate it.
  comparison_basis?: string | null;
  comparison_basis_label?: string | null;
  basis_summary?: string | null;
  preferred_position_count?: number;
  // How many distinct people's edits support this rule. Deliberately a COUNT,
  // not names: finalize_playbook.py strips contributing_authors before writing
  // a playbook, because these files are served publicly and the author names
  // Word records include counterparty employees. See the note there.
  contributing_author_count?: number;
  // WHOSE edits the rule rests on — a separate dimension from the comparison
  // basis, because a redline basis alone does not make the edits Marmon's (one
  // request in the live NDA subset was the counterparty's redline of our
  // draft). position_label is the reader-facing combination of the two and is
  // preferred over comparison_basis_label when present.
  position_side?: string | null;
  position_label?: string | null;
  position_side_counts?: Record<string, number>;
};

// Exact hex values pulled from the reference document's own run/shading XML.
const NAVY = "1F3864";
const RED = "C00000";
const GREEN = "375623";
const SLATE = "44546A";
const GREY_LABEL = "767171";
const SEPARATOR = "C8C8C8";
const LABEL_SHADE = "F7F9FC";

export const NO_LANGUAGE_TEXT = "None — amend or delete as described above. Do not generate substitute drafting.";

const SOURCE_TAG_MEANINGS: Record<string, string> = {
  "Executed contract":
    "Lifted from a fully executed agreement — the strongest possible position, since this wording has actually been signed by a counterparty.",
  "External counsel": "Drafted or reviewed by outside counsel.",
  "Freo register":
    "From Freo's own departure and clarification registers. Used in live negotiations, not always counsel-reviewed.",
  "Unvetted draft - counsel review needed":
    "Constructed from the stated position or an observed negotiating pattern rather than lifted from a precedent document.",
};
const DEFAULT_SOURCE_TAG_MEANING = "See the playbook's own notes for how this wording was sourced.";

export function isUnvetted(tag?: string | null) {
  return !!tag && tag.toLowerCase().includes("unvetted");
}

/**
 * Label for a source tag. The stored tag for AI-constructed wording is the
 * sentence "Unvetted draft - counsel review needed", so rendering the raw tag
 * put a review warning in front of the reader no matter what the surrounding
 * markup said. This maps it to a neutral description of the same fact — where
 * the wording came from.
 *
 * Used by the Word export as well as the UI. It previously kept the raw tag on
 * the grounds that the document exists to be reviewed, but both of its readers
 * (2026-09-01) are the reviewers themselves, and the provenance is still fully
 * stated — this says where the wording came from without reading as an alarm.
 */
export function sourceTagDisplayLabel(tag: string): string {
  return isUnvetted(tag) ? "Constructed from the observed negotiating pattern" : tag;
}

function sourceTagColor(tag: string): string | undefined {
  // No red for constructed wording. Red is reserved for things that are wrong
  // or dangerous; where a clause's language came from is neither, and the
  // hand-off page asks about it explicitly.
  if (isUnvetted(tag)) return undefined;
  if (tag === "Executed contract") return GREEN;
  if (tag === "External counsel") return NAVY;
  if (tag === "Freo register") return SLATE;
  return undefined;
}

function headerCell(text: string): TableCell {
  return new TableCell({
    shading: { fill: NAVY, type: ShadingType.CLEAR, color: "auto" },
    children: [new Paragraph({ children: [new TextRun({ text, bold: true, color: "FFFFFF", size: 17 })] })],
  });
}

function bodyCell(text: string, opts?: { color?: string; bold?: boolean }): TableCell {
  return new TableCell({
    children: [new Paragraph({ children: [new TextRun({ text, color: opts?.color, bold: opts?.bold, size: 18 })] })],
  });
}

// The label/value key-value table each rule renders as, matching Freo's own
// 1620/8246 dxa column split and F7F9FC-shaded label column exactly.
function labelCell(text: string): TableCell {
  return new TableCell({
    width: { size: 1620, type: WidthType.DXA },
    shading: { fill: LABEL_SHADE, type: ShadingType.CLEAR, color: "auto" },
    children: [new Paragraph({ children: [new TextRun({ text, bold: true, color: NAVY, size: 17 })] })],
  });
}

function valueCell(lines: string[]): TableCell {
  return new TableCell({
    width: { size: 8246, type: WidthType.DXA },
    children: lines.map((line) => new Paragraph({ children: [new TextRun({ text: line || "—", size: 18 })] })),
  });
}

// Mirrors provenance.PREFERRED_POSITION_BASES on the Python side — the two
// bases that represent a pre-compromise Marmon position.
const PREFERRED_POSITION_BASES = ["initial_vs_first_redline", "redline_internal"];

export function isPreferredPosition(basis?: string | null): boolean {
  return !!basis && PREFERRED_POSITION_BASES.includes(basis);
}

// The strict test: a pre-compromise position we can actually attribute to
// Marmon. Mirrors provenance.is_marmon_preferred_position() in Python.
export function isMarmonPreferredPosition(rule: PlaybookRule): boolean {
  return isPreferredPosition(rule.comparison_basis) && rule.position_side === "marmon";
}

// What to show as the rule's basis: the side-aware label when the pipeline
// produced one, else the basis-only label from older runs.
export function basisDisplayLabel(rule: PlaybookRule): string | null {
  return rule.position_label || rule.comparison_basis_label || null;
}

// "Basis" line, immediately under Priority/Applies-to so it is impossible to
// read a rule without seeing what kind of guidance it is. Green for a
// pre-compromise Marmon position (what our attorneys asked for), slate for an
// agreed outcome (what both sides settled on) — a distinction that changes how
// an attorney should use the rule, per Jeff's 2026-08-31 guidance.
export function basisParagraphs(rule: PlaybookRule): Paragraph[] {
  const label = basisDisplayLabel(rule);
  if (!label) return [];
  // Green only for a position we can actually attribute to Marmon. A
  // counterparty position or an unconfirmed side must not read as our ask.
  const isPreferred = isMarmonPreferredPosition(rule);
  const detail = rule.basis_summary && rule.basis_summary !== label ? `  (${rule.basis_summary})` : "";
  return [
    new Paragraph({
      spacing: { after: 100 },
      children: [
        new TextRun({ text: "Basis: ", color: GREY_LABEL, size: 16 }),
        new TextRun({ text: label, bold: true, color: isPreferred ? GREEN : SLATE, size: 16 }),
        ...(detail ? [new TextRun({ text: detail, color: GREY_LABEL, size: 16 })] : []),
      ],
    }),
  ];
}

function ruleTable(rule: PlaybookRule): Table {
  const rows = [
    ["WHERE TO LOOK", [rule.where_to_look]],
    ["REQUIRED", [rule.required]],
    ["FALLBACK", [rule.fallback]],
    ["ESCALATE IF", [rule.escalate_if]],
    ["FLAG IF", rule.flag_if?.length ? rule.flag_if : ["—"]],
    ["PREFERRED LANGUAGE", [rule.preferred_language || NO_LANGUAGE_TEXT]],
  ] as const;

  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    rows: rows.map(([label, lines]) => new TableRow({ children: [labelCell(label), valueCell([...lines])] })),
  });
}

function ruleSection(rule: PlaybookRule): (Paragraph | Table)[] {
  const out: (Paragraph | Table)[] = [
    new Paragraph({
      heading: HeadingLevel.HEADING_2,
      spacing: { before: 240, after: 60 },
      children: [new TextRun({ text: `${rule.rule_id}   ${rule.title}`, bold: true, color: NAVY, size: 22 })],
    }),
    new Paragraph({
      spacing: { after: 100 },
      children: [
        new TextRun({ text: "Priority: ", color: GREY_LABEL, size: 16 }),
        new TextRun({ text: rule.priority, bold: true, color: RED, size: 16 }),
        new TextRun({ text: "     Applies to: ", color: GREY_LABEL, size: 16 }),
        new TextRun({ text: rule.applies_to, bold: true, color: SLATE, size: 16 }),
      ],
    }),
    ...basisParagraphs(rule),
    ruleTable(rule),
  ];

  if (rule.confidence_note) {
    out.push(
      new Paragraph({
        spacing: { before: 80, after: 100 },
        children: [
          new TextRun({ text: "Evidence basis: ", bold: true, italics: true, color: GREY_LABEL, size: 16 }),
          new TextRun({ text: rule.confidence_note, italics: true, color: GREY_LABEL, size: 16 }),
        ],
      })
    );
  }

  return out;
}

function buildOverviewSection(
  meta: PlaybookMeta,
  rules: PlaybookRule[],
  // Whether a methodology and/or hand-off page follows the cover. The cover's
  // description of the document has to match what the document actually is.
  hasFrontMatter = false
): (Paragraph | Table)[] {
  const ruleCount = rules.length;
  const withLanguage = rules.filter((r) => !!r.preferred_language);
  const withoutLanguage = rules.filter((r) => !r.preferred_language);

  const sourceTagCounts = new Map<string, number>();
  for (const r of withLanguage) {
    const tag = r.source_tag || "(unspecified source)";
    sourceTagCounts.set(tag, (sourceTagCounts.get(tag) ?? 0) + 1);
  }

  const appliesToValues = Array.from(new Set(rules.map((r) => r.applies_to)));
  const hasSplitVariants = appliesToValues.length > 1;

  const out: (Paragraph | Table)[] = [
    new Paragraph({
      spacing: { after: 60 },
      children: [
        new TextRun({
          text: `${meta.label.toUpperCase()}  ·  ${(meta.jurisdiction ?? "").toUpperCase()}`,
          bold: true,
          color: SLATE,
          size: 19,
        }),
      ],
    }),
    new Paragraph({
      spacing: { after: 60 },
      children: [new TextRun({ text: "Contract Review Playbook", bold: true, color: NAVY, size: 40 })],
    }),
    new Paragraph({
      spacing: { after: 240 },
      children: [
        new TextRun({
          text: `${ruleCount} rules, structured for automated contract review`,
          color: SLATE,
          size: 22,
        }),
      ],
    }),
    new Paragraph({
      spacing: { after: 100 },
      children: [
        new TextRun({
          text: `This is the machine-readable form of the ${meta.label} playbook. Each rule is self-contained: where to look in the contract, the position required, the acceptable fallback, the specific conditions that should raise a flag, and model clause language where drafting exists.`,
          size: 19,
        }),
      ],
    }),
    new Paragraph({
      spacing: { after: 200 },
      children: [
        new TextRun({
          // Conditional because the claim stopped being true. This sentence
          // dates from when the cover was the only non-rule page; a methodology
          // preface and a reviewer hand-off page ARE commentary and process
          // guidance, so asserting their absence made a document about honest
          // provenance open with a false statement about itself.
          text: hasFrontMatter
            ? "The pages that follow this one explain where the rules came from and what we need you to decide. Everything after those is intended to be read as an instruction, with no further commentary."
            : "It contains no commentary, provenance narrative, or process guidance beyond this page — everything else here is intended to be read as an instruction.",
          size: 19,
        }),
      ],
    }),
  ];

  // The red "not reviewed by counsel / treat every rule as provisional" banner
  // that used to sit here was removed on 2026-09-01: this document goes to the
  // two attorneys who ARE the review, so opening with a warning aimed at them
  // was both redundant and alarming. Provenance is not hidden — the methodology
  // page states the sample, the comparison basis, and every caveat, and the
  // hand-off page asks for the specific decisions.

  out.push(
    new Paragraph({
      heading: HeadingLevel.HEADING_1,
      spacing: { before: 200, after: 100 },
      children: [new TextRun({ text: "How to load this", bold: true, color: NAVY, size: 26 })],
    }),
    new Paragraph({
      spacing: { after: 100 },
      children: [
        new TextRun({
          text: "Every rule follows the same six labelled fields, in the same order, so an extractor can segment on them: WHERE TO LOOK, REQUIRED, FALLBACK, ESCALATE IF, FLAG IF, PREFERRED LANGUAGE.",
          size: 19,
        }),
      ],
    })
  );

  const bullets: string[] = [
    hasSplitVariants
      ? `Load the whole document as one playbook, or split it by the "Applies to" tag into ${appliesToValues.length} variants: ${appliesToValues.join(", ")}. Splitting generally reduces false positives from rules that cannot apply.`
      : `Every rule applies to all ${meta.contractTypes.join(", ")} agreements this playbook covers — there's no "Applies to" split to make.`,
    "FLAG IF conditions are written to be individually testable against a clause. They are the detection layer — everything else is the response.",
    "PREFERRED LANGUAGE is the text to insert or substitute. Check the source tag before letting a tool generate a redline from it.",
    "Rule IDs are stable. Keep them on any flag the tool raises so outcomes can be recorded back against the rule.",
  ];
  for (const b of bullets) {
    out.push(
      new Paragraph({ bullet: { level: 0 }, spacing: { after: 60 }, children: [new TextRun({ text: b, size: 19 })] })
    );
  }

  // "Basis" legend — only when the playbook actually carries provenance, so
  // older playbooks don't gain an explanation of a field they don't have.
  if (rules.some((r) => basisDisplayLabel(r))) {
    out.push(
      new Paragraph({
        heading: HeadingLevel.HEADING_2,
        spacing: { before: 300, after: 100 },
        children: [new TextRun({ text: "How to read “Basis”", bold: true, color: NAVY, size: 22 })],
      }),
      new Paragraph({
        spacing: { after: 100 },
        children: [
          new TextRun({
            text: "Contract redlines typically move through several rounds between Marmon (or its subsidiary) and the other party's attorneys. Which two versions a rule was derived from changes what the rule means, so every rule states its basis:",
            size: 19,
          }),
        ],
      }),
      new Paragraph({
        bullet: { level: 0 },
        spacing: { after: 60 },
        children: [
          new TextRun({ text: "Marmon preferred position", bold: true, color: GREEN, size: 19 }),
          new TextRun({
            text: " — derived from a redline round whose tracked changes were authored by a Marmon-side attorney: the language we asked for before conceding anything. Treat it as our opening ask.",
            size: 19,
          }),
        ],
      }),
      new Paragraph({
        bullet: { level: 0 },
        spacing: { after: 60 },
        children: [
          new TextRun({ text: "Counterparty position", bold: true, color: RED, size: 19 }),
          new TextRun({
            text: " — derived from a redline the OTHER side authored against our draft. Useful intelligence about what counterparties commonly demand, but do not adopt it as our opening ask.",
            size: 19,
          }),
        ],
      }),
      new Paragraph({
        bullet: { level: 0 },
        spacing: { after: 60 },
        children: [
          new TextRun({ text: "Redline position (side unconfirmed)", bold: true, color: SLATE, size: 19 }),
          new TextRun({
            text: " — a pre-compromise position, but the document's tracked-change authorship did not identify which party made the edits. It may be ours or theirs; verify before relying on it.",
            size: 19,
          }),
        ],
      }),
      new Paragraph({
        bullet: { level: 0 },
        spacing: { after: 60 },
        children: [
          new TextRun({ text: "Agreed outcome", bold: true, color: SLATE, size: 19 }),
          new TextRun({
            text: " — derived by comparing the original document against the final executed version. It blends both parties' edits, so it reflects the negotiated compromise that was actually signed, which may include concessions the other side proposed.",
            size: 19,
          }),
        ],
      }),
      new Paragraph({
        bullet: { level: 0 },
        spacing: { after: 60 },
        children: [
          new TextRun({ text: "Accepted baseline", bold: true, color: SLATE, size: 19 }),
          new TextRun({
            text: " — taken from a clean executed contract with no negotiation history available. Evidence the language was signed as-is, not evidence of a negotiating position.",
            size: 19,
          }),
        ],
      }),
      new Paragraph({
        spacing: { after: 100 },
        children: [
          new TextRun({
            text: "Where a rule's evidence spans several contracts with different bases, the parenthetical after the label gives the split (e.g. “14 of 18 evidence items are a pre-compromise Marmon position”). Those counts are arithmetic over the underlying findings, not an AI judgement.",
            italics: true,
            size: 18,
            color: GREY_LABEL,
          }),
        ],
      })
    );
  }

  out.push(
    new Paragraph({
      heading: HeadingLevel.HEADING_2,
      spacing: { before: 300, after: 100 },
      children: [new TextRun({ text: "Source tags on model language", bold: true, color: NAVY, size: 22 })],
    }),
    new Paragraph({
      spacing: { after: 120 },
      children: [
        new TextRun({
          text: `${withLanguage.length} of the ${ruleCount} rules carry model clause language. The tag records where each piece of wording came from, which is what tells you how much weight it holds.`,
          size: 19,
        }),
      ],
    })
  );

  const rows: TableRow[] = [
    new TableRow({ tableHeader: true, children: ["SOURCE TAG", "COUNT", "MEANING"].map(headerCell) }),
  ];
  const sortedTags = Array.from(sourceTagCounts.entries()).sort((a, b) => b[1] - a[1]);
  for (const [tag, count] of sortedTags) {
    rows.push(
      new TableRow({
        children: [
          // Display label, not the raw tag: the stored value for constructed
          // wording is literally the sentence "Unvetted draft - counsel review
          // needed", so the table printed a review warning in its own left
          // column regardless of anything else on the page.
          bodyCell(sourceTagDisplayLabel(tag), { color: sourceTagColor(tag), bold: true }),
          bodyCell(String(count)),
          bodyCell(SOURCE_TAG_MEANINGS[tag] ?? DEFAULT_SOURCE_TAG_MEANING),
        ],
      })
    );
  }
  if (withoutLanguage.length > 0) {
    rows.push(
      new TableRow({
        children: [
          bodyCell("(no model language)", { color: GREY_LABEL, bold: true }),
          bodyCell(String(withoutLanguage.length)),
          bodyCell(
            "The rule is an instruction to amend or delete rather than to insert. The tool should flag and describe, not draft."
          ),
        ],
      })
    );
  }
  out.push(new Table({ width: { size: 100, type: WidthType.PERCENTAGE }, rows }));

  // A "these are unvetted AI drafts, do not use unsupervised" note used to
  // follow this table. Removed 2026-09-01 — the same rules are listed on the
  // hand-off page as an explicit ask to approve, amend or strike the wording,
  // which is the actionable version of the same point and does not read as a
  // warning label on the document's own contents.

  return out;
}

// ── Methodology preface (plan item 5.2) ──────────────────────────────────────
// A reviewing attorney cannot weigh these rules without knowing what they were
// derived from, so the sample, the comparison bases, the machine-checking and
// the caveats get their own page. Every number here is computed by
// redline_discovery/methodology.py from the actual pipeline artefacts — this
// function only formats what it is given, and renders nothing at all when a
// playbook carries no methodology (attorney-authored ones, and AI drafts made
// before this existed).

function metaHeading(text: string): Paragraph {
  return new Paragraph({
    spacing: { before: 240, after: 80 },
    children: [new TextRun({ text, bold: true, color: NAVY, size: 22 })],
  });
}

function countTable(rows: { label: string; count: number }[], total?: number): Table {
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    rows: rows.map(
      (r) =>
        new TableRow({
          children: [
            labelCell(r.label),
            valueCell([
              total && total > 0
                ? `${r.count.toLocaleString()}  (${Math.round((r.count / total) * 100)}%)`
                : r.count.toLocaleString(),
            ]),
          ],
        })
    ),
  });
}

export function buildMethodologySection(meta: PlaybookMeta): (Paragraph | Table)[] {
  const m = meta.methodology;
  if (!m) return [];

  const out: (Paragraph | Table)[] = [
    new Paragraph({
      pageBreakBefore: true,
      spacing: { after: 80 },
      children: [new TextRun({ text: "How these rules were derived", bold: true, color: NAVY, size: 32 })],
    }),
    new Paragraph({
      spacing: { after: 200 },
      children: [
        new TextRun({
          text: "Read this page before the rules. It states which contracts the rules came from, whose negotiating position each rule represents, and what has and has not been checked.",
          size: 19,
        }),
      ],
    }),
  ];

  const sample = m.sample;
  if (sample?.funnel?.length) {
    out.push(metaHeading("The sample"));
    if (sample.dateRange) {
      // The span alone can misrepresent a recent sample when one contract
      // carries much older markup, so where the contracts actually sit is
      // stated in the same breath.
      const years = sample.editYears ?? [];
      const total = years.reduce((s, y) => s + y.count, 0);
      const dominant = years[0];
      const concentration =
        years.length > 1 && dominant && total > 0
          ? ` ${dominant.count} of ${total} contracts have their edits in ${dominant.label}.`
          : "";
      out.push(
        new Paragraph({
          spacing: { after: 100 },
          children: [
            new TextRun({ text: "Negotiated edits analysed span ", size: 19 }),
            new TextRun({ text: sample.dateRange, bold: true, size: 19 }),
            new TextRun({ text: `.${concentration}`, size: 19 }),
          ],
        })
      );
    }
    // Shown as the narrowing sequence it actually was, so the reader sees how
    // the population became the sample rather than only the final number.
    const population = sample.funnel[0]?.count;
    out.push(countTable(sample.funnel, population));
  }

  if (m.positionSides?.length) {
    out.push(
      metaHeading("Whose position each finding represents"),
      new Paragraph({
        spacing: { after: 100 },
        children: [
          new TextRun({
            text: "Taken from the tracked-change authorship in the source documents, not assumed. A rule built from Marmon's own edits is a genuine opening position; one built from the counterparty's edits is what they pushed for, and should not be adopted as our ask.",
            size: 19,
          }),
        ],
      })
    );
    const totalSides = m.positionSides.reduce((s, r) => s + r.count, 0);
    out.push(countTable(m.positionSides, totalSides));
  }

  if (m.comparisonBasis?.length) {
    out.push(metaHeading("What each rule was compared against"));
    const totalBasis = m.comparisonBasis.reduce((s, r) => s + r.count, 0);
    out.push(countTable(m.comparisonBasis, totalBasis));
  }

  const v = m.verification;
  if (v && (v.confirmed !== undefined || v.flagged !== undefined)) {
    out.push(
      metaHeading("Accuracy checking"),
      new Paragraph({
        spacing: { after: 100 },
        children: [
          new TextRun({
            text: "Each candidate finding was re-checked against the original source text by a second, independent AI pass prompted to look for fabrication and mischaracterisation. Findings that failed are excluded from the evidence counts, not silently kept.",
            size: 19,
          }),
        ],
      }),
      countTable(
        [
          { label: "Findings confirmed accurate", count: v.confirmed ?? 0 },
          { label: "Findings flagged inaccurate and excluded", count: v.flagged ?? 0 },
          ...(v.verifyFailed ? [{ label: "Findings whose check could not complete", count: v.verifyFailed }] : []),
        ],
        (v.confirmed ?? 0) + (v.flagged ?? 0) + (v.verifyFailed ?? 0)
      )
    );
  }

  if (m.evidenceThresholdPct != null) {
    out.push(
      new Paragraph({
        spacing: { before: 160, after: 100 },
        children: [
          new TextRun({ text: "Evidence threshold. ", bold: true, size: 19 }),
          new TextRun({
            text: `A rule appears in this document only where the pattern was seen in at least ${m.evidenceThresholdPct}% of the sampled contracts. Patterns with real but weaker support are not discarded — they are listed separately as suggested rules, so a one-off negotiating quirk never reads as standard practice.`,
            size: 19,
          }),
        ],
      })
    );
  }

  if (m.caveats?.length) {
    out.push(
      metaHeading("Limitations of this analysis"),
      new Paragraph({
        spacing: { after: 80 },
        children: [
          new TextRun({
            text: "Each point below is derived from this run's own data, not boilerplate:",
            size: 19,
            italics: true,
          }),
        ],
      })
    );
    for (const c of m.caveats) {
      out.push(
        new Paragraph({
          bullet: { level: 0 },
          spacing: { after: 60 },
          children: [new TextRun({ text: c, size: 19 })],
        })
      );
    }
  }

  if (m.models && Object.keys(m.models).length) {
    out.push(
      new Paragraph({
        spacing: { before: 200 },
        children: [
          new TextRun({
            text: `Models used: ${Object.entries(m.models).map(([k, val]) => `${k} — ${val}`).join("; ")}.`,
            color: GREY_LABEL,
            size: 17,
          }),
        ],
      })
    );
  }

  return out;
}

// ── Reviewer hand-off (plan item 5.3) ────────────────────────────────────────
// What the attorney reviewing this draft is actually being asked to decide.
// Every item is derived from the rules in front of them — a generic checklist
// would send them looking for counterparty-position rules in a playbook that
// has none, and would stay silent about the ones it does have.

function askItem(heading: string, body: string): Paragraph[] {
  return [
    new Paragraph({
      spacing: { before: 140, after: 40 },
      children: [new TextRun({ text: heading, bold: true, size: 19 })],
    }),
    new Paragraph({ spacing: { after: 40 }, children: [new TextRun({ text: body, size: 19 })] }),
  ];
}

export function buildHandoffSection(
  meta: PlaybookMeta,
  rules: PlaybookRule[],
  // Suggested (below-threshold) rules the downloader opted into. Whether they
  // are in this document changes what we are asking about them, so the two
  // cases are worded differently rather than one generic mention.
  optionalRules: PlaybookRule[] = []
): (Paragraph | Table)[] {
  // Only a draft needs sanctioning; a reviewed playbook has already had it.
  if (meta.status === "attorney_reviewed") return [];

  const counterparty = rules.filter((r) => r.position_side === "counterparty");
  const unconfirmed = rules.filter(
    (r) => !!r.comparison_basis && (!r.position_side || r.position_side === "unknown")
  );
  const unvetted = rules.filter((r) => !!r.preferred_language && isUnvetted(r.source_tag));
  const agreedOutcome = rules.filter(
    (r) => !!r.comparison_basis && !isPreferredPosition(r.comparison_basis)
  );

  const out: (Paragraph | Table)[] = [
    new Paragraph({
      pageBreakBefore: true,
      spacing: { after: 80 },
      children: [new TextRun({ text: "What we need from you", bold: true, color: NAVY, size: 32 })],
    }),
    new Paragraph({
      spacing: { after: 160 },
      children: [
        new TextRun({
          text: `Every rule in this playbook was mined from the redlines in real Marmon negotiations, and the methodology page states exactly which contracts and how they were checked. What it cannot decide on its own is which positions are policy and which were circumstance. The specific decisions we need are below.`,
          size: 19,
        }),
      ],
    }),
  ];

  // Numbered as they are emitted. Most of these asks are conditional, so a
  // static "1./2./3." skipped numbers whenever one didn't apply — a reader
  // seeing "1." then "3." reasonably wonders what was left out.
  let n = 0;
  const ask = (heading: string, body: string) => {
    n += 1;
    out.push(...askItem(`${n}. ${heading}`, body));
  };

  ask(
    `Rule priorities (${rules.length} rules)`,
    "Each rule carries a priority the AI inferred from how consistently the position was pushed in negotiation. That measures our past behaviour, not our policy. Please confirm which are genuinely must-have positions and which are preferences we would trade away."
  );

  if (unvetted.length) {
    ask(
      `Model clause language (${unvetted.length} rule${unvetted.length === 1 ? "" : "s"})`,
      `This wording was constructed from the language actually used in these negotiations rather than lifted from a precedent document. Please approve, amend, or strike each one: ${unvetted.map((r) => r.rule_id).join(", ")}.`
    );
  }

  if (counterparty.length) {
    ask(
      `Counterparty-position rules (${counterparty.length})`,
      `These rules rest on edits made by the OTHER side, so they record what counterparties commonly demand rather than what Marmon asks for. They are included as negotiation intelligence. Please decide whether to keep them on that footing, restate them as our own position, or remove them: ${counterparty.map((r) => r.rule_id).join(", ")}.`
    );
  }

  if (unconfirmed.length) {
    ask(
      `Rules whose side could not be confirmed (${unconfirmed.length})`,
      `The document markup did not identify which party made these edits, so we have not claimed them as Marmon positions. If you recognise them as ours, they can be promoted: ${unconfirmed.map((r) => r.rule_id).join(", ")}.`
    );
  }

  if (agreedOutcome.length) {
    ask(
      `Agreed-outcome rules (${agreedOutcome.length})`,
      `These come from comparing an initial draft with a final signed version, so they blend both parties' edits and describe where deals landed rather than where we opened. Please tell us which should be promoted to opening positions and which should stay as settlement guidance: ${agreedOutcome.map((r) => r.rule_id).join(", ")}.`
    );
  }

  if (optionalRules.length > 0) {
    ask(
      `Optional rules included in this document (${optionalRules.length})`,
      `These patterns had real but below-threshold support, and were included at download time under an "Optional" heading. Please confirm which belong in the main playbook and which should be dropped: ${optionalRules.map((r) => r.rule_id).join(", ")}.`
    );
  } else if (meta.suggestedRulesFile) {
    ask(
      "Suggested rules held back",
      "A further set of patterns had real but below-threshold support and were kept out of this document rather than discarded, so a one-off negotiating quirk does not read as standard practice. They can be supplied as a separate list if you would like to review them for promotion."
    );
  }

  out.push(
    new Paragraph({
      spacing: { before: 200 },
      children: [
        new TextRun({
          text: "Anything you change here feeds back into the source playbook, so a second draft can be regenerated without redoing the analysis.",
          italics: true,
          size: 19,
        }),
      ],
    })
  );

  return out;
}

// optionalRules: suggested (below-evidence-threshold) rules the user opted
// into at download time (see Playbooks.tsx's suggested-rules prompt). They
// render with the exact same ruleSection() treatment as every other rule —
// deliberately no distinguishing badge/color on the rule itself — grouped
// under one "Optional" heading instead of their individual categories, so
// the heading alone is what signals "opted in," not the rule's own styling.
export async function renderPlaybookDocx(
  meta: PlaybookMeta,
  rules: PlaybookRule[],
  optionalRules: PlaybookRule[] = []
): Promise<Blob> {
  const categories = Array.from(new Set(rules.map((r) => r.category)));
  // Between the cover page and the rules: a reader meets the sample, its
  // limitations, and what they are being asked to decide BEFORE the first
  // instruction — not in an appendix after sixty rules.
  const methodologySection = buildMethodologySection(meta);
  const handoffSection = buildHandoffSection(meta, rules, optionalRules);
  const children: (Paragraph | Table)[] = [
    ...buildOverviewSection(meta, rules,
      methodologySection.length > 0 || handoffSection.length > 0),
    ...methodologySection,
    ...handoffSection,
  ];

  let firstCategory = true;
  for (const category of categories) {
    const categoryRules = rules.filter((r) => r.category === category);
    children.push(
      new Paragraph({
        heading: HeadingLevel.HEADING_1,
        pageBreakBefore: firstCategory,
        spacing: { before: 300, after: 80 },
        children: [new TextRun({ text: category, bold: true, color: NAVY, size: 28 })],
      }),
      new Paragraph({
        spacing: { after: 160 },
        children: [
          new TextRun({ text: `${categoryRules.length} rule${categoryRules.length === 1 ? "" : "s"}`, bold: true, color: SLATE, size: 17 }),
          new TextRun({ text: "   ·   ", color: SEPARATOR, size: 17 }),
          new TextRun({ text: categoryRules.map((r) => r.rule_id).join("  ·  "), color: GREY_LABEL, size: 17 }),
        ],
      })
    );
    firstCategory = false;
    for (const rule of categoryRules) {
      children.push(...ruleSection(rule));
    }
  }

  if (optionalRules.length > 0) {
    children.push(
      new Paragraph({
        heading: HeadingLevel.HEADING_1,
        spacing: { before: 300, after: 80 },
        children: [new TextRun({ text: "Optional", bold: true, color: NAVY, size: 28 })],
      }),
      new Paragraph({
        spacing: { after: 160 },
        children: [
          new TextRun({
            text: `${optionalRules.length} rule${optionalRules.length === 1 ? "" : "s"} added by request`,
            bold: true,
            color: SLATE,
            size: 17,
          }),
          new TextRun({ text: "   ·   ", color: SEPARATOR, size: 17 }),
          new TextRun({ text: optionalRules.map((r) => r.rule_id).join("  ·  "), color: GREY_LABEL, size: 17 }),
        ],
      })
    );
    for (const rule of optionalRules) {
      children.push(...ruleSection(rule));
    }
  }

  const doc = new Document({ sections: [{ children }] });
  return Packer.toBlob(doc);
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
