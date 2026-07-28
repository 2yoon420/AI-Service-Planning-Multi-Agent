// DraftView.tsx — 마크다운을 docx_design.md 스타일로 렌더링
import { useQuery } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../../api/client";
import type { ProjectStatus } from "../../api/types";

export default function DraftView({
  projectId, status,
}: { projectId: string; status: ProjectStatus }) {
  const { data, isLoading } = useQuery({
    // status가 바뀔 때(= 실행이 한 번 끝날 때)마다 다시 받는다.
    queryKey: ["draft", projectId, status],
    queryFn: () => api.getDraftMarkdown(projectId),
  });

  if (isLoading) return <p className="doc-empty">불러오는 중…</p>;
  if (!data) {
    return (
      <p className="doc-empty">
        아직 초안이 없습니다. 시장조사 · PESTEL · 경쟁사 분석이 끝나면 여기에 표시됩니다.
      </p>
    );
  }

  return (
    <article className="doc">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // 마크다운 h1 = 문서 제목 → docx 표지 대제목 (3절)
          h1: ({ children }) => <h1 className="doc-cover-title">{children}</h1>,
          // 마크다운 h2 = "## 1. 개요" → docx H1 (4절)
          h2: ({ children }) => <h2 className="doc-h1">{children}</h2>,
          // 마크다운 h3 → docx H2 "▎ 소제목" (4절)
          h3: ({ children }) => <h3 className="doc-h2">▎ {children}</h3>,
          table: ({ children }) => (
            <div className="doc-table-wrap"><table className="doc-table">{children}</table></div>
          ),
          blockquote: ({ children }) => <div className="doc-callout">{children}</div>,
        }}
      >
        {data}
      </ReactMarkdown>
    </article>
  );
}
