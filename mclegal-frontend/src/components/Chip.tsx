import type { ReactNode } from "react";

export type ChipTone = "good" | "warn" | "bad" | "info";

export function Chip({ tone, children }: { tone?: ChipTone; children: ReactNode }) {
  return <span className={tone ? `chip ${tone}` : "chip"}>{children}</span>;
}
