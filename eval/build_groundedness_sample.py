"""근거지지도 사람 라벨용 표본을 층화 추출하고, ② 대조 후보를 미리 뽑아둔다.

실행:
    python eval/build_groundedness_sample.py --db fact_store/fact_20260729.db -n 50

## 왜 이제 가능해졌는가

`build_groundedness_sample`의 관련성 판(`build_label_sample.py`) docstring에 이렇게
적어두었다.

    "근거지지도를 사람이 라벨하려면 원문(source_content)이 필요한데 스키마가 저장하지
     않는다."

결함 H 수정(2026-07-29)으로 `Fact.source_excerpt`에 **심판이 실제로 본 3,000자**가
저장된다. 그래서 원문을 다시 긁어올 필요가 없다 — 다시 긁으면 그 사이 페이지가
바뀌어 "심판이 본 것"과 어긋나고, 순서 효과와 원문 차이가 섞인다.

## 왜 3점 경계에 몰아서 뽑는가

`ACCEPT_MIN_SCORE=4` / `REJECT_MAX_SCORE=2` 규칙에서 실제로 판정이 갈리는 자리는
3점(보류)이다. Router 골든셋에서 "경계 층에서 실력이 갈린다"를 확인했고, 관련성
라벨셋(`build_label_sample.py`)도 같은 이유로 경계를 두껍게 잡았다.

명확 구간(5점·2점)도 넣는다. **사람 라벨 자체를 검증하기 위해서다** — 명백한
케이스에서 사람과 기계가 어긋나면 경계 결과도 못 믿는다.

## ② 대조 후보를 코드가 뽑는 이유

원문이 3,000자다. 사람이 통독하면 항목당 몇 분이 걸리고, 50건이면 라벨링이
끝나지 않는다. 그래서 fact에서 수치·고유명사 후보를 뽑아 **원문에 그대로 있는지**
표시해 준다. 사람은 `2조 5,000억` vs `2.5조` 같은 **표기 차이만** 판단한다.

이 대조는 문자열 일치이고 검증기는 LLM이므로 로직을 공유하지 않는다. 다만
②가 **반자동**이라는 사실은 문서에 명시해야 한다 — 순수 사람 라벨이 아니다.
사람이 후보를 추가·삭제할 수 있게 UI에서 열어둔다.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

GND_PAT = re.compile(r"근거지지도\s*(\d)점")
REL_PAT = re.compile(r"관련성\s*(\d)점")

# ── ② 후보 추출 ────────────────────────────────────────────────────────────
# 수치: 1,234 / 35.7% / 2조 5,000억 / 2030년 / 420억 유로 / 17.4%p
NUM_PAT = re.compile(
    r"\d[\d,\.]*\s*(?:%p|%|퍼센트|배|조|억|만|천|원|달러|유로|엔|위안|년|월|일|명|개|건|위|천억|조원)?"
)
# 고유명사 후보: 라틴 문자로 시작하는 낱말 (DS Smith, Amcor, DexCom, Medicare …)
LATIN_PAT = re.compile(r"\b[A-Z][A-Za-z0-9&\.\-]{1,}\b")
# 그리고 한글 낱말 + 조직 접미사
#
# 접미사에서 1글자(부·청·처)를 뺐다. `룩셈부르크`에서 "부"에 걸려 **`룩셈부`**를
# 후보로 뽑는 버그가 있었다 — 잘린 문자열은 원문에 당연히 없으므로 "원문에 없음"으로
# 표시되고, 사람은 실재하지 않는 환각을 판단하느라 시간을 쓴다.
# 후보 추출기의 오탐은 라벨하는 사람의 시간을 직접 깎는다.
ORG_SUFFIX = ("연구소", "연구원", "협회", "학회", "위원회", "공사", "공단", "재단",
              "센터", "그룹", "홀딩스", "전자", "제약", "바이오", "식품", "푸드")
ORG_PAT = re.compile(r"[가-힣A-Za-z0-9]{2,}(?:" + "|".join(ORG_SUFFIX) + r")")

# 대조 가치가 없는 일반 약어·법인격 표기.
#
# `B2B`는 목표시장 서술("유럽 B2B 유통 시장")에서 온 말이고 원문에 없어도 환각이
# 아니다. `SA`·`plc`·`Inc`는 법인격이며 원문이 생략해도 무방하다. `HMR`은 제품
# 카테고리명이다. 첫 실행에서 45개 후보 중 8개(18%)가 이 유형이었다.
GENERIC_TOKENS = {
    "b2b", "b2c", "b2g", "d2c", "hmr", "ai", "it", "iot", "esg", "ceo", "cagr",
    "sa", "plc", "inc", "inc.", "ltd", "ltd.", "gmbh", "co", "co.", "corp",
    "corp.", "llc", "ag", "nv", "bv", "spa", "kk", "pte",
}
STOP_NUM = {str(i) for i in range(10)}
# 월 단독(`6월`)은 대조 가치가 낮다 — 연도 없이 월만 맞춰봐야 의미가 없다.
#
# ## 이 검사가 한때 죽은 코드였다 (2026-07-29 변조실험에서 발견)
#
# 처음에는 단위 목록에서 `월`·`일`을 **빼는** 방식으로 막으려 했다. 그러면 `6월`이
# `6`으로만 잡혀 한 자리 숫자 필터(`STOP_NUM`)에 걸린다. 그래서 `MONTH_ONLY`는
# 한 번도 발동하지 않았다.
#
# 그런데 `12월`은 `12`로 잡히고 `STOP_NUM`은 한 자리만 막으므로 **`12`가 후보로
# 올라갔다.** 아무 의미 없는 후보를 사람이 판단하게 만드는 것이다.
#
# 방어를 두 겹으로 겹쳐 놓고 한 겹이 다른 겹을 무력화한 경우다. 변조실험이 잡았다 —
# `MONTH_ONLY`를 지워도 테스트가 통과했기 때문이다. **통과하는 변조는 그 코드가
# 아무 일도 안 한다는 뜻이다.**
MONTH_ONLY = re.compile(r"^\d{1,2}\s*월$")


def norm(s: str) -> str:
    """대조용 정규화 — 공백·쉼표·괄호를 지운다.

    `2조 5,000억`과 `2조5000억`을 같은 것으로 보려는 최소한의 처리다.
    단위 환산(`2.5조` ↔ `2조 5,000억`)은 **하지 않는다** — 그건 판단이고,
    판단은 사람이 해야 한다. 코드가 환산까지 하면 틀렸을 때 사람이 알아채지 못한다.
    """
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"[\s,()\[\]]", "", s)


def extract_tokens(fact_text: str, context: str = "") -> list[str]:
    """fact에서 원문과 대조할 후보를 뽑는다.

    `context`에는 주제·목표시장·리서치 질문을 넣는다. **거기에 이미 있는 말은
    후보에서 뺀다.**

    ## 왜

    fact 문장에는 파이프라인이 주입한 맥락 서술어가 섞여 있다 —
    `한국 시니어 케어푸드 시장에서…`, `유럽 B2B 유통 시장에서…`. 이 말들은
    출처가 주장한 내용이 아니라 **질문 쪽에서 온 것**이다. 원문에 없어도 환각이
    아니다. 첫 실행에서 `B2B`·`케어푸드`가 "원문에 없음"으로 표시돼 사람이
    판단할 목록에 올라왔다.

    `GENERIC_TOKENS`로 일일이 나열하는 방식은 도메인이 바뀌면 무너진다.
    맥락 문자열과 대조하는 쪽이 일반적이다 — 하드코딩 감사(59-2절)에서
    배운 "목록보다 규칙"이다.
    """
    nctx = norm(context)
    out: list[str] = []
    for m in NUM_PAT.finditer(fact_text):
        t = m.group(0).strip()
        if norm(t) in STOP_NUM or not any(ch.isdigit() for ch in t):
            continue
        if MONTH_ONLY.match(norm(t)):
            continue
        out.append(t)
    for pat in (LATIN_PAT, ORG_PAT):
        for m in pat.finditer(fact_text):
            t = m.group(0).strip()
            if len(norm(t)) >= 2 and norm(t).lower() not in GENERIC_TOKENS \
                    and norm(t) not in nctx:
                out.append(t)
    seen, uniq = set(), []
    for t in out:
        k = norm(t)
        if k not in seen:
            seen.add(k)
            uniq.append(t)
    return uniq


DIGITS = re.compile(r"\d[\d\.]*")


def _loose_digit_pattern(d: str) -> re.Pattern:
    """숫자 사이에 쉼표·공백이 끼어도 찾도록 느슨한 정규식을 만든다.

    `116.13`이 원문에서 `116.13`으로도 `116,13`으로도 나올 수 있고, 천 단위 쉼표가
    붙는 경우(`1169` ↔ `1,169`)도 흔하다.
    """
    return re.compile(r"[\s,]*".join(re.escape(ch) for ch in d))


def near_hits(token: str, excerpt: str, width: int = 40) -> list[str]:
    """그대로는 없는 후보에 대해, 원문에서 **비슷한 표기**를 찾아 문맥과 함께 준다.

    ## 왜 필요한가

    첫 실행에서 원문에 없다고 나온 후보 상당수가 `2032년`·`65%`처럼 **단위 표기만
    다른** 경우였다. 사람이 이걸 확인하려면 3,000자를 눈으로 훑어야 한다.
    그러면 "반자동 보조"가 보조가 아니게 된다.

    ## 문맥은 원문에서 잘라야 한다

    처음에는 정규화된 문자열(공백·쉼표 제거)에서 문맥을 잘랐다. 그랬더니
    `…별북미유럽아시아태평양라틴아메리카…` 처럼 **읽을 수 없는 덩어리**가 나왔고,
    더 나쁘게는 공백이 사라져 **없던 인접 관계가 생겼다** — `유니레버는100년2025월72년`
    같은 문맥은 원문에 존재하지 않는 배열이다. 보조 정보가 사람을 오도하면
    보조가 아니라 함정이다.

    그래서 대조는 정규화로, **표시는 원문으로** 한다.

    판단은 사람이 한다 — 코드는 "여기를 보십시오"까지만 한다. 코드가 `2032년`과
    `2032`를 같다고 단정하면, 원문이 "2032년 예상"이 아니라 "2032년까지 금지"인
    경우를 놓친다.
    """
    hits: list[str] = []
    seen: set[int] = set()
    for dm in DIGITS.finditer(token):
        d = dm.group(0)
        if len(d.replace(".", "")) < 2:
            continue
        for m in _loose_digit_pattern(d).finditer(excerpt):
            a, b = max(0, m.start() - width), min(len(excerpt), m.end() + width)
            if any(abs(a - x) < 12 for x in seen):
                continue
            seen.add(a)
            hits.append(re.sub(r"\s+", " ", excerpt[a:b]).strip())
            if len(hits) >= 3:
                return hits
    return hits


def check_tokens(tokens: list[str], excerpt: str) -> list[dict]:
    """각 후보가 원문에 그대로 있는지 표시하고, 없으면 근처 표기를 찾아 붙인다."""
    ne = norm(excerpt)
    out = []
    for t in tokens:
        verbatim = norm(t) in ne
        rec = {"token": t, "verbatim": verbatim}
        if not verbatim:
            rec["near"] = near_hits(t, excerpt)
        out.append(rec)
    return out


# ── 표본 추출 ──────────────────────────────────────────────────────────────
def load_usable(db: str) -> list[dict]:
    """source_excerpt와 근거지지도 점수를 둘 다 가진 fact만 모은다."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = [json.loads(r["data_json"]) for r in con.execute("SELECT data_json FROM facts")]
    con.close()

    out = []
    for d in rows:
        exc = d.get("source_excerpt")
        vr = d.get("verification_reasoning") or ""
        mg = GND_PAT.search(vr)
        if not exc or not mg:
            continue
        mr = REL_PAT.search(vr)
        out.append({
            "id": d["id"],
            "text": d["text"],
            "topic": d.get("topic") or "",
            "region": d.get("region"),
            "topic_relevance": d.get("topic_relevance") or "",
            "source_url": d.get("source_url") or "",
            "source_excerpt": exc,
            # ↓ 라벨링 UI에는 절대 넣지 않는다 (앵커링 방지). 분석 단계에서만 쓴다.
            "_machine_groundedness": int(mg.group(1)),
            "_machine_relevance": int(mg and mr.group(1)) if mr else None,
            "_machine_status": d.get("verification_status"),
        })
    return out


