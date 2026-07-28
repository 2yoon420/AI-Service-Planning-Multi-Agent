// useProjects.ts — 사이드바 목록
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function useProjects() {
  return useQuery({
    queryKey: ["projects"],
    queryFn: api.listProjects,
    refetchInterval: 10_000,          // 사이드바는 느리게 갱신해도 충분하다
    refetchIntervalInBackground: true,
  });
}
