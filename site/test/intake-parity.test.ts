// The TypeScript intake judge must answer like lcc.intake.category on every fixture prompt.
// Expectations come from Python (tests/test_site_intake_fixture.py keeps them current).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { classify, loadModel } from "../src/lib/intake.ts";

const read = (p: string) => JSON.parse(readFileSync(new URL(p, import.meta.url), "utf8"));
const model = loadModel(read("../../src/lcc/intake/intake_category_v1.json"));
const items: { prompt: string; expected: { top: string; category: string | null; probabilities: number[] } | null }[] =
  read("./intake-parity.json");

test("fixture is not trivial", () => {
  assert.ok(items.length >= 30);
  assert.ok(items.some((i) => i.expected?.category));
  assert.ok(items.some((i) => i.expected && !i.expected.category));
  assert.ok(items.some((i) => i.expected === null));
});

for (const { prompt, expected } of items) {
  test(`same answer as Python: ${JSON.stringify(prompt.slice(0, 40))}`, () => {
    const got = classify(model, prompt);
    if (expected === null) return assert.equal(got, null);
    assert.ok(got);
    assert.equal(got.top, expected.top);
    assert.equal(got.category, expected.category);
    got.probabilities.forEach((p, i) => assert.ok(Math.abs(p - expected.probabilities[i]!) < 1e-12));
  });
}
