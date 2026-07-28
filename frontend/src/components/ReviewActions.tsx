// ReviewActions.tsx — 승인 UI (설계도 4절 ④)
import { useSendMessage } from "../hooks/useSendMessage";
import { REVISION_CAP, QA_CAP, type ProjectDetail } from "../api/types";

export default function ReviewActions({ detail }: { detail: ProjectDetail }) {
  const send = useSendMessage(detail.project_id);

  return (
    <section className="review">
      {/* 원시 JSON을 던지지 않고, 서버가 준 사람이 읽는 문장을 그대로 보여준다 */}
      <p className="review-prompt">{detail.prompt ?? "초안을 확인해 주세요."}</p>

      <div className="review-actions">
        <button
          className="btn-primary"
          disabled={send.isPending}
          onClick={() => send.mutate("승인합니다. 이대로 마무리해 주세요.")}
        >
          승인하고 마무리
        </button>
        <button
          className="btn-ghost"
          onClick={() => document.getElementById("msg-input")?.focus()}
        >
          수정 요청하기
        </button>
      </div>

      {/* 한도를 미리 알려주지 않으면 갑자기 세션이 끝나는 이유를 알 수 없다 */}
      <p className="review-caps">
        재작업 {detail.revision_count}/{REVISION_CAP}
        {detail.qa_count > 0 && ` · 기능 질문 ${detail.qa_count}/${QA_CAP}`}
        {detail.revision_count >= REVISION_CAP - 1 &&
          " — 한도에 도달하면 현재 초안으로 자동 마무리됩니다"}
      </p>
    </section>
  );
}
