"""Owner labelling pages for intake-distill-v1 (PROTOCOL.md: Dev and Test). Prints counts only.

    python label_page.py dev   -> ~/.lcc-private/intake-distill-v1/label_dev.html (Part R's 22, main ask pre-filled)
    python label_page.py t     -> ~/.lcc-private/intake-distill-v1/label_t.html   (T's 68, in its drawn order)

Every sentence starts as `contexto`; the owner picks a category and clicks the sentences that are not context.
No model, teacher or arm output is on the page. The page exports labels_dev.json / labels_t.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

PRIV = Path.home() / ".lcc-private"
OUT = PRIV / "intake-distill-v1"
CATS = [
    ("pedido_principal", "Pedido principal", "o que você mais precisa que seja feito"),
    ("pedido_lateral", "Pedido lateral", "pede outra coisa também"),
    ("entrega", "Entrega", "o que deve sair: formato, arquivo, lugar, público"),
    ("regra", "Regra", "restringe o como: deve, nunca, só, sem, antes de"),
    ("ruido", "Ruído", "pensando alto, enchimento, ou repete uma frase anterior sem nada novo"),
]
REASONS = ["não foi ditado", "sensível", "não tem um pedido principal"]

PAGE = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Intake: rótulos</title>
<style>
:root{--bg:#0b0f17;--card:#141b27;--ink:#e6ebf2;--mute:#8a97ab;--line:#26324a;--skip:#a33b3b;--ok:#2e8b57;
--pedido_principal:#2f6fed;--pedido_lateral:#7a4fd6;--entrega:#c47a12;--regra:#b8325a;--ruido:#55606f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.6 -apple-system,system-ui,sans-serif}
main{max-width:900px;margin:0 auto;padding:16px}
header{position:sticky;top:0;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--line);z-index:1}
.meta{color:var(--mute);font-size:14px}.text{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:12px 0;white-space:pre-wrap}
.s{cursor:pointer;border-radius:4px;padding:1px 2px;border-bottom:1px dashed #3a4a6a}.s:hover{outline:1px solid #4a5a7a}
.pal{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.pal button{margin:0;padding:8px 10px;font-size:14px;opacity:.55}
.pal button.cur{opacity:1;outline:2px solid #fff}
.actions{position:sticky;bottom:0;background:var(--bg);padding:6px 0 10px;border-top:1px solid var(--line)}
button{font:inherit;font-size:16px;border:0;border-radius:10px;padding:12px 14px;margin:6px 6px 0 0;cursor:pointer;color:#fff;background:#33415c}
button.use{background:var(--ok)}button.skip{background:var(--skip)}button:disabled{opacity:.4;cursor:not-allowed}
textarea{width:100%;height:140px;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:10px;padding:8px;font:13px monospace}
</style></head><body><main>
<header><div id="progress"></div><div class="meta">Toda frase começa como <b>contexto</b>. Escolha a categoria abaixo e clique nas frases que não são contexto; clicar de novo volta para contexto.</div><div class="pal" id="pal"></div><div class="meta" id="hint"></div></header>
<section id="card"></section>
<section><h3>Exportar</h3><button id="copy">Copiar rótulos</button><button id="download">Baixar __FILE__</button>
<p class="meta">Se copiar não funcionar, o JSON está aqui embaixo.</p><textarea id="out" readonly></textarea></section>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById("data").textContent);
const KEY = "lcc-intake-distill-" + D.pool;
let st = {}; try { st = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { st = {}; }
let unsaved = false;
function save() { try { localStorage.setItem(KEY, JSON.stringify(st)); unsaved = false; } catch (e) { unsaved = true; } render(); }
function current() { return D.items.findIndex(c => !st[c.id]); }
function exportJSON() {
  const items = D.items.filter(c => st[c.id]).map(c => Object.assign({id: c.id, sha256: c.sha256}, st[c.id]));
  return JSON.stringify({version: 1, split: D.split, items: items}, null, 1);
}
let cur = D.cats[0][0], lab = null, shown = null;
function render() {
  const pal = document.getElementById("pal"); pal.replaceChildren();
  D.cats.forEach(([k, name, hint]) => {
    const b = document.createElement("button"); b.textContent = name; b.style.background = "var(--" + k + ")";
    if (k === cur) { b.className = "cur"; document.getElementById("hint").textContent = name + ": " + hint; }
    b.onclick = () => { cur = k; render(); }; pal.append(b);
  });
  const i = current();
  if (i !== shown) { shown = i; lab = null; window.scrollTo(0, 0); }
  const done = D.items.filter(c => st[c.id]).length, kept = D.items.filter(c => st[c.id] && st[c.id].decision === "use").length;
  document.getElementById("progress").textContent = "Usados: " + kept + " | decididos: " + done + " de " + D.items.length +
    (unsaved ? " | ATENÇÃO: o navegador não está salvando; baixe os rótulos antes de fechar" : "");
  document.getElementById("out").value = exportJSON();
  const card = document.getElementById("card"); card.replaceChildren();
  const prev = i < 0 ? D.items.length - 1 : i - 1;
  const back = document.createElement("button"); back.textContent = "Desfazer o anterior";
  back.disabled = prev < 0 || !st[D.items[prev].id];
  back.onclick = () => { delete st[D.items[prev].id]; save(); };
  if (i < 0) { const p = document.createElement("p"); p.textContent = "Pronto. Baixe ou copie os rótulos abaixo."; card.append(p, back); return; }
  const c = D.items[i];
  if (lab === null) { lab = {}; (c.preset || []).forEach(k => { lab[k] = "pedido_principal"; }); }
  const meta = document.createElement("div"); meta.className = "meta";
  meta.textContent = "#" + (i + 1) + " · " + c.words + " palavras" + (c.preset ? " · pedido principal já marcado no Part R" : "");
  const box = document.createElement("div"); box.className = "text";
  const cp = Array.from(c.text), cut = (s, e) => cp.slice(s, e).join("");  // spans count code points
  let at = 0;
  c.sentences.forEach(([s, e], k) => {
    if (s > at) box.append(document.createTextNode(cut(at, s)));
    const span = document.createElement("span"); span.className = "s";
    if (lab[k]) { span.style.background = "var(--" + lab[k] + ")"; span.style.color = "#fff"; }
    span.textContent = cut(s, e);
    span.onclick = () => { lab[k] === cur ? delete lab[k] : (lab[k] = cur); render(); };
    box.append(span); at = e;
  });
  if (at < cp.length) box.append(document.createTextNode(cut(at)));
  const row = document.createElement("div"); row.className = "actions";
  const nMain = Object.values(lab).filter(v => v === "pedido_principal").length;
  const use = document.createElement("button"); use.className = "use";
  use.textContent = "Usar (" + Object.keys(lab).length + " frases fora de contexto)"; use.disabled = nMain === 0;
  use.title = nMain === 0 ? "Marque ao menos uma frase como pedido principal, ou pule" : "";
  use.onclick = () => {
    const extra = Object.values(lab).filter(v => v !== "pedido_principal").length;
    if (extra === 0 && !confirm("Só o pedido principal está marcado. Todas as outras frases são contexto (nenhuma entrega, regra, pedido lateral ou ruído)?")) return;
    const labels = Object.keys(lab).map(Number).sort((a, b) => a - b).map(k => ({span: c.sentences[k], cat: lab[k]}));
    st[c.id] = {decision: "use", labels: labels}; save();
  };
  row.append(use);
  D.reasons.forEach(r => {
    const b = document.createElement("button"); b.className = "skip"; b.textContent = "Pular: " + r;
    b.onclick = () => { st[c.id] = {decision: "skip", reason: r}; save(); }; row.append(b);
  });
  row.append(back); card.append(meta, box, row);
}
document.getElementById("copy").onclick = async () => {
  try { await navigator.clipboard.writeText(exportJSON()); } catch (e) { document.getElementById("out").select(); }
};
document.getElementById("download").onclick = () => {
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([exportJSON()], {type: "application/json"}));
  a.download = D.file; a.click();
};
render();
</script></body></html>
"""


