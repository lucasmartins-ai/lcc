// Research log, generated from LCC-judge at the pinned commit. This file only says which files
// belong to which study and which STATUS.md row describes it; every date, number and verdict on
// the pages is read from those files at build time.
import { blob, docFiles, firstCommit, firstParagraph, judge, list, md, read, section, title } from "./sources.ts";

interface StudyDef {
  id: string;
  /** First cell of the study's row in STATUS.md "Current state". */
  status: string;
  dir: string;
  protocol: string;
  results?: string;
  /** Files of this study inside `dir` (several studies share specialist-v1/). */
  files?: RegExp;
  /** Added to the STATUS.md name when two studies share a row. */
  part?: string;
}

const G = "research/goal-engine-2026-10-04";
const DEFS: StudyDef[] = [
  { id: "specialist-v3", status: "Block judge specialist v3", dir: `${G}/specialist-v1`, protocol: "V3_FINAL_TEST_PROTOCOL.md", results: "V3_FINAL_TEST_RESULTS.md", files: /^(V3_FINAL|v3_final|heldout-v3)/ },
  { id: "specialist-v4", status: "Block judge v4", dir: `${G}/specialist-v1`, protocol: "V4_SELECTION_RULE.md", results: "V4_DEV_RESULTS.md", files: /^(V4_|v4-)/ },
  { id: "specialist-v5", status: "Block judge v5", dir: `${G}/specialist-v1`, protocol: "V5_SELECTION_RULE.md", results: "V5_DEV_RESULTS.md", files: /^(V5_|v5-)/ },
  { id: "specialist-v5c2", status: "v5 cycle 2", dir: `${G}/specialist-v1`, protocol: "V5C2_PROTOCOL.md", results: "V5C2_RESULTS.md", files: /^(V5C2|v5c2)/ },
  { id: "stashed-recall-v1", status: "`stashed` + `recall`", dir: `${G}/stashed-recall-v1`, protocol: "PROTOCOL.md", results: "RESULTS.md" },
  { id: "probe-eval-v1", status: "Probe eval v1", dir: `${G}/probe-eval-v1`, protocol: "PROTOCOL.md", results: "RESULTS.md" },
  { id: "when-to-compact", status: "When to compact", dir: "research/when-to-compact-2026-10-19", protocol: "WHEN_PROTOCOL.md", results: "WHEN_RESULTS.md", files: /^(WHEN_|when-)/ },
  { id: "when-to-compact-2", status: "When to compact", dir: "research/when-to-compact-2026-10-19", protocol: "WHEN2_PROTOCOL.md", results: "WHEN2_RESULTS.md", files: /^(WHEN2_|when2-)/, part: "part 2" },
  { id: "intake-judge-v1", status: "Intake judge v1", dir: `${G}/intake-judge-v1`, protocol: "PROTOCOL.md", results: "RESULTS.md" },
  { id: "intake-judge-v2", status: "Intake judge v2", dir: `${G}/intake-judge-v2`, protocol: "PROTOCOL.md" },
  { id: "intake-judge-v3", status: "Intake judge v3", dir: `${G}/intake-judge-v3`, protocol: "PROTOCOL.md", results: "RESULTS_EXTERNAL.md" },
];

export type Outcome = "shipped" | "not adopted" | "pending" | "passed" | "finding";

export interface Study {
  id: string;
  name: string;
  title: string;
  question: { label: string; html: string };
  registered: { date: string; sha: string };
  outcome: Outcome;
  /** The STATUS.md state cell, rendered. */
  stateHtml: string;
  /** "Bottom line" (or "Verdicts") of the results file, rendered; null while results are pending. */
  resultHtml: string | null;
  protocolUrl: string;
  resultsUrl: string | null;
  files: { name: string; url: string; kind: "md" | "json" }[];
}

const STATUS = "STATUS.md";
const status = read(judge, STATUS);
const plain = (s: string) => s.replace(/[`*]/g, "").trim();

/** Rows of the "Current state" table: [line, state, evidence]. */
export const currentState = (section(status, "Current state") ?? "")
  .split("\n")
  .filter((l) => l.startsWith("|") && !/^\|\s*(line|---)/.test(l))
  .map((l) => l.split("|").slice(1, -1).map((c) => c.trim()));

export const currentStateIntro = md(firstParagraph(section(status, "Current state") ?? ""), judge, STATUS);
export const statusDate = /^# Status \((\d{4}-\d{2}-\d{2})\)/m.exec(status)?.[1] ?? "unknown";

function outcomeOf(state: string): Outcome {
  if (/pending/i.test(state)) return "pending";
  if (/not adopted|fails|no ranker replaces/i.test(state)) return "not adopted";
  if (/shipped/i.test(state)) return "shipped";
  if (/\bpass/i.test(state)) return "passed";
  return "finding";
}

/** Label and markdown text: the protocol's Question section, its H1 when that is a question, or its Why. */
function question(protocol: string, fallback: string): { label: string; text: string } {
  const h1 = /^#\s+(.+)$/m.exec(protocol)?.[1] ?? "";
  if (h1.includes("?")) {
    const t = h1.slice(h1.indexOf(":") + 1).replace(/\s*\([^)]*\)\s*$/, "").trim();
    return { label: "Question", text: t[0]!.toUpperCase() + t.slice(1) };
  }
  const q = section(protocol, "Question");
  if (q) return { label: "Question", text: firstParagraph(q) };
  const why = section(protocol, "Why");
  if (why) return { label: "Why", text: firstParagraph(why) };
  return { label: "What was tested", text: fallback };
}

function load(d: StudyDef): Study {
  const row = currentState.find((r) => plain(r[0]!).startsWith(plain(d.status)));
  if (!row) throw new Error(`research: no STATUS.md "Current state" row starts with ${d.status}`);
  const pPath = `${d.dir}/${d.protocol}`;
  const protocol = read(judge, pPath);
  const rPath = d.results ? `${d.dir}/${d.results}` : null;
  const results = rPath ? read(judge, rPath) : null;
  const bottom = results ? section(results, "Bottom line", "Verdicts") : null;
  if (results && !bottom) throw new Error(`research: ${rPath} has no "Bottom line" or "Verdicts" section`);
  const name = plain(row[0]!) + (d.part ? `, ${d.part}` : "");
  const q = question(protocol, title(results ?? protocol, name));
  const files = list(judge, d.dir)
    .filter((f) => /\.(md|json)$/.test(f) && !f.slice(d.dir.length + 1).includes("/"))
    .filter((f) => !d.files || d.files.test(f.slice(d.dir.length + 1)))
    .map((f) => ({ name: f.slice(d.dir.length + 1), url: blob(judge, f), kind: f.endsWith(".md") ? ("md" as const) : ("json" as const) }));
  return {
    id: d.id,
    name,
    title: title(results ?? protocol, name),
    question: { label: q.label, html: md(q.text, judge, pPath, true) },
    registered: firstCommit(judge, pPath),
    outcome: outcomeOf(row[1]!),
    stateHtml: md(row[1]!, judge, STATUS, true),
    resultHtml: bottom && rPath ? md(bottom, judge, rPath) : null,
    protocolUrl: blob(judge, pPath),
    resultsUrl: rPath ? blob(judge, rPath) : null,
    files,
  };
}

export const studies = DEFS.map(load);
// Study pages share research/ with lcc's docs/research/*.md pages.
for (const s of studies) if (docFiles.includes(`docs/research/${s.id}.md`)) throw new Error(`research: ${s.id} clashes with a docs page`);

export const ROADMAP = "docs/08-roadmap.md";
export const statusUrl = blob(judge, STATUS);
