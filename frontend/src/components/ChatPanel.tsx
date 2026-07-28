import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "../api/client";
import type { EventItem, ProjectDetail } from "../api/types";
import WorkCard from "./WorkCard";
import ReviewActions from "./ReviewActions";
import StatusBanner from "./StatusBanner";
import MessageInput from "./MessageInput";

export default function ChatPanel({
  detail, events, docOpen, onToggleDoc,
}: {
  detail: ProjectDetail;
  events: EventItem[];
  docOpen: boolean;
  onToggleDoc: () => void;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // 대화 기록은 실행이 끝날 때마다 갱신되면 충분하다 — 매 2초 받을 필요가 없다.
  const { data: chat } = useQuery({
    queryKey: ["messages", detail.project_id, detail.status, detail.revision_count, detail.qa_count],
    queryFn: () => api.getMessages(detail.project_id),
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length, chat?.messages.length]);

  return (
    <main className="chat">
      <header className="chat-header">
        <div>
          <p className="chat-eyebrow">사업 기획서 초안</p>
          <h1 className="chat-title">{detail.topic}</h1>
          <p className="chat-sub">{detail.target_market}</p>
        </div>
        <button className="btn-ghost" onClick={onToggleDoc}>
          {docOpen ? "문서 닫기" : "문서 보기"}
        </button>
      </header>

      <div className="chat-scroll">
        {/* 최초 입력은 chat_history에 없으므로 합성해서 보여준다(설계도 3-2절) */}
        <div className="msg msg-user">
          <div className="msg-body">
            <strong>{detail.topic}</strong>
            <br />
            {detail.target_market}
          </div>
        </div>

        {chat?.messages.map((m, i) => (
          <div key={i} className={`msg msg-${m.role === "user" ? "user" : "assistant"}`}>
            <div className="msg-body">{m.content}</div>
          </div>
        ))}

        <WorkCard detail={detail} events={events} />

        {(detail.status === "failed" || detail.status === "interrupted") && (
          <StatusBanner detail={detail} />
        )}

        {detail.status === "awaiting_review" && <ReviewActions detail={detail} />}

        <div ref={bottomRef} />
      </div>

      <MessageInput detail={detail} />
    </main>
  );
}
