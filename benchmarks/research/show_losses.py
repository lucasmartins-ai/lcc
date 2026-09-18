"""Show exactly which categorized item each arm loses, per scale."""

import importlib.util
import json
import pathlib
import re
import sys

sys.path.insert(0, ".")
spec = importlib.util.spec_from_file_location("_rm", "run_matrix.py")
m = importlib.util.module_from_spec(spec)
sys.modules["_rm"] = m
spec.loader.exec_module(m)

rows = [json.loads(l) for l in pathlib.Path("results/matrix.jsonl").read_text().splitlines()]
index = json.loads(pathlib.Path("corpora/index.json").read_text())

print(f"{'arm':24} {'escala':7} {'categoria perdida':22} marcador")
print("-" * 90)
seen: set[tuple[str, str]] = set()
for row in rows:
    scale, arm = row["scale"], row["arm"]
    out = pathlib.Path(f"work/{scale}/{arm}/context.md")
    if not out.exists():
        continue
    text = out.read_text(encoding="utf-8")
    for item in index[scale]["items"]:
        if not re.search(item["marker"], text):
            key = (arm, item["category"])
            if key in seen:
                continue
            seen.add(key)
            print(f"{arm:24} {scale:7} {item['category']:22} {item['marker']}")
