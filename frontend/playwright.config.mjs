import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:15173",
    browserName: "chromium",
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "uv run --locked python scripts/serve_test_api.py --port 18000 --faults",
      cwd: "..",
      url: "http://127.0.0.1:18000/api/v1/health",
      reuseExistingServer: false,
      gracefulShutdown: { signal: "SIGTERM", timeout: 5000 },
    },
    {
      command: "npm run dev -- --port 15173",
      url: "http://127.0.0.1:15173",
      env: {
        VITE_BACKEND_URL: "http://127.0.0.1:18000",
        VITE_API_BASE_URL: "/api/v1",
        VITE_OPENAPI_URL: "/openapi.json",
      },
      reuseExistingServer: false,
      gracefulShutdown: { signal: "SIGTERM", timeout: 5000 },
    },
  ],
});
