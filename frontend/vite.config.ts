import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", "ADBOT_");
  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        "/api": env.ADBOT_API_PROXY_TARGET || "http://127.0.0.1:8000",
      },
    },
    build: {
      sourcemap: env.ADBOT_BUILD_SOURCEMAPS === "true" ? "hidden" : false,
      rollupOptions: { output: { manualChunks: { charts: ["recharts"] } } },
    },
  };
});
