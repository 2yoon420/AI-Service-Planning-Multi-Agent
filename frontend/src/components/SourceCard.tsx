import type { SourceCard as Data } from "../lib/sources";

export default function SourceCard({ s }: { s: Data }) {
  return (
    <a
      className={`src-card${s.failed ? " is-failed" : ""}`}
      href={s.url}
      target="_blank"
      rel="noopener noreferrer"
    >
      {/* 파비콘 대신 도메인 첫 글자 아바타를 쓴다 — 외부 파비콘 서비스에
          사용자의 열람 이력을 넘기지 않기 위함(설계도 4-3절). */}
      <span className={`src-avatar tier-bg-${s.tier ?? "none"}`} aria-hidden>
        {s.domain.charAt(0).toUpperCase()}
      </span>

      <span className="src-main">
        <span className="src-top">
          <span className="src-domain">{s.domain}</span>
          {s.tier && <span className={`tier tier-${s.tier}`}>{s.tier}</span>}
        </span>

        <span className="src-title">{s.title || s.url}</span>

        <span className="src-meta">
          {s.failed
            ? "본문을 읽지 못했습니다 (검색 요약만 사용)"
            : [
                s.readChars !== null ? `본문 ${s.readChars.toLocaleString()}자` : null,
                s.factCount > 0 ? `fact ${s.factCount}건` : null,
              ].filter(Boolean).join(" · ") || "검색 결과"}
        </span>
      </span>
    </a>
  );
}