# 층 구성 — 3점 경계를 두껍게, 명확 구간은 라벨셋 검증용
DEFAULT_STRATA = {3: 0.60, 5: 0.24, 2: 0.16}


def stratify(pool: list[dict], n: int, seed: int) -> list[dict]:
    """기계 점수 층별로 뽑되, 주제가 한쪽에 몰리지 않게 라운드로빈으로 섞는다."""
    rnd = random.Random(seed)
    by_score: dict[int, list[dict]] = defaultdict(list)
    for d in pool:
        by_score[d["_machine_groundedness"]].append(d)

    picked: list[dict] = []
    for score, frac in DEFAULT_STRATA.items():
        want = round(n * frac)
        cand = by_score.get(score, [])
        # 주제별로 나눠 라운드로빈 — 한 주제가 층을 독점하지 않게 한다
        by_topic: dict[str, list[dict]] = defaultdict(list)
        for d in cand:
            by_topic[d["topic"]].append(d)
        for v in by_topic.values():
            rnd.shuffle(v)
        keys = sorted(by_topic)
        rnd.shuffle(keys)
        taken = 0
        while taken < want and any(by_topic[k] for k in keys):
            for k in keys:
                if taken >= want:
                    break
                if by_topic[k]:
                    picked.append(by_topic[k].pop())
                    taken += 1
        if taken < want:
            print(f"  ! {score}점 층: {want}건 요청했으나 {taken}건만 있음")
    rnd.shuffle(picked)
    return picked[:n]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="fact_store/fact_20260729.db")
    ap.add_argument("-n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=20260729)
    ap.add_argument("--out", default="eval/label/groundedness_sample.json")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    pool = load_usable(args.db)
    print(f"실험 가능 fact {len(pool)}건")
    print(f"  기계 근거지지도 분포: {dict(sorted(Counter(d['_machine_groundedness'] for d in pool).items()))}")
    print(f"  주제 분포: {dict(Counter(d['topic'] for d in pool))}")

    sample = stratify(pool, args.n, args.seed)
    for d in sample:
        ctx = " ".join([d.get("topic") or "", d.get("topic_relevance") or ""])
        toks = extract_tokens(d["text"], ctx)
        d["token_candidates"] = check_tokens(toks, d["source_excerpt"])

    out = Path(args.out)
    if out.exists() and not args.force:
        raise SystemExit(f"이미 있음: {out} (--force 로 덮어쓰기)")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "built_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
        "db": args.db, "n": len(sample), "seed": args.seed,
        "axis": "groundedness",
        "strata": {str(k): v for k, v in DEFAULT_STRATA.items()},
        "note": "_machine_* 필드는 라벨링 UI에 넣지 않는다 (앵커링 방지). 분석 단계 전용.",
        "items": sample,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n표본 {len(sample)}건 → {out}")
    print(f"  층 분포: {dict(sorted(Counter(d['_machine_groundedness'] for d in sample).items()))}")
    print(f"  주제 분포: {dict(Counter(d['topic'] for d in sample))}")
    tc = [len(d['token_candidates']) for d in sample]
    vb = sum(1 for d in sample for t in d['token_candidates'] if t['verbatim'])
    tot = sum(tc)
    print(f"  ② 후보: 총 {tot}개 (항목당 평균 {tot/len(sample):.1f}개), "
          f"원문에 그대로 있음 {vb}개 ({vb/tot*100:.0f}%)" if tot else "  ② 후보 없음")
    print(f"  후보 0개인 항목: {sum(1 for x in tc if x==0)}건 → ②는 '해당없음'이 기본")


if __name__ == "__main__":
    main()
