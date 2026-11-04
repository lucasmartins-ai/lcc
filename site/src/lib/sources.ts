// Everything the site shows comes from two repos, read at build time:
// - lcc (this checkout): tracked files, read from the working tree;
// - LCC-judge: read only through git at one commit (LCC_JUDGE_REF, default HEAD), so uncommitted
//   or untracked files in that clone never reach the site, and every link points at that commit.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { Marked, type Token, type Tokens } from "marked";
import { gfmHeadingId } from "marked-gfm-heading-id";

export interface Repo {
  name: string;
  dir: string;
  url: string;
  sha: string;
}

const git = (dir: string, ...args: string[]) =>
  execFileSync("git", ["-C", dir, ...args], { encoding: "utf8", maxBuffer: 1 << 28 });

function open(name: string, dir: string, url: string, ref: string): Repo {
  try {
    return { name, dir, url, sha: git(dir, "rev-parse", `${ref}^{commit}`).trim() };
  } catch {
    throw new Error(
      `${name}: no git checkout at ${dir}. For LCC-judge run \`npm run fetch-judge\` or set LCC_JUDGE_DIR.`,
    );
  }
}

// Astro runs from site/, so the lcc checkout is its parent.
export const lcc = open("lcc", path.resolve(".."), "https://github.com/lucasmartins-ai/lcc", "HEAD");
export const judge = open(
  "LCC-judge",
  path.resolve(process.env.LCC_JUDGE_DIR ?? ".cache/LCC-judge"),
  "https://github.com/lucasmartins-ai/LCC-judge",
  process.env.LCC_JUDGE_REF ?? "HEAD",
);
if (git(judge.dir, "rev-parse", "--is-shallow-repository").trim() === "true") {
  // A shallow clone would date every protocol to the clone's single commit.
  throw new Error("LCC-judge clone is shallow: pre-registration dates need full history (git fetch --unshallow).");
}

export function readBytes(repo: Repo, file: string): Buffer {
  return repo === lcc
    ? readFileSync(path.join(repo.dir, file))
    : execFileSync("git", ["-C", repo.dir, "show", `${repo.sha}:${file}`], { maxBuffer: 1 << 28 });
}
export const read = (repo: Repo, file: string) => readBytes(repo, file).toString("utf8");
export const sha256 = (b: Buffer) => createHash("sha256").update(b).digest("hex");

/** Tracked files under `dir` (lcc: index; LCC-judge: the pinned commit). */
export function list(repo: Repo, dir: string): string[] {
  const out =
    repo === lcc ? git(repo.dir, "ls-files", "--", dir) : git(repo.dir, "ls-tree", "-r", "--name-only", repo.sha, "--", dir);
  return out.split("\n").filter(Boolean);
}

/** Date and short hash of the commit that first added `file`. */
export function firstCommit(repo: Repo, file: string): { date: string; sha: string } {
  const lines = git(repo.dir, "log", "--diff-filter=A", "--format=%as %H", repo.sha, "--", file).trim().split("\n");
  const [date, sha] = (lines.at(-1) ?? "").split(" ");
  if (!date || !sha) throw new Error(`${repo.name}: no commit adds ${file}`);
  return { date, sha };
}

export const blob = (repo: Repo, file: string) => `${repo.url}/blob/${repo.sha}/${file}`;
export const commitUrl = (repo: Repo, sha: string) => `${repo.url}/commit/${sha}`;
export const short = (sha: string) => sha.slice(0, 7);

/** Site URL for a path, under the configured base (SITE_BASE). */
export const href = (p = "") => import.meta.env.BASE_URL.replace(/\/?$/, "/") + p.replace(/^\//, "");

// ---- lcc docs rendered as site pages, at the paths the old Jekyll site used (QUICKSTART.html) ----

export const docFiles = list(lcc, "docs")
  .concat(list(lcc, "benchmarks/research").filter((f) => !f.slice("benchmarks/research/".length).includes("/")))
  .filter((f) => f.endsWith(".md") && f !== "docs/index.md");
const docSet = new Set(docFiles);

/** `docs/QUICKSTART.md` -> `QUICKSTART`; `benchmarks/research/USE_CASES.md` -> `benchmarks/research/USE_CASES`. */
export const docSlug = (file: string) => file.replace(/^docs\//, "").replace(/\.md$/, "");

function rewrite(repo: Repo, from: string, target: string, image: boolean): string {
  if (/^([a-z][a-z0-9+.-]*:|#|\/\/)/i.test(target)) return target;
  const [p = "", hash] = target.split("#", 2);
  const file = p.startsWith("/") ? p.slice(1) : path.posix.normalize(path.posix.join(path.posix.dirname(from), p));
  const anchor = hash ? `#${hash}` : "";
  if (repo === lcc && !image) {
    if (file === "docs/index.md" || file === "docs") return href() + anchor;
    const page = docSet.has(file) ? file : docSet.has(`${file.replace(/\/$/, "")}/README.md`) ? `${file.replace(/\/$/, "")}/README.md` : null;
    if (page) return href(`${docSlug(page)}.html`) + anchor;
  }
  return image
    ? `${repo.url.replace("github.com", "raw.githubusercontent.com")}/${repo.sha}/${file}`
    : blob(repo, file) + anchor;
}

export const stripFrontmatter = (src: string) => src.replace(/^---\n[\s\S]*?\n---\n/, "");

/** Markdown from `file` in `repo` to HTML; relative links go to site pages or to GitHub at the pinned commit. */
export function md(src: string, repo: Repo, file: string, inline = false): string {
  const m = new Marked(gfmHeadingId(), {
    walkTokens(t: Token) {
      if (t.type === "link" || t.type === "image") {
        const l = t as Tokens.Link | Tokens.Image;
        l.href = rewrite(repo, file, l.href, t.type === "image");
      }
    },
  });
  const text = stripFrontmatter(src);
  return (inline ? m.parseInline(text) : m.parse(text)) as string;
}

export const title = (src: string, fallback: string) =>
  /^#\s+(.+)$/m.exec(stripFrontmatter(src))?.[1]?.replace(/[`*]/g, "").trim() ?? fallback;

/** Body of the first `## ` section whose heading starts with one of `names` as whole words (null if none). */
export function section(src: string, ...names: string[]): string | null {
  const parts = src.split(/^(?=## )/m);
  const hit = parts.find((s) => names.some((n) => s.startsWith(`## ${n}`) && !/\w/.test(s.charAt(3 + n.length))));
  return hit ? hit.replace(/^## .*\n/, "").trim() : null;
}

/** First paragraph of a markdown chunk (lines up to the first blank line). */
export const firstParagraph = (s: string) => s.trim().split(/\n\s*\n/)[0]!.replace(/\n/g, " ");

/** The first fenced code block in `file` that contains `needle`, as markdown (fails the build if none). */
export function codeBlock(repo: Repo, file: string, needle: string): string {
  const hit = read(repo, file).match(/^```[\s\S]*?^```$/gm)?.find((b) => b.includes(needle));
  if (!hit) throw new Error(`codeBlock: no fenced block with "${needle}" in ${repo.name}/${file}`);
  return md(hit, repo, file);
}

/**
 * A number quoted on the site must appear verbatim in its source file, or the build fails.
 * Returns `q` for use in templates; `.href` is the source link.
 */
export function cite(repo: Repo, file: string) {
  const text = read(repo, file);
  const q = (snippet: string) => {
    if (!text.includes(snippet)) throw new Error(`cite: "${snippet}" not found in ${repo.name}/${file}`);
    return snippet;
  };
  return Object.assign(q, { href: blob(repo, file), label: `${repo.name}/${file}` });
}
