// The landing page and the docs sidebar are read from docs/index.md, so editing that file updates both.
import { Marked, type Tokens } from "marked";
import { docSlug, href, lcc, md, read, section } from "./sources.ts";

const FILE = "docs/index.md";
const src = read(lcc, FILE);
const front = /^---\n([\s\S]*?)\n---\n/.exec(src)?.[1] ?? "";
const head = src.replace(/^---\n[\s\S]*?\n---\n/, "").split(/^## /m)[0]!;
const tokens = new Marked().lexer(head);
const paragraphs = tokens.filter((t): t is Tokens.Paragraph => t.type === "paragraph");
const table = tokens.find((t) => t.type === "table");
const block = (t: { raw: string } | undefined) => (t ? md(t.raw, lcc, FILE) : "");
if (!table || paragraphs.length < 3) throw new Error(`${FILE}: expected a tagline, a lead, a table and its sources line`);

export const home = {
  description: /^description:\s*(.+)$/m.exec(front)?.[1] ?? "",
  tagline: paragraphs[0]!.text.replace(/\*\*/g, ""),
  lead: block(paragraphs[1]),
  image: paragraphs.map((p) => p.tokens.find((t): t is Tokens.Image => t.type === "image")).find(Boolean),
  table: block(table),
  /** Paragraphs after the table: its sources and limits. */
  notes: paragraphs.filter((p) => head.indexOf(p.raw) > head.indexOf(table.raw)).map(block).join(""),
  install: md(section(src, "Install") ?? "", lcc, FILE),
};

/** Guides listed in docs/index.md, in that order. */
export const guides = [...(section(src, "Guides") ?? "").matchAll(/\[([^\]]+)\]\(([^)#]+\.md)\)/g)].map(([, label, file]) => ({
  label: label!,
  url: href(`${docSlug(`docs/${file}`)}.html`),
}));
