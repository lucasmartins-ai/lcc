// TypeScript port of src/lcc/intake/category.py (intake judge v1). Same features, same sum order,
// same threshold; test/intake-parity.test.ts checks it against the Python output on a fixture.

export const THRESHOLD = 0.45;
export const MAX_CHARS = 1000;
const BUCKETS = 1 << 15;
// ponytail: equals Python's `\w` on every character assigned in Unicode 16 (checked code point by
// code point against CPython 3.14); they can differ only on characters new in a later Unicode.
const WORD = /[\p{L}\p{N}_]+/gu;
// Python's str.isspace() set, which differs from JS \s (no U+FEFF; adds U+001C-U+001F and U+0085).
const PY_BLANK = /^[\t\n\v\f\r\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*$/;

export interface ModelFile {
  labels: string[];
  kinds: string;
  bias: number[];
  weights_f16: string;
}

export interface Model {
  labels: string[];
  kinds: string;
  bias: number[];
  w: Float32Array;
}

const CRC = new Uint32Array(256).map((_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c;
});
const UTF8 = new TextEncoder();

function crc32(s: string): number {
  let c = 0xffffffff;
  for (const b of UTF8.encode(s)) c = CRC[(c ^ b) & 0xff]! ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function f16(h: number): number {
  const e = (h >> 10) & 0x1f;
  const m = h & 0x3ff;
  const v = e === 0 ? m * 2 ** -24 : e === 31 ? (m ? NaN : Infinity) : (1 + m / 1024) * 2 ** (e - 15);
  return h & 0x8000 ? -v : v;
}

/** Hashed char 2-5-grams (+ word 1-2-grams), binary, L2-normalised; buckets in ascending order. */
export function features(text: string, kinds: string): Map<number, number> {
  const words = text.normalize("NFKC").toLowerCase().match(WORD) ?? [];
  const grams = new Set<string>();
  for (const w of words) {
    const p = [...` ${w} `]; // code points, as Python slices them
    for (let n = 2; n < 6; n++) {
      for (let i = 0; i + n <= p.length; i++) grams.add("c" + p.slice(i, i + n).join(""));
    }
  }
  if (kinds === "char+word") {
    for (const w of words) grams.add("w" + w);
    for (let i = 1; i < words.length; i++) grams.add("b" + words[i - 1] + " " + words[i]);
  }
  if (grams.size === 0) grams.add("<empty>");
  const buckets = [...new Set([...grams].map((g) => crc32(g) % BUCKETS))].sort((a, b) => a - b);
  const v = 1 / Math.sqrt(buckets.length);
  return new Map(buckets.map((b) => [b, v]));
}

export function loadModel(data: ModelFile): Model {
  const raw = Uint8Array.from(atob(data.weights_f16), (c) => c.charCodeAt(0));
  const view = new DataView(raw.buffer);
  const w = new Float32Array(raw.length / 2); // float16 values are exact in float32
  for (let i = 0; i < w.length; i++) w[i] = f16(view.getUint16(i * 2, true));
  if (w.length !== BUCKETS * data.labels.length) throw new Error("intake model: wrong weight count");
  return { labels: data.labels, kinds: data.kinds, bias: data.bias, w };
}

export function proba(model: Model, text: string): number[] {
  const k = model.labels.length;
  const z = [...model.bias];
  const head = [...text].slice(0, MAX_CHARS).join(""); // Python's text[:1000] counts code points
  for (const [idx, v] of features(head, model.kinds)) {
    const base = idx * k;
    for (let j = 0; j < k; j++) z[j] = z[j]! + model.w[base + j]! * v;
  }
  const m = Math.max(...z);
  const e = z.map((x) => Math.exp(x - m));
  let s = 0;
  for (const x of e) s += x;
  return e.map((x) => x / s);
}

export interface Prediction {
  /** Most likely label, UNKNOWN included. */
  top: string;
  probability: number;
  /** What LCC reports: the top label at probability >= threshold, never UNKNOWN; else null. */
  category: string | null;
  probabilities: number[];
}

export function classify(model: Model, text: string, threshold = THRESHOLD): Prediction | null {
  if (PY_BLANK.test(text)) return null;
  const p = proba(model, text);
  let i = 0;
  for (let j = 1; j < p.length; j++) if (p[j]! > p[i]!) i = j;
  const top = model.labels[i]!;
  const category = p[i]! < threshold || top === "UNKNOWN" ? null : top;
  return { top, probability: p[i]!, category, probabilities: p };
}
