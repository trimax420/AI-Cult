import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": new URL("./src", import.meta.url).pathname } },
  server: {
    port: 5173,
    proxy: {
      "/api/simulator": {
        target: "http://localhost:8080",
        changeOrigin: true,
        rewrite: (requestPath) => requestPath.replace(/^\/api\/simulator/, ""),
      },
    },
  },
})
