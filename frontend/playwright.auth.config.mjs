import { defineConfig } from "@playwright/test";

const output = process.env.LLMCLOUD_AUTH_TEST_OUTPUT;
if (!output) throw new Error("Set LLMCLOUD_AUTH_TEST_OUTPUT to a runtime-disk output directory");
const apiCommand = process.env.LLMCLOUD_AUTH_TEST_COMMAND;
if (!apiCommand) throw new Error("Set LLMCLOUD_AUTH_TEST_COMMAND to run the disposable serve_auth_api.py");

export default defineConfig({
  testDir: "./e2e-auth", workers: 1, fullyParallel: false, retries: 0, timeout: 45000,
  outputDir: `${output}/artifacts`, reporter: [["list"], ["json", { outputFile: `${output}/report.json` }]],
  use: { baseURL: "http://127.0.0.1:15178", browserName: "chromium",
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined, viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure", screenshot: "only-on-failure" },
  webServer: [
    { command: apiCommand, cwd: "..", url: "http://127.0.0.1:18008/api/v1/health", reuseExistingServer: false,
      gracefulShutdown: { signal: "SIGTERM", timeout: 5000 } },
    { command: "npm run dev -- --port 15178 --strictPort", url: "http://127.0.0.1:15178", reuseExistingServer: false,
      env: { VITE_BACKEND_URL: "http://127.0.0.1:18008", VITE_API_BASE_URL: "/api/v1" },
      gracefulShutdown: { signal: "SIGTERM", timeout: 5000 } },
  ],
});
