"""The annotation tool: one self-contained HTML page per annotator and batch (J02).

Two annotators label each item independently, blinded to every system's output (protocol §4.3;
``docs/paper/ANNOTATION_GUIDELINE.md``). ``build`` writes a page that shows, per item, the
issue, the candidate patch, the gold patch, the tests the maintainers added and what the
automatic tiers found, and nothing else: items are built from an allow-list, as J01's sealed
inputs are, so a system's verdict cannot reach an annotator by an extra field.

Each annotator gets the items in their own order (from a seed), so neither works through them
in the same sequence. The page keeps answers in the browser as they are given and exports them
as the JSONL ``repro_bench.labels`` reads. It runs from a file with no server and no network:
the batch is embedded, and every text from a task is shown as text, never as HTML.

    uv run python -m repro_bench.annotate build --items <jsonl> --annotator A1 --seed <s>
        --out A1.html
"""

import argparse
import hashlib
import html
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from repro_bench.labels import DEFECTS, LABELS, PSEUDONYM, LabelError

#: What an annotator may see: the task and the ground-truth tiers, never a system's output.
SHOWN: Final = (
    "item",
    "repo",
    "problem_statement",
    "candidate_patch",
    "gold_patch",
    "test_patch",
    "tiers",
)


def blinded(record: Mapping[str, Any]) -> dict[str, Any]:
    """An item with the allowed fields alone; anything else is refused, not dropped, so a
    batch made with a system's output in it is noticed."""
    extra = sorted(set(record) - set(SHOWN))
    if extra:
        raise LabelError(f"{record.get('item')}: fields an annotator may not see: {extra}")
    for key in ("item", "problem_statement", "candidate_patch", "gold_patch"):
        if not isinstance(record.get(key), str) or not record[key]:
            raise LabelError(f"an item needs {key}")
    return {key: record[key] for key in SHOWN if key in record}


def ordered(
    items: Sequence[Mapping[str, Any]], annotator: str, seed: str
) -> list[Mapping[str, Any]]:
    """The annotator's own order: by SHA-256 of the seed, the annotator and the item."""
    return sorted(
        items,
        key=lambda i: hashlib.sha256(f"{seed}\0{annotator}\0{i['item']}".encode()).hexdigest(),
    )


def _embedded(value: Any) -> str:
    """JSON safe inside a ``<script>`` element: no ``<``, ``>`` or ``&`` as themselves."""
    text = json.dumps(value, sort_keys=True, ensure_ascii=True)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


