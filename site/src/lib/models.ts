// Shipped model files. The sha256 shown on the site is computed from the bytes and must equal the
// pin in the Python loader, or the build fails.
import { lcc, read, readBytes, sha256 } from "./sources.ts";

const DEFS = [
  { path: "src/lcc/relevance/specialist_v3.json", pin: ["src/lcc/relevance/specialist.py", "MODEL_SHA256"], what: "Block ranker for agent transcripts (specialist v3)" },
  { path: "src/lcc/intake/intake_category_v1.json", pin: ["src/lcc/intake/category.py", "MODEL_SHA256"], what: "Request category judge (intake judge v1)" },
  { path: "src/lcc/intake/intake_categories.json", pin: ["src/lcc/intake/category.py", "NOTES_SHA256"], what: "Category notes: what context each category needs" },
] as const;

export const models = DEFS.map(({ path, pin: [loader, constant], what }) => {
  const bytes = readBytes(lcc, path);
  const hash = sha256(bytes);
  const pinned = new RegExp(`^${constant} = "([0-9a-f]{64})"`, "m").exec(read(lcc, loader))?.[1];
  if (hash !== pinned) throw new Error(`${path}: sha256 ${hash} does not match ${constant} in ${loader}`);
  return { name: path.split("/").at(-1)!, path, loader, constant, what, bytes: bytes.length, sha256: hash };
});
