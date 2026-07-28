import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import DifferentiatorPanel from "./DifferentiatorPanel";

// 메인화면_시안_설계도.md 5-3절.
// 실제로 실행해본 적 있는 주제만 넣는다 — 시연 중 칩을 눌러 시작했을 때
// 결과가 잘 나오는 것이 보장돼야 하기 때문이다.
const PRESETS = [
  { label: "웨어러블 헬스케어 · 북미", topic: "웨어러블 헬스케어 기기",
    market: "북미 시니어 건강관리 시장" },
  { label: "반려동물 기기 · 북미",     topic: "스마트 반려동물 건강관리 기기",
    market: "북미 반려동물 오너 시장" },
  { label: "친환경 포장재 · EU",       topic: "친환경 포장재",
    market: "유럽 B2B 유통 시장" },
] as const;

export default function NewProjectForm({ onCreated }: { onCreated: (id: string) => void }) {
  const [topic, setTopic] = useState("");
  const [market, setMarket] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const qc = useQueryClient();

  const ready = topic.trim().length > 0 && market.trim().length > 0;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await api.createProject(topic.trim(), market.trim());
      qc.invalidateQueries({ queryKey: ["projects"] });
      onCreated(res.project_id);          // 202를 받는 즉시 채팅으로 전환(설계도 3-2절)
    } catch (e) {
      setErr(e instanceof Error ? e.message : "요청에 실패했습니다");
      setBusy(false);
    }
  }

  // 칩 클릭 = setTopic + setMarket. 자동 제출하지 않는다 —
  // 사용자가 값을 확인하고 수정할 여지를 남긴다(설계도 5-3절).
  function applyPreset(p: (typeof PRESETS)[number]) {
    setTopic(p.topic);
    setMarket(p.market);
  }

  return (
    <main className="home">
      <div className="home-col-input">
        <div className="home-inner">
          <p className="home-eyebrow">AI 서비스 기획 보조 Multi-Agent</p>
          <h1 className="home-title">어떤 사업을 기획하시나요?</h1>
          <p className="home-sub">
            모든 문장에 <strong>출처와 검증 결과</strong>가 붙은 기획서를 만듭니다.
            <br />
            찾지 못한 정보는 지어내지 않고 <strong>"정보 없음"</strong>이라고 씁니다.
          </p>

          <form className="home-form" onSubmit={submit}>
            <label className="field">
              <span className="field-label">연구대상 (제품 / 서비스)</span>
              <input
                className="field-input"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="예: 웨어러블 헬스케어 기기"
                autoFocus
              />
            </label>

            <label className="field">
              <span className="field-label">목표시장</span>
              <input
                className="field-input"
                value={market}
                onChange={(e) => setMarket(e.target.value)}
                placeholder="예: 북미 시니어 건강관리 시장"
              />
            </label>

            <div className="chips">
              {PRESETS.map((p) => (
                <button
                  key={p.label}
                  type="button"
                  className="chip"
                  onClick={() => applyPreset(p)}
                >
                  {p.label}
                </button>
              ))}
            </div>

            {err && <p className="field-error">{err}</p>}

            <button className="btn-primary" type="submit" disabled={!ready || busy}>
              {busy ? "시작하는 중…" : "기획 시작"}
            </button>

            <div className="note">
              <p className="note-text">
                평균 <strong>100건 이상</strong>의 근거를 직접 수집하고, 그것을 문장 단위로{" "}
                <strong>검증합니다.</strong>
                <br />
                그래서 5~15분이 걸리고, 그 과정을 전부 보여드립니다.
              </p>
            </div>
          </form>
        </div>
      </div>

      <div className="home-col-diff">
        <DifferentiatorPanel />
      </div>
    </main>
  );
}
