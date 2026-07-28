import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 프록시를 쓰지 않고 CORS로 해결한다(8-1절). 프록시를 쓰면 개발할 때만
    // 동작하고 빌드 후에는 다시 CORS가 필요해져서, 문제를 나중으로 미루는 셈이 된다.
  },
});
