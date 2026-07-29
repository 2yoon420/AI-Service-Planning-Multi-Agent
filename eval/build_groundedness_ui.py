"""근거지지도 라벨링 화면(단일 HTML)을 생성한다.

실행:
    python eval/build_groundedness_ui.py
    # → eval/label/groundedness_labeling.html  (브라우저로 열어 라벨링)

## 왜 생성기로 만드는가

HTML을 손으로 쓰면 결합 규칙(`groundedness_scale.COMBINE`)이 JS 쪽에 복사되고,
Python 표를 고칠 때 JS가 남는다. **표를 Python에서 읽어 JS로 심는다** —
단일 진실 원천이다. 51절에서 "결합을 코드로 고정한다"고 한 이유와 같다.

## 화면이 지키는 것

1. **기계 점수를 보여주지 않는다.** `_machine_*` 필드는 주입 단계에서 제거한다.
   보이면 앵커링이 생기고(Tversky & Kahneman 1974), 그러면 정렬도 측정이 무의미해진다.
   더 나쁘게는 A/B 비교에서 "보여준 조건이 이긴다".
2. **② 는 후보 대조 결과로 미리 채워두고 사람이 덮어쓸 수 있게 한다.**
   3,000자를 통독하지 않게 하려는 것이고, 코드가 확정하지 않게 하려는 것이다.
3. **원문에서 찾은 후보를 강조 표시한다.** 눈이 갈 자리를 알려준다.
4. **애매함 표시**를 남길 수 있다. 51절에서 "사람도 애매하다고 한 항목"을 따로
   집계해 자기 착오 3건을 찾아냈다.
5. **자동 저장**(localStorage). 50건은 한 시간이 걸리고, 새로 고침 한 번에 잃으면 안 된다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from eval.groundedness_scale import (
    ACCEPT_MIN_SCORE, CLAIM_HELP, COMBINE, NUMERIC_HELP, REJECT_MAX_SCORE,
)

SRC = Path("eval/label/groundedness_sample.json")
OUT = Path("eval/label/groundedness_labeling.html")

CLAIMS = ["예", "부분", "아니오"]
NUMERICS = ["있음", "일부", "없음", "해당없음"]


def prefill_numeric(cands: list[dict]) -> str:
    """후보 대조 결과로 ②의 초기값을 정한다."""
    if not cands:
        return "해당없음"
    hit = sum(1 for c in cands if c["verbatim"])
    if hit == len(cands):
        return "있음"
    if hit == 0:
        return "없음"
    return "일부"


def strip_machine(item: dict) -> dict:
    """기계 점수를 지운다 — 화면에 새어 나가면 실험이 무효가 된다."""
    return {k: v for k, v in item.items() if not k.startswith("_")}


HTML = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>근거지지도 라벨링</title>
<style>
 *{box-sizing:border-box}
 body{font:15px/1.65 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif;
      margin:0;background:#f5f5f4;color:#1c1917}
 header{position:sticky;top:0;background:#1c1917;color:#fafaf9;padding:10px 18px;z-index:9;
        display:flex;gap:16px;align-items:center;flex-wrap:wrap}
 header b{font-size:16px}
 .bar{flex:1;min-width:140px;height:7px;background:#44403c;border-radius:4px;overflow:hidden}
 .bar>i{display:block;height:100%;background:#22c55e;width:0}
 main{max-width:1080px;margin:0 auto;padding:18px}
 .card{background:#fff;border:1px solid #e7e5e4;border-radius:10px;padding:16px 18px;margin-bottom:14px}
 .meta{font-size:12.5px;color:#78716c;margin-bottom:8px}
 .fact{font-size:17px;font-weight:600;line-height:1.6;margin:6px 0 2px}
 h3{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:#78716c;margin:0 0 8px}
 .exc{max-height:340px;overflow:auto;background:#fafaf9;border:1px solid #e7e5e4;
      border-radius:8px;padding:12px;font-size:13.5px;line-height:1.75;white-space:pre-wrap}
 mark{background:#fde68a;padding:0 1px;border-radius:2px}
 .tok{display:flex;flex-wrap:wrap;gap:6px;margin:2px 0 10px}
 .tok span{font-size:12.5px;padding:3px 8px;border-radius:999px;border:1px solid}
 .ok{background:#f0fdf4;border-color:#bbf7d0;color:#15803d}
 .ng{background:#fef2f2;border-color:#fecaca;color:#b91c1c}
 .near{font-size:12.5px;color:#78716c;background:#fafaf9;border-left:3px solid #d6d3d1;
       padding:6px 10px;margin:4px 0;border-radius:0 6px 6px 0}
 .q{margin:14px 0 4px;font-weight:600}
 .opts{display:flex;gap:8px;flex-wrap:wrap}
 button.opt{font:inherit;padding:9px 15px;border:1.5px solid #d6d3d1;background:#fff;
            border-radius:8px;cursor:pointer;text-align:left}
 button.opt:hover{border-color:#a8a29e}
 button.opt.sel{border-color:#1c1917;background:#1c1917;color:#fff}
 button.opt small{display:block;font-size:11.5px;opacity:.7;font-weight:400}
 .res{font-size:14px;padding:10px 14px;border-radius:8px;background:#fafaf9;
      border:1px solid #e7e5e4;margin-top:12px}
 .res b{font-size:19px}
 .nav{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
 .nav button,.tools button{font:inherit;padding:8px 14px;border-radius:8px;cursor:pointer;
   border:1px solid #d6d3d1;background:#fff}
 .tools{display:flex;gap:8px;margin-top:6px;flex-wrap:wrap}
 .tools button.pri{background:#1c1917;color:#fff;border-color:#1c1917}
 .flag.on{background:#fef3c7;border-color:#fcd34d}
 textarea{width:100%;font:inherit;font-size:13.5px;padding:8px;border:1px solid #d6d3d1;
          border-radius:8px;min-height:42px;resize:vertical}
 .kbd{font-size:12px;color:#78716c;margin-top:10px}
 .kbd code{background:#f5f5f4;border:1px solid #e7e5e4;border-radius:4px;padding:1px 5px}
 .warn{background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:10px 14px;
       font-size:13.5px;margin-bottom:14px}
</style></head><body>
<header>
  <b>근거지지도 라벨링</b>
  <span id="pos"></span>
  <div class="bar"><i id="pbar"></i></div>
  <span id="cnt"></span>
</header>
<main>
 <div class="warn">
  <b>검증기 점수는 일부러 보여드리지 않습니다.</b> 먼저 보시면 판단이 그쪽으로 끌려
  정렬도 측정이 무의미해집니다. 라벨링을 마치신 뒤 대조 화면에서 전부 보여드립니다.
 </div>
 <div class="card">
   <div class="meta" id="meta"></div>
   <div class="fact" id="fact"></div>
 </div>
 <div class="card">
   <h3>출처 원문 — 검증기가 실제로 본 것</h3>
   <div class="exc" id="exc"></div>
 </div>
 <div class="card">
   <h3>수치·고유명사 대조 (코드가 미리 찾아둔 것)</h3>
   <div class="tok" id="tok"></div>
   <div id="nears"></div>
   <div class="q">① fact의 <u>핵심 주장</u>이 원문에 있는가?</div>
   <div class="opts" id="q1"></div>
   <div class="q">② fact의 <u>구체 수치·고유명사</u>가 원문에 있는가?</div>
   <div class="opts" id="q2"></div>
   <div class="res" id="res"></div>
   <div class="q">메모 (선택)</div>
   <textarea id="note" placeholder="애매했던 이유, 판단 근거 등"></textarea>
   <div class="kbd">
     단축키 — ① <code>1</code><code>2</code><code>3</code> ·
     ② <code>Q</code><code>W</code><code>E</code><code>R</code> ·
     이동 <code>←</code><code>→</code> · 애매함 <code>/</code>
   </div>
 </div>
 <div class="card">
   <div class="nav">
     <button id="prev">← 이전</button>
     <button id="next">다음 →</button>
     <button id="flag" class="flag">애매함 표시</button>
     <span id="fstat" class="meta"></span>
   </div>
   <div class="tools">
     <button id="save" class="pri">JSON 내보내기</button>
     <button id="jump">라벨 안 된 첫 항목으로</button>
     <button id="reset">전체 지우기</button>
   </div>
 </div>
</main>
<script>
const DATA = __DATA__;
const COMBINE = __COMBINE__;
const CLAIMS = __CLAIMS__, NUMERICS = __NUMERICS__;
const CLAIM_HELP = __CLAIM_HELP__, NUMERIC_HELP = __NUMERIC_HELP__;
const ACCEPT = __ACCEPT__, REJECT = __REJECT__;
const KEY = "gnd_labels_v1";
let L = {}, idx = 0;
try { L = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch(e) { L = {}; }

function cur(){ return DATA.items[idx]; }
function rec(){ const it=cur(); if(!L[it.id]) L[it.id]={numeric_scope: it.prefill_numeric}; return L[it.id]; }
function persist(){ try{ localStorage.setItem(KEY, JSON.stringify(L)); }catch(e){} }
function done(){ return DATA.items.filter(x => L[x.id] && L[x.id].claim_scope).length; }

function esc(s){ return (s||"").replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

function highlight(text, cands){
  let html = esc(text);
  const found = cands.filter(c=>c.verbatim).map(c=>c.token)
                     .sort((a,b)=>b.length-a.length);
  for (const t of found){
    const pat = t.split("").map(ch=>esc(ch).replace(/[.*+?^${}()|[\]\\]/g,"\\$&")).join("[\\s,]*");
    html = html.replace(new RegExp(pat,"g"), m=>"\u0001"+m+"\u0002");
  }
  // \u0001/\u0002 는 자리표시자다. esc() 로 이스케이프한 뒤에 태그를 넣어야
  // 하는데, 태그를 바로 삽입하면 다음 토큰 치환이 태그 안쪽을 건드린다.
  return html.replace(/\u0001/g,"<mark>").replace(/\u0002/g,"</mark>");
}

function render(){
  const it = cur(), c = rec();
  document.getElementById("pos").textContent = `${idx+1} / ${DATA.items.length}`;
  document.getElementById("cnt").textContent = `완료 ${done()}건`;
  document.getElementById("pbar").style.width = (done()/DATA.items.length*100)+"%";
  document.getElementById("meta").innerHTML =
    `${esc(it.topic)} · ${esc(it.region||"지역 미상")} · <a href="${esc(it.source_url)}" target="_blank">출처</a>`
    + `<br>리서치 질문: ${esc(it.topic_relevance)}`;
  document.getElementById("fact").innerHTML = highlight(it.text, it.token_candidates);
  document.getElementById("exc").innerHTML = highlight(it.source_excerpt, it.token_candidates);

  const tk = document.getElementById("tok");
  tk.innerHTML = it.token_candidates.length
    ? it.token_candidates.map(t =>
        `<span class="${t.verbatim?'ok':'ng'}">${t.verbatim?'○':'✕'} ${esc(t.token)}</span>`).join("")
    : `<span class="meta">대조할 수치·고유명사가 없습니다 → ② 는 "해당없음"</span>`;

  document.getElementById("nears").innerHTML = it.token_candidates
    .filter(t=>!t.verbatim && t.near && t.near.length)
    .map(t=>`<div class="near"><b>${esc(t.token)}</b> — 원문에 그대로는 없으나 비슷한 표기가 있습니다:<br>`
            + t.near.map(h=>"…"+esc(h)+"…").join("<br>") + `</div>`).join("");

  const mk = (host, opts, help, field) => {
    host.innerHTML = opts.map(o =>
      `<button class="opt ${c[field]===o?'sel':''}" data-f="${field}" data-v="${o}">`
      + `${o}<small>${esc(help[o])}</small></button>`).join("");
  };
  mk(document.getElementById("q1"), CLAIMS, CLAIM_HELP, "claim_scope");
  mk(document.getElementById("q2"), NUMERICS, NUMERIC_HELP, "numeric_scope");
  document.querySelectorAll("button.opt").forEach(b =>
    b.onclick = () => pick(b.dataset.f, b.dataset.v));

  const res = document.getElementById("res");
  if (c.claim_scope && c.numeric_scope){
    const s = COMBINE[c.claim_scope + "|" + c.numeric_scope];
    const st = s>=ACCEPT ? "채택" : (s<=REJECT ? "기각" : "보류");
    res.innerHTML = `환산 결과 → <b>${s}점</b> (${st})`;
  } else {
    res.innerHTML = `<span class="meta">두 질문에 모두 답하시면 점수가 환산됩니다</span>`;
  }
  document.getElementById("note").value = c.note || "";
  const f = document.getElementById("flag");
  f.classList.toggle("on", !!c.uncertain);
  document.getElementById("fstat").textContent = c.uncertain ? "애매함으로 표시됨" : "";
}

function pick(field, v){ rec()[field] = v; persist(); render(); }

document.getElementById("note").addEventListener("input", e => { rec().note = e.target.value; persist(); });
document.getElementById("prev").onclick = () => { if(idx>0){ idx--; render(); window.scrollTo(0,0);} };
document.getElementById("next").onclick = () => { if(idx<DATA.items.length-1){ idx++; render(); window.scrollTo(0,0);} };
document.getElementById("flag").onclick = () => { const c=rec(); c.uncertain=!c.uncertain; persist(); render(); };
document.getElementById("jump").onclick = () => {
  const i = DATA.items.findIndex(x => !(L[x.id] && L[x.id].claim_scope));
  if (i>=0){ idx=i; render(); window.scrollTo(0,0); } else alert("모두 라벨했습니다.");
};
document.getElementById("reset").onclick = () => {
  if (confirm("라벨을 전부 지웁니다. 계속할까요?")){ L={}; persist(); render(); }
};
document.getElementById("save").onclick = () => {
  const labels = DATA.items.filter(x=>L[x.id] && L[x.id].claim_scope).map(x => {
    const c = L[x.id];
    return { id:x.id, topic:x.topic, text:x.text,
             claim_scope:c.claim_scope, numeric_scope:c.numeric_scope,
             human_groundedness: COMBINE[c.claim_scope+"|"+c.numeric_scope],
             uncertain: !!c.uncertain, note: c.note || "" };
  });
  const payload = { labeled_at:new Date().toISOString(), axis:"groundedness",
    method:"분해 척도 (핵심 주장 + 수치·고유명사 → 코드가 환산). ②는 코드가 후보를 제시하고 사람이 확정 — 반자동.",
    labeler:"이후윤", n:labels.length, sample:DATA.sample_meta, labels };
  const blob = new Blob([JSON.stringify(payload,null,1)], {type:"application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "groundedness_labels.json";
  document.body.appendChild(a); a.click(); a.remove();
};
document.addEventListener("keydown", e => {
  if (e.target.tagName === "TEXTAREA") return;
  const k = e.key.toLowerCase();
  if (["1","2","3"].includes(k)) pick("claim_scope", CLAIMS[+k-1]);
  else if (["q","w","e","r"].includes(k)) pick("numeric_scope", NUMERICS["qwer".indexOf(k)]);
  else if (e.key==="ArrowLeft") document.getElementById("prev").click();
  else if (e.key==="ArrowRight") document.getElementById("next").click();
  else if (e.key==="/") document.getElementById("flag").click();
});
render();
</script></body></html>"""