def load(split: str) -> list[dict]:
    if split == "t":
        return json.loads((OUT / "t.json").read_text())["items"]
    cands = json.loads((PRIV / "intake-objective-v1/candidates.json").read_text())["items"]
    gold = {
        x["id"]: x
        for x in json.loads((PRIV / "intake-objective-v1/labels.json").read_text())["items"]
    }
    items = []
    for c in cands:
        g = gold.get(c["id"])
        if not g or g["decision"] != "use":
            continue
        spans = [list(s) for s in c["sentences"]]
        preset = [k for k, s in enumerate(spans) if s in [list(x) for x in g["gold"]]]
        if len(preset) != len(g["gold"]):
            raise SystemExit(
                f"refused: {c['id']} gold spans are not sentences of the pinned parser"
            )
        items.append({**c, "preset": preset})
    if len(items) != 22:
        raise SystemExit(f"refused: dev has {len(items)}, expected 22")
    return items


def main() -> None:
    split = sys.argv[1] if len(sys.argv) == 2 else ""
    if split not in ("dev", "t"):
        raise SystemExit("usage: label_page.py dev|t")
    items = [
        {k: c[k] for k in ("id", "sha256", "words", "text", "sentences", "preset") if k in c}
        for c in load(split)
    ]
    # Keyed to texts and sentence spans: a page with another split starts fresh in the browser.
    pool = hashlib.sha256(
        json.dumps([(c["sha256"], c["sentences"]) for c in items]).encode()
    ).hexdigest()[:16]
    name = f"labels_{split}.json"
    data = {"split": split, "pool": pool, "file": name, "cats": CATS, "items": items,
            "reasons": REASONS if split == "t" else []}  # fmt: skip
    # No "<" may reach the script block raw: message text could otherwise end or reopen it.
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    path = OUT / f"label_{split}.html"
    tmp = path.with_suffix(".html.tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(PAGE.replace("__FILE__", name).replace("__DATA__", payload))
    os.replace(
        tmp, path
    )  # the page holds no labels; progress lives in the browser, keyed to the pool
    print(f"{path.name}: {len(items)} items, {sum(len(c['sentences']) for c in items)} sentences")


if __name__ == "__main__":
    main()
