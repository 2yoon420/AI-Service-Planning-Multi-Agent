// EventTicker.tsx — 최근 이벤트 4줄만 흐른다
import type { EventItem } from "../api/types";

const TICKER_LINES = 4;

export default function EventTicker({ events }: { events: EventItem[] }) {
  const recent = events.slice(-TICKER_LINES);
  if (recent.length === 0) {
    return <p className="ticker-idle">준비 중…</p>;
  }
  return (
    <ul className="ticker">
      {recent.map((e) => (
        <li key={e.seq} className={`ticker-line kind-${e.kind}`}>
          {e.tier && <span className={`tier tier-${e.tier}`}>{e.tier}</span>}
          <span className="ticker-text">{e.message.trim()}</span>
        </li>
      ))}
    </ul>
  );
}
