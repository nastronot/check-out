/// <reference types="vitest" />
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// Dev: vite serves the UI on :5173 and proxies /api to the FastAPI backend on
// :8000, so the same fetch('/api/...') calls work in dev and in production
// (where uvicorn serves the built dist/ and the api from one origin).
export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  test: {
    // Pure-logic unit tests (font/render helpers) — no DOM needed.
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
