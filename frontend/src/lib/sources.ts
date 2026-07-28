import type { EventItem } from "../api/types";

export interface SourceCard {
  url: string;
  domain: string;
  title: string;
  tier: string | null;      // "1차" | "2차" | "3차"
  readChars: number | null;
  factCount: number;
  failed: boolean;
  firstSeq: number;
}

function toDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url.slice(0, 40);   // URL 파싱 실패해도 화면이 깨지지 않게
  }
}

/** 같은 URL에 대한 여러 이벤트(검색결과 → 본문읽기 → fact저장)를
 *  카드 하나로 합친다. 규칙은 설계도 4-3절 표와 동일. */
export function aggregateSources(events: EventItem[]): SourceCard[] {
  const map = new Map<string, SourceCard>();

  for (const e of events) {
    if (!e.url) continue;

    let card = map.get(e.url);
    if (!card) {
      card = {
        url: e.url, domain: toDomain(e.url), title: "", tier: null,
        readChars: null, factCount: 0, failed: false, firstSeq: e.seq,
      };
      map.set(e.url, card);
    }

    switch (e.kind) {
      case "search_result":
        if (e.title) card.title = e.title;
        if (e.tier) card.tier = e.tier;
        break;
      case "fetch":
        card.readChars = e.count ?? null;
        card.failed = false;              // 나중에 성공했으면 실패 표시를 지운다
        break;
      case "fetch_failed":
        if (card.readChars === null) card.failed = true;
        break;
      case "fact":
        card.factCount += 1;
        if (e.tier && !card.tier) card.tier = e.tier;
        break;
      default:
        break;                            // 모르는 kind는 무시
    }
  }

  // fact를 많이 만든 출처가 위로. 실패한 것은 맨 아래.
  return [...map.values()].sort((a, b) => {
    if (a.failed !== b.failed) return a.failed ? 1 : -1;
    if (b.factCount !== a.factCount) return b.factCount - a.factCount;
    return a.firstSeq - b.firstSeq;
  });
}

export function summarizeEvents(events: EventItem[]) {
  const sources = aggregateSources(events);
  return {
    lines: events.length,
    sources: sources.length,
    read: sources.filter((s) => s.readChars !== null).length,
    facts: events.filter((e) => e.kind === "fact").length,
  };
}
