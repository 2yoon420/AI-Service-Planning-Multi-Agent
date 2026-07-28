// MessageInput.tsx
import { useState } from "react";
import { useSendMessage } from "../hooks/useSendMessage";
import type { ProjectDetail } from "../api/types";

/** 입력이 가능한 상태인지. running/completed/failed에서는 백엔드가 409로 막으므로
 *  화면에서 먼저 잠근다(1차 방어). 409 처리는 useSendMessage에 있다(2차 방어). */
function canType(s: ProjectDetail["status"]) {
  return s === "awaiting_review" || s === "interrupted";
}

const PLACEHOLDER: Record<string, string> = {
  running: "작업이 진행 중입니다. 끝나면 입력할 수 있습니다.",
  completed: "종료된 프로젝트입니다. 새 기획서를 시작해 주세요.",
  failed: "실패한 프로젝트입니다. 새 기획서를 시작해 주세요.",
  awaiting_review: "수정할 부분을 알려주세요. (예: 4장 경쟁사 가격 정보를 더 채워주세요)",
  interrupted: "메시지를 보내면 멈춘 지점부터 이어집니다.",
};

export default function MessageInput({ detail }: { detail: ProjectDetail }) {
  const [text, setText] = useState("");
  const send = useSendMessage(detail.project_id);
  const enabled = canType(detail.status) && !send.isPending;

  function submit() {
    const v = text.trim();
    if (!v || !enabled) return;
    send.mutate(v);
    setText("");
  }

  return (
    <footer className="composer">
      <textarea
        id="msg-input"
        className="composer-input"
        rows={2}
        value={text}
        disabled={!enabled}
        placeholder={PLACEHOLDER[detail.status] ?? ""}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          // Enter 전송 / Shift+Enter 줄바꿈 — 채팅 UI 관례
          if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
        }}
      />
      <button className="btn-primary" disabled={!enabled || !text.trim()} onClick={submit}>
        보내기
      </button>
      {send.isError && (
        <p className="composer-error">
          전송 실패 — {(send.error as Error).message}
        </p>
      )}
    </footer>
  );
}
