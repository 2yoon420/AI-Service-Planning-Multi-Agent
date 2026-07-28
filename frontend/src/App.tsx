import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes, useNavigate, useParams } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import NewProjectForm from "./components/NewProjectForm";
import ChatPanel from "./components/ChatPanel";
import DocumentPanel from "./components/document/DocumentPanel";
import { useProjectStream } from "./hooks/useProjectStream";
import { useState } from "react";
import "./styles/tokens.css";
import "./styles/app.css";

const qc = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
});

function ProjectView() {
  const { projectId } = useParams<{ projectId: string }>();
  const { detail, events, error } = useProjectStream(projectId ?? null);
  const [docOpen, setDocOpen] = useState(window.innerWidth >= 1440);

  if (error) {
    return <div className="center-msg">프로젝트를 불러오지 못했습니다 — {error.message}</div>;
  }
  if (!detail) {
    return <div className="center-msg">불러오는 중…</div>;
  }

  return (
    <>
      <ChatPanel
        detail={detail}
        events={events}
        docOpen={docOpen}
        onToggleDoc={() => setDocOpen((v) => !v)}
      />
      {docOpen && (
        <DocumentPanel detail={detail} events={events} onClose={() => setDocOpen(false)} />
      )}
    </>
  );
}

function HomeView() {
  const navigate = useNavigate();
  return <NewProjectForm onCreated={(id) => navigate(`/projects/${id}`)} />;
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <div className="app-shell">
          <Sidebar />
          <Routes>
            <Route path="/" element={<HomeView />} />
            <Route path="/projects/:projectId" element={<ProjectView />} />
          </Routes>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
