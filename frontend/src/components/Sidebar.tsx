import { NavLink, useNavigate } from "react-router-dom";
import { useProjects } from "../hooks/useProjects";
import type { ProjectStatus, ProjectSummary } from "../api/types";

const GROUPS: { key: string; label: string; match: ProjectStatus[] }[] = [
  { key: "run",  label: "진행 중",   match: ["running"] },
  { key: "wait", label: "검토 대기",  match: ["awaiting_review", "interrupted"] },
  { key: "done", label: "완료",      match: ["completed"] },
  { key: "fail", label: "실패",      match: ["failed"] },
];

const DOT: Record<ProjectStatus, string> = {
  running: "dot-running",
  awaiting_review: "dot-awaiting",
  interrupted: "dot-awaiting",
  completed: "dot-done",
  failed: "dot-error",
};

export default function Sidebar() {
  const { data = [] } = useProjects();
  const navigate = useNavigate();

  return (
    <aside className="sidebar">
      <button className="btn-new" onClick={() => navigate("/")}>+ 새 기획서</button>

      <nav className="sidebar-list">
        {GROUPS.map((g) => {
          const items = data.filter((p) => g.match.includes(p.status));
          if (items.length === 0) return null;
          return (
            <section key={g.key} className="sidebar-group">
              <h2 className="sidebar-group-title">{g.label}</h2>
              {items.map((p: ProjectSummary) => (
                <NavLink
                  key={p.project_id}
                  to={`/projects/${p.project_id}`}
                  className={({ isActive }) =>
                    "sidebar-item" + (isActive ? " is-active" : "")
                  }
                >
                  <span className={`dot ${DOT[p.status]}`} aria-hidden />
                  <span className="sidebar-item-text">
                    <span className="sidebar-item-topic">{p.topic}</span>
                    <span className="sidebar-item-market">{p.target_market}</span>
                  </span>
                </NavLink>
              ))}
            </section>
          );
        })}

        {data.length === 0 && (
          <p className="sidebar-empty">아직 기획서가 없습니다.</p>
        )}
      </nav>
    </aside>
  );
}
