// Renders an AssembledContract to a paginated PDF via jsPDF, entirely
// client-side — this project's frontend is a static SPA with no live
// backend, and nothing here needs secrecy or server-side compute, so
// standing up a backend just for this would be a bigger commitment than
// the feature warrants.

import { jsPDF } from "jspdf";
import type { AssembledContract } from "./contractAssembly";

const MARGIN = 20;
const PAGE_HEIGHT = 297;
const CONTENT_WIDTH = 210 - MARGIN * 2;
const BODY_FONT_SIZE = 10;
const LINE_HEIGHT = 5;

type ParagraphOptions = {
  bold?: boolean;
  italic?: boolean;
  color?: [number, number, number];
};

class PdfCursor {
  doc: jsPDF;
  y: number;

  constructor(doc: jsPDF) {
    this.doc = doc;
    this.y = MARGIN;
  }

  private ensureSpace(height: number) {
    if (this.y + height > PAGE_HEIGHT - MARGIN) {
      this.doc.addPage();
      this.y = MARGIN;
    }
  }

  addHeading(text: string, size: number) {
    this.ensureSpace(LINE_HEIGHT * 2);
    this.doc.setFont("helvetica", "bold");
    this.doc.setFontSize(size);
    this.doc.text(text, MARGIN, this.y);
    this.y += LINE_HEIGHT * 1.6;
    this.doc.setFont("helvetica", "normal");
    this.doc.setFontSize(BODY_FONT_SIZE);
  }

  addParagraph(text: string, opts?: ParagraphOptions) {
    this.doc.setFont("helvetica", opts?.bold ? "bold" : opts?.italic ? "italic" : "normal");
    this.doc.setFontSize(BODY_FONT_SIZE);
    if (opts?.color) {
      this.doc.setTextColor(opts.color[0], opts.color[1], opts.color[2]);
    } else {
      this.doc.setTextColor(0, 0, 0);
    }
    const lines: string[] = this.doc.splitTextToSize(text, CONTENT_WIDTH);
    for (const line of lines) {
      this.ensureSpace(LINE_HEIGHT);
      this.doc.text(line, MARGIN, this.y);
      this.y += LINE_HEIGHT;
    }
    this.doc.setTextColor(0, 0, 0);
  }

  addSpacer(height = LINE_HEIGHT) {
    this.y += height;
  }
}

export function renderContractPdf(contract: AssembledContract): jsPDF {
  const doc = new jsPDF({ unit: "mm", format: "a4" });
  const cur = new PdfCursor(doc);

  cur.addHeading("DRAFT CONTRACT", 20);
  cur.addSpacer(2);
  cur.addParagraph(`Contract type: ${contract.contractType}`, { bold: true });
  cur.addParagraph(`Party A: ${contract.partyA}`);
  cur.addParagraph(`Party B: ${contract.partyB}`);
  cur.addParagraph(`Generated: ${new Date(contract.generatedAt).toLocaleString()}`);
  cur.addSpacer(6);
  cur.addParagraph(
    "AI-GENERATED FIRST DRAFT — NOT FOR EXECUTION WITHOUT REVIEW. This document was assembled " +
      "from a Golden Rules playbook and has not been reviewed by counsel. Bracketed " +
      "[[NEEDS REVIEW: ...]] markers indicate cross-references or jurisdiction-specific wording " +
      "that must be completed manually. Clause language uses role terms from the source precedent " +
      '(e.g. "the Subcontractor", "the Contractor") — confirm these align with Party A / Party B ' +
      "before use.",
    { bold: true, color: [180, 0, 0] }
  );
  cur.addSpacer(4);
  cur.addParagraph(
    `This Agreement is made between ${contract.partyA} ("Party A") and ${contract.partyB} ("Party B").`
  );

  for (const section of contract.sections) {
    cur.addSpacer(4);
    cur.addHeading(`${section.number}. ${section.title}`, 14);
    for (const clause of section.clauses) {
      cur.addSpacer(1);
      cur.addParagraph(`${clause.number}  ${clause.title}`, { bold: true });
      cur.addParagraph(clause.body);
      if (clause.sourceTag) {
        cur.addParagraph(`[Source: ${clause.sourceTag}]`, { italic: true, color: [100, 100, 100] });
      }
    }
  }

  if (contract.needsManualDraft.length > 0) {
    cur.addSpacer(6);
    cur.addHeading("Clauses Requiring Manual Drafting", 14);
    cur.addParagraph(
      "The playbook has no pre-approved model language for the following — a human must draft these from scratch."
    );
    for (const item of contract.needsManualDraft) {
      cur.addSpacer(1);
      cur.addParagraph(`${item.ruleId}  ${item.title} (${item.category})`, { bold: true });
      cur.addParagraph(`Required position: ${item.required}`);
    }
  }

  return doc;
}

export function downloadContractPdf(contract: AssembledContract, filename: string): void {
  renderContractPdf(contract).save(filename);
}
