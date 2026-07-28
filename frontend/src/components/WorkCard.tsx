// WorkCard.tsx — 작업 카드 (설계도 4-2절)
import { useState } from "react";
import type { EventItem, ProjectDetail } from "../api/types";
import { resolveStages } from "../lib/stages";
import { summarizeEvents } from "../lib/sources";
import StageTimeline from "./StageTimeline";
import EventTicker from "./EventTicker";

export default function WorkCard({
  detail, events,
}: { detail: ProjectDetail; events: EventItem[] }) {
  const running = detail.status === "running";
  const [open, setOpen] = useState(false);

  if (events.length === 0 && !running) return null;

  const stages = resolveStages(detail.next_nodes, detail.status);
  const sum = summarizeEvents(events);

  return (
    <section className={`work-card${running ? " is-running" : ""}`}>
      <StageTimeline stages={stages} />

      {running && <EventTicker events={events} />}

      <button className="work-log-toggle" onClick={() => setOpen((v) => !v)}>
        {open ? "▾" : "▸"} 전체 로그 {sum.lines}줄 · 출처 {sum.sources}곳 · fact {sum.facts}건
      </button>

      {open && (
        <pre className="work-log">
          {events.map((e) => e.message).join("\n")}
        </pre>
      )}
    </section>
  );
}
