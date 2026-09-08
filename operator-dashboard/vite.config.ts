import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"
import { fileURLToPath } from "node:url"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    proxy: {
      "/api/simulator": {
        target: process.env.VITE_SIMULATOR_PROXY_TARGET || "http://localhost:8080",
        changeOrigin: true,
        rewrite: (requestPath) => requestPath.replace(/^\/api\/simulator/, ""),
      },
    },
  },
})
