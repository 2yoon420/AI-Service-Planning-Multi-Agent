"""산출물 루브릭 채점 화면을 만든다 (사람용).

## 설계에서 지킨 것

**① 내 채점 결과를 파일에 넣지 않는다.** 정렬도 실험에서 검증기 점수를 라벨러에게
숨겼던 것과 같은 통제다. 먼저 본 점수가 있으면 판단이 그리로 끌려간다(anchoring).
**두 채점이 독립이어야 κ가 의미를 갖는다.**

**② 문서 본문을 화면 안에 넣는다.** *"출처에 조회일이 표기되어 있는가"* 같은 항목은
문서를 뒤져야 답할 수 있다. docx를 따로 열어 왔다 갔다 하면 채점이 느려지고 실수가
는다. 페이지 안에서 `Ctrl+F`로 찾을 수 있게 한다.

**③ 진행분을 잃지 않는다.** 이전 라벨링 도구에서 **창을 닫자 진행분이 사라진** 적이
있다. `localStorage`에 매 클릭마다 저장하고, 다운로드 버튼을 항상 노출한다.

**④ '모름'을 허용한다.** 억지로 예/아니오를 고르게 하면 애매한 것이 한쪽으로 쏠린다.
모름은 κ 계산에서 제외하고 건수를 따로 보고한다 — 정렬도 실험에서 3점 구간이
알려준 것이다.
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval.rubric.hisrubric import DOCS, ITEMS, RUNGS  # noqa: E402

OUT = Path("eval/rubric/scoring.html")
DOC_DIR = Path("outputs/v2")


def doc_text(fragment: str) -> tuple[str, str]:
    hits = [p for p in sorted(DOC_DIR.glob("*.docx")) if fragment in p.name]
    if not hits:
        return "(문서를 찾지 못했습니다)", ""
    p = hits[0]
    txt = subprocess.run(["pandoc", "-t", "plain", str(p)],
                         capture_output=True, text=True).stdout
    return txt, p.name


def build() -> str:
    docs = []
    for alias, frag in DOCS:
        txt, fname = doc_text(frag)
        docs.append({"alias": alias, "file": fname, "text": txt})

    items_js = json.dumps([{
        "no": i.no, "rung": i.rung, "chapter": i.chapter,
        "text": i.text, "hint": i.hint, "ext": i.needs_external,
    } for i in ITEMS], ensure_ascii=False)
    docs_js = json.dumps([{"alias": d["alias"], "file": d["file"]} for d in docs],
                         ensure_ascii=False)
    bodies = "\n".join(
        f'<pre class="doc" id="doc-{i}" hidden>{html.escape(d["text"])}</pre>'
        for i, d in enumerate(docs))

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>산출물 루브릭 채점</title>
<style>
 body{{font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',sans-serif;
   margin:0;background:#f6f7f9;color:#1a1a1a;font-size:14px}}
 header{{position:sticky;top:0;background:#fff;border-bottom:1px solid #ddd;
   padding:12px 20px;z-index:10;display:flex;gap:16px;align-items:center;flex-wrap:wrap}}
 h1{{font-size:16px;margin:0}}
 .tab{{padding:6px 14px;border:1px solid #ccc;border-radius:6px;background:#fff;cursor:pointer}}
 .tab.on{{background:#1a1a1a;color:#fff;border-color:#1a1a1a}}
 .prog{{margin-left:auto;font-variant-numeric:tabular-nums;color:#555}}
 button.dl{{padding:6px 14px;border:1px solid #1a6;border-radius:6px;background:#1a6;color:#fff;cursor:pointer}}
 main{{display:grid;grid-template-columns:1fr 1fr;gap:0;height:calc(100vh - 58px)}}
 .pane{{overflow:auto;padding:16px 20px}}
 .pane.left{{border-right:1px solid #ddd;background:#fff}}
 pre.doc{{white-space:pre-wrap;font-family:ui-monospace,Menlo,monospace;font-size:12px;
   line-height:1.6;margin:0}}
 .rung{{margin:18px 0 8px;font-weight:700;font-size:13px;color:#444;
   border-bottom:2px solid #1a1a1a;padding-bottom:4px}}
 .item{{background:#fff;border:1px solid #e2e2e2;border-radius:8px;padding:10px 12px;margin-bottom:8px}}
 .item.done{{border-color:#bbb;background:#fafafa}}
 .no{{color:#888;font-size:12px}}
 .ch{{display:inline-block;background:#eef;color:#446;border-radius:4px;padding:1px 6px;font-size:11px;margin-left:6px}}
 .ext{{background:#fee;color:#a33}}
 .txt{{margin:4px 0 6px;font-weight:600}}
 .hint{{color:#666;font-size:12px;margin-bottom:8px}}
 .btns{{display:flex;gap:6px}}
 .btns button{{flex:0 0 auto;padding:5px 16px;border:1px solid #ccc;border-radius:6px;
   background:#fff;cursor:pointer;font-size:13px}}
 .btns button.yes.on{{background:#1a6;color:#fff;border-color:#1a6}}
 .btns button.no.on{{background:#c33;color:#fff;border-color:#c33}}
 .btns button.unk.on{{background:#888;color:#fff;border-color:#888}}
 .note{{background:#fffbe6;border:1px solid #e8d98a;border-radius:8px;padding:10px 12px;
   margin-bottom:12px;font-size:13px;line-height:1.6}}
</style></head><body>
<header>
 <h1>산출물 루브릭 채점</h1>
 <div id="tabs"></div>
 <span class="prog" id="prog"></span>
 <button class="dl" onclick="download()">JSON 내려받기</button>
</header>
<main>
 <div class="pane left" id="left">{bodies}</div>
 <div class="pane" id="right"></div>
</main>
<script>
const ITEMS = {items_js};
const DOCS  = {docs_js};
const KEY = "rubric_scores_v1";
let cur = 0;
let S = JSON.parse(localStorage.getItem(KEY) || "{{}}");

function save() {{ localStorage.setItem(KEY, JSON.stringify(S)); }}
function set(d, no, v) {{
  S[d] = S[d] || {{}};
  S[d][no] = (S[d][no] === v) ? null : v;
  save(); render();
}}
function count() {{
  let done = 0;
  DOCS.forEach((d, i) => ITEMS.forEach(it => {{ if (S[i] && S[i][it.no]) done++; }}));
  return done;
}}
function renderTabs() {{
  document.getElementById("tabs").innerHTML = DOCS.map((d, i) => {{
    const n = ITEMS.filter(it => S[i] && S[i][it.no]).length;
    return `<button class="tab ${{i===cur?'on':''}}" onclick="pick(${{i}})">${{d.alias}} (${{n}}/32)</button>`;
  }}).join(" ");
}}
function pick(i) {{
  cur = i;
  DOCS.forEach((_, k) => document.getElementById("doc-"+k).hidden = (k !== i));
  render();
}}
function render() {{
  renderTabs();
  document.getElementById("prog").textContent = `진행 ${{count()}} / ${{DOCS.length*32}}`;
  const RUNGS = {json.dumps(RUNGS, ensure_ascii=False)};
  let h = `<div class="note"><b>${{DOCS[cur].alias}}</b> — ${{DOCS[cur].file}}<br>
    왼쪽에 문서 본문이 있습니다. <b>Ctrl+F</b>(맥은 <b>⌘F</b>)로 찾으면 빠릅니다.<br>
    애매하면 <b>모름</b>을 누르십시오 — 억지로 고르면 한쪽으로 쏠립니다.
    모름은 일치도 계산에서 제외하고 건수만 따로 봅니다.</div>`;
  RUNGS.forEach(r => {{
    h += `<div class="rung">${{r}}</div>`;
    ITEMS.filter(it => it.rung === r).forEach(it => {{
      const v = (S[cur] || {{}})[it.no] || null;
      h += `<div class="item ${{v?'done':''}}">
        <span class="no">${{it.no}}.</span>
        <span class="ch ${{it.ext?'ext':''}}">${{it.chapter}}${{it.ext?' · 외부확인 필요':''}}</span>
        <div class="txt">${{it.text}}</div>
        ${{it.hint ? `<div class="hint">→ ${{it.hint}}</div>` : ""}}
        <div class="btns">
          <button class="yes ${{v==='yes'?'on':''}}" onclick="set(${{cur}},${{it.no}},'yes')">예</button>
          <button class="no  ${{v==='no' ?'on':''}}" onclick="set(${{cur}},${{it.no}},'no')">아니오</button>
          <button class="unk ${{v==='unk'?'on':''}}" onclick="set(${{cur}},${{it.no}},'unk')">모름</button>
        </div></div>`;
    }});
  }});
  document.getElementById("right").innerHTML = h;
}}
function download() {{
  const out = {{ labeler: "이후윤", labeled_at: new Date().toISOString(),
    rubric: "hisrubric v1 (32항목)", scores: {{}} }};
  DOCS.forEach((d, i) => {{ out.scores[d.alias] = S[i] || {{}}; }});
  const b = new Blob([JSON.stringify(out, null, 2)], {{type:"application/json"}});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(b); a.download = "rubric_human.json"; a.click();
}}
pick(0);
</script></body></html>"""


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    print(f"생성: {OUT}  ({OUT.stat().st_size/1024:.0f} KB)")
    print(f"항목 {len(ITEMS)} × 문서 {len(DOCS)} = {len(ITEMS)*len(DOCS)}칸")
