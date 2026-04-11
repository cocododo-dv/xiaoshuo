import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  workers: 1,
  timeout: 120000,
  expect: {
    timeout: 10000,
  },
  fullyParallel: false,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:8081",
    trace: "on-first-retry",
  },
  webServer: [
    {
      command: "node tests/e2e/backend-server.mjs",
      url: "http://127.0.0.1:8000/api/v1/review-items",
      reuseExistingServer: false,
      timeout: 120000,
    },
    {
      command: "cmd /c \"npm run build && npx vite preview --host 127.0.0.1 --port 8081 --strictPort\"",
      url: "http://127.0.0.1:8081",
      reuseExistingServer: false,
      timeout: 120000,
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], channel: "chrome" },
    },
  ],
});