def main() -> None:
    src = json.loads(SRC.read_text(encoding="utf-8"))
    items = []
    for it in src["items"]:
        clean = strip_machine(it)
        clean["prefill_numeric"] = prefill_numeric(it["token_candidates"])
        items.append(clean)

    leaked = [k for it in items for k in it if k.startswith("_")]
    assert not leaked, f"기계 점수가 화면 데이터에 남았다: {set(leaked)}"

    data = {
        "items": items,
        "sample_meta": {k: v for k, v in src.items() if k != "items"},
    }
    combine_js = {f"{c}|{n}": v for (c, n), v in COMBINE.items()}

    html = HTML
    for token, value in (
        ("__DATA__", data), ("__COMBINE__", combine_js),
        ("__CLAIMS__", CLAIMS), ("__NUMERICS__", NUMERICS),
        ("__CLAIM_HELP__", CLAIM_HELP), ("__NUMERIC_HELP__", NUMERIC_HELP),
        ("__ACCEPT__", ACCEPT_MIN_SCORE), ("__REJECT__", REJECT_MAX_SCORE),
    ):
        html = html.replace(token, json.dumps(value, ensure_ascii=False))

    assert "__" not in re.sub(r"[a-z_]+__[a-z]", "", html.replace("__DATA__", "")), "치환 안 된 자리표시자"
    OUT.write_text(html, encoding="utf-8")

    pf = {}
    for it in items:
        pf[it["prefill_numeric"]] = pf.get(it["prefill_numeric"], 0) + 1
    print(f"생성: {OUT}  ({len(html)/1024:.0f}KB, {len(items)}건)")
    print(f"  ② 초기값 분포: {pf}")
    print(f"  기계 점수 누출: 없음 (검사 통과)")


if __name__ == "__main__":
    main()
