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
    "Constructed from the stated position or an observed negotiating pattern, not taken from any precedent. Do NOT let a tool generate redlines from these unsupervised until counsel has signed them off.",
};
const DEFAULT_SOURCE_TAG_MEANING = "See the playbook's own notes for how this wording was sourced.";

export function isUnvetted(tag?: string | null) {
  return !!tag && tag.toLowerCase().includes("unvetted");
}

function sourceTagColor(tag: string): string | undefined {
  if (isUnvetted(tag)) return RED;
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

function buildOverviewSection(meta: PlaybookMeta, rules: PlaybookRule[]): (Paragraph | Table)[] {
  const ruleCount = rules.length;
  const withLanguage = rules.filter((r) => !!r.preferred_language);
  const withoutLanguage = rules.filter((r) => !r.preferred_language);
  const isDraft = meta.status !== "attorney_reviewed";

  const sourceTagCounts = new Map<string, number>();
  for (const r of withLanguage) {
    const tag = r.source_tag || "(unspecified source)";
    sourceTagCounts.set(tag, (sourceTagCounts.get(tag) ?? 0) + 1);
  }

  const appliesToValues = Array.from(new Set(rules.map((r) => r.applies_to)));
  const hasSplitVariants = appliesToValues.length > 1;

  const unvettedRules = withLanguage.filter((r) => isUnvetted(r.source_tag));
  const allUnvetted = withLanguage.length > 0 && unvettedRules.length === withLanguage.length;

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
          text: `This is the machine-readable form of the ${meta.label} playbook. Each rule is self-contained: where to look in the contract, the position required, the acceptable fallback, the specific conditions that should raise a flag, and model clause language ${isDraft ? "where AI-drafted language exists" : "where vetted drafting exists"}.`,
          size: 19,
        }),
      ],
    }),
    new Paragraph({
      spacing: { after: 200 },
      children: [
        new TextRun({
          text: "It contains no commentary, provenance narrative, or process guidance beyond this page — everything else here is intended to be read as an instruction.",
          size: 19,
        }),
      ],
    }),
  ];

  if (isDraft) {
    out.push(
      new Paragraph({
        spacing: { after: 200 },
        children: [
          new TextRun({
            text: "This entire playbook is an AI-derived first draft, mined from real contract negotiations — it has not been reviewed by counsel. Treat every rule as provisional until an attorney signs off.",
            bold: true,
            color: RED,
            size: 19,
          }),
        ],
      })
    );
  }

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
          text: `${withLanguage.length} of the ${ruleCount} rules carry model clause language. The tag tells you how much weight it holds — this matters if a tool will generate redlines from it unsupervised.`,
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
          bodyCell(tag, { color: sourceTagColor(tag), bold: true }),
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

  if (unvettedRules.length > 0) {
    out.push(
      new Paragraph({
        spacing: { before: 160 },
        children: [
          allUnvetted
            ? new TextRun({
                text: "Every rule's model language in this document is an unvetted AI draft — none of it has been reviewed by counsel. Do not let a tool generate redlines from any of it unsupervised until reviewed.",
                italics: true,
                size: 18,
              })
            : new TextRun({
                text: `The ${unvettedRules.length} unvetted draft${unvettedRules.length === 1 ? "" : "s"} ${unvettedRules.length === 1 ? "is" : "are"} the only item${unvettedRules.length === 1 ? "" : "s"} in this document that should not go straight into production. ${unvettedRules.length === 1 ? "It is" : "They are"}: ${unvettedRules.map((r) => r.rule_id).join(", ")}.`,
                italics: true,
                size: 18,
              }),
        ],
      })
    );
  }

  return out;
}

export async function renderPlaybookDocx(meta: PlaybookMeta, rules: PlaybookRule[]): Promise<Blob> {
  const categories = Array.from(new Set(rules.map((r) => r.category)));
  const children: (Paragraph | Table)[] = buildOverviewSection(meta, rules);

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
