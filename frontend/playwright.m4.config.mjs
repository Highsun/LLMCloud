import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";

// External mode is only for the disposable serve_m4_api.py on Linux/container.
// Never point these destructive test controls at a business service.
const api = process.env.LLMCLOUD_M4_TEST_API || "http://127.0.0.1:18006";
process.env.LLMCLOUD_M4_RUN_ID ??= String(Date.now());
const output = fileURLToPath(new URL(`../data/acceptance/b-review/m4-06/${process.env.LLMCLOUD_M4_RUN_ID}/`, import.meta.url));
export default defineConfig({
  testDir: "./e2e-m4",
  fullyParallel: false, workers: 1, retries: 0, timeout: 45_000,
  outputDir: output,
  reporter: [["list"], ["json", { outputFile: `${output}/report.json` }]],
  use: {
    baseURL: "http://127.0.0.1:15176", browserName: "chromium",
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    viewport: { width: 1440, height: 1000 }, acceptDownloads: true,
    trace: "retain-on-failure", screenshot: "only-on-failure",
  },
  webServer: [
    ...(!process.env.LLMCLOUD_M4_TEST_API ? [{
      command: `${process.env.LLMCLOUD_TEST_PYTHON || "uv run --locked python"} frontend/testing/serve_m4_api.py`,
      cwd: "..", url: `${api}/api/v1/health`, reuseExistingServer: false,
      gracefulShutdown: { signal: "SIGTERM", timeout: 5000 },
    }] : []),
    {
      command: "npm run dev -- --port 15176 --strictPort",
      url: "http://127.0.0.1:15176", reuseExistingServer: false,
      env: { VITE_BACKEND_URL: api, VITE_API_BASE_URL: "/api/v1", VITE_OPENAPI_URL: "/openapi.json" },
      gracefulShutdown: { signal: "SIGTERM", timeout: 5000 },
    },
  ],
});