PAGE: Final = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Repro annotation</title>
<style>
:root { --bg: #fbfaf7; --fg: #1c1b19; --muted: #6b6760; --line: #dedad2; --panel: #ffffff;
  --accent: #1f5f8b; --add: #e6f4ea; --del: #fbe9e7; }
@media (prefers-color-scheme: dark) { :root { --bg: #161513; --fg: #ecebe8; --muted: #a29e96;
  --line: #34322e; --panel: #1f1e1b; --accent: #7fb6dc; --add: #183522; --del: #3a1d19; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
header, main { max-width: 1100px; margin: 0 auto; padding: 16px; }
header { display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
  border-bottom: 1px solid var(--line); }
header h1 { font-size: 17px; margin: 0 auto 0 0; }
button, select { font: inherit; padding: 6px 12px; border-radius: 6px;
  border: 1px solid var(--line); background: var(--panel); color: var(--fg); cursor: pointer; }
button.primary { background: var(--accent); color: var(--bg); border-color: var(--accent); }
section { background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
  padding: 12px 16px; margin: 12px 0; }
h2 { font-size: 14px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted);
  margin: 0 0 8px; }
pre { margin: 0; overflow-x: auto; white-space: pre; font: 13px/1.45 ui-monospace, Consolas,
  monospace; max-height: 480px; }
pre.text { white-space: pre-wrap; overflow-wrap: anywhere; }
.add { background: var(--add); display: block; } .del { background: var(--del); display: block; }
fieldset { border: 0; padding: 0; margin: 0 0 12px; display: flex; flex-wrap: wrap; gap: 16px; }
textarea { width: 100%; min-height: 90px; font: inherit; padding: 8px; border-radius: 6px;
  border: 1px solid var(--line); background: var(--bg); color: var(--fg); }
.meta { color: var(--muted); font-size: 13px; }
</style>
</head>
<body>
<header>
  <h1>Annotation · <span id="who"></span></h1>
  <span class="meta" id="progress"></span>
  <button id="prev">Previous</button>
  <select id="jump" aria-label="Item"></select>
  <button id="next">Next</button>
  <button class="primary" id="export">Export labels</button>
</header>
<main>
  <p class="meta">Follow the annotation guideline. Decide from the issue and the patches:
  <em>would the issue's author accept this as fixing the issue without breaking documented
  behaviour?</em> Answers are kept in this browser until you export them.</p>
  <section><h2>Your label</h2>
    <fieldset id="labels"></fieldset>
    <label>Defect class (INCORRECT only)
      <select id="defect"><option value="">—</option></select></label>
    <p><label>Rationale<br><textarea id="rationale"></textarea></label></p>
  </section>
  <section><h2>Issue</h2><pre class="text" id="problem_statement"></pre></section>
  <section><h2>Candidate patch</h2><pre id="candidate_patch"></pre></section>
  <section><h2>Gold patch (maintainers' fix)</h2><pre id="gold_patch"></pre></section>
  <section><h2>Tests the maintainers added</h2><pre id="test_patch"></pre></section>
  <section><h2>Automatic tiers</h2><pre class="text" id="tiers"></pre></section>
</main>
<script type="application/json" id="batch">__BATCH__</script>
<script>
"use strict";
const batch = JSON.parse(document.getElementById("batch").textContent);
const LABELS = __LABELS__, DEFECTS = __DEFECTS__;
const store = "repro-annotation:" + batch.digest + ":" + batch.annotator;
let answers = {};
try { answers = JSON.parse(localStorage.getItem(store) || "{}"); } catch (e) { answers = {}; }
let at = 0;
const $ = (id) => document.getElementById(id);
$("who").textContent = batch.annotator + " · " + batch.items.length + " items";
function save() { try { localStorage.setItem(store, JSON.stringify(answers)); } catch (e) {} }
function diff(node, text) {
  node.replaceChildren();
  for (const line of (text || "").split("\\n")) {
    const span = document.createElement("span");
    if (line.startsWith("+") && !line.startsWith("+++")) span.className = "add";
    else if (line.startsWith("-") && !line.startsWith("---")) span.className = "del";
    span.textContent = line + "\\n";
    node.appendChild(span);
  }
}
for (const label of LABELS) {
  const wrap = document.createElement("label");
  const input = document.createElement("input");
  input.type = "radio"; input.name = "label"; input.value = label;
  input.addEventListener("change", () => { record(); });
  wrap.append(input, " " + label);
  $("labels").appendChild(wrap);
}
for (const defect of DEFECTS) {
  const option = document.createElement("option");
  option.value = defect; option.textContent = defect;
  $("defect").appendChild(option);
}
batch.items.forEach((item, i) => {
  const option = document.createElement("option");
  option.value = String(i); option.textContent = (i + 1) + ". " + item.item;
  $("jump").appendChild(option);
});
function record() {
  const item = batch.items[at].item;
  const chosen = document.querySelector("input[name=label]:checked");
  answers[item] = { label: chosen ? chosen.value : "", defect: $("defect").value,
    rationale: $("rationale").value };
  save(); progress();
}
function progress() {
  const done = batch.items.filter((i) => (answers[i.item] || {}).label).length;
  $("progress").textContent = done + " of " + batch.items.length + " labelled";
}
function show(i) {
  at = Math.max(0, Math.min(batch.items.length - 1, i));
  const item = batch.items[at];
  $("jump").value = String(at);
  $("problem_statement").textContent = item.problem_statement;
  diff($("candidate_patch"), item.candidate_patch);
  diff($("gold_patch"), item.gold_patch);
  diff($("test_patch"), item.test_patch || "");
  $("tiers").textContent = JSON.stringify(item.tiers || {}, null, 2);
  const answer = answers[item.item] || {};
  for (const input of document.querySelectorAll("input[name=label]"))
    input.checked = input.value === answer.label;
  $("defect").value = answer.defect || "";
  $("rationale").value = answer.rationale || "";
  progress(); window.scrollTo(0, 0);
}
$("defect").addEventListener("change", record);
$("rationale").addEventListener("input", record);
$("prev").addEventListener("click", () => show(at - 1));
$("next").addEventListener("click", () => show(at + 1));
$("jump").addEventListener("change", (e) => show(Number(e.target.value)));
$("export").addEventListener("click", () => {
  const lines = [];
  for (const item of batch.items) {
    const answer = answers[item.item];
    if (!answer || !answer.label) continue;
    lines.push(JSON.stringify({ item: item.item, annotator: batch.annotator,
      label: answer.label, defect: answer.label === "INCORRECT" ? (answer.defect || null) : null,
      rationale: answer.rationale || "" }));
  }
  const blob = new Blob([lines.join("\\n") + "\\n"], { type: "application/x-ndjson" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = batch.annotator + "-" + batch.digest.slice(0, 12) + ".jsonl";
  link.click();
});
show(0);
</script>
</body>
</html>
"""


def page(items: Sequence[Mapping[str, Any]], annotator: str, seed: str) -> str:
    """The annotator's page for ``items``."""
    if not PSEUDONYM.match(annotator):
        raise LabelError(f"annotator {annotator!r} is not a pseudonym (A1, A2)")
    shown = [blinded(item) for item in items]
    if len({item["item"] for item in shown}) != len(shown):
        raise LabelError("an item appears twice in the batch")
    digest = hashlib.sha256(_embedded(sorted(shown, key=lambda i: i["item"])).encode()).hexdigest()
    batch = {"annotator": annotator, "digest": digest, "items": ordered(shown, annotator, seed)}
    return (
        PAGE.replace("__BATCH__", _embedded(batch))
        .replace("__LABELS__", json.dumps(list(LABELS)))
        .replace("__DEFECTS__", json.dumps(list(DEFECTS)))
        .replace(
            "<title>Repro annotation</title>",
            f"<title>Repro annotation {html.escape(annotator)}</title>",
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="an annotator's page for a batch")
    build.add_argument("--items", type=Path, required=True, help="JSONL, one item a line")
    build.add_argument("--annotator", required=True, help="a pseudonym: A1, A2")
    build.add_argument("--seed", required=True, help="the batch's ordering seed")
    build.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        lines = args.items.read_text(encoding="utf-8").splitlines()
        items = [json.loads(line) for line in lines if line.strip()]
        args.out.write_bytes(page(items, args.annotator, args.seed).encode("utf-8"))
    except (LabelError, ValueError, OSError) as exc:
        sys.stderr.write(f"repro_bench.annotate: {exc}\n")
        return 1
    sys.stdout.write(f"{len(items)} items for {args.annotator} in {args.out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
