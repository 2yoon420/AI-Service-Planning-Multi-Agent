import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { EventItem, ProjectDetail } from "../api/types";

const POLL_MS = 2000;

/** 프로젝트 상태와 진행 이벤트를 함께 폴링한다.
 *
 *  두 개를 따로 폴링하지 않고 한 훅에서 순차로 처리하는 이유(설계도 6-1절):
 *  ProjectDetail.latest_event_seq를 보면 새 이벤트가 있는지 알 수 있으므로,
 *  없으면 /events 요청 자체를 건너뛴다. */
export function useProjectStream(projectId: string | null) {
  const [events, setEvents] = useState<EventItem[]>([]);
  const seenSeq = useRef(0);

  // 프로젝트를 바꾸면 이벤트 버퍼를 반드시 비운다.
  // 안 비우면 이전 프로젝트의 출처 카드가 새 프로젝트에 섞여 보인다.
  useEffect(() => {
    setEvents([]);
    seenSeq.current = 0;
  }, [projectId]);

  const query = useQuery<ProjectDetail>({
    queryKey: ["project", projectId],
    enabled: projectId !== null,
    queryFn: async () => {
      const detail = await api.getProject(projectId!);

      if (detail.latest_event_seq > seenSeq.current) {
        const batch = await api.getEvents(projectId!, seenSeq.current);
        if (batch.events.length > 0) {
          seenSeq.current = batch.latest_seq;
          setEvents((prev) => {
            // StrictMode 이중 실행·재시도로 같은 seq가 두 번 올 수 있어 중복을 거른다
            const seen = new Set(prev.map((e) => e.seq));
            const fresh = batch.events.filter((e) => !seen.has(e.seq));
            return fresh.length ? [...prev, ...fresh] : prev;
          });
        }
      }
      return detail;
    },

    // running일 때만 폴링한다. 나머지 상태에서는 서버가 스스로 바뀔 일이 없다.
    refetchInterval: (q) => (q.state.data?.status === "running" ? POLL_MS : false),

    // 이걸 빼면 탭을 옮겼다 돌아왔을 때 진행이 멈춘 것처럼 보인다(설계도 6-2절).
    refetchIntervalInBackground: true,

    // 진행 중 잠깐 실패해도 화면을 비우지 않는다
    retry: 2,
    staleTime: 0,
  });

  return {
    detail: query.data ?? null,
    events,
    isLoading: query.isLoading,
    error: query.error as Error | null,
  };
}
