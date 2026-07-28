// useSendMessage.ts — 메시지 전송 + 폴링 재시작
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";

export function useSendMessage(projectId: string) {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (message: string) => api.sendMessage(projectId, message),

    onSuccess: () => {
      // ★ 이 두 줄이 없으면 메시지를 보내도 화면이 영원히 멈춘다.
      //   awaiting_review에서 refetchInterval이 false를 반환해 폴링이 꺼져 있으므로,
      //   강제로 한 번 다시 조회해서 status를 running으로 읽게 만들어야
      //   refetchInterval이 다시 2000을 반환하며 폴링이 살아난다(설계도 6-2절).
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },

    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) {
        // 입력창을 잠가두는 것이 1차 방어, 이 처리가 2차 방어다
        // (이 프로젝트가 지켜온 "이중 안전장치" 원칙).
        qc.invalidateQueries({ queryKey: ["project", projectId] });
      }
    },
  });
}
