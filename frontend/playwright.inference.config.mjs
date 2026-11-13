import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";

// All API responses are intercepted mock draft fixtures; no backend or GPU is started.
const output = process.env.LLMCLOUD_INFERENCE_TEST_OUTPUT ||
  fileURLToPath(new URL("../data/acceptance/b-review/m5-inference-mock/", import.meta.url));
export default defineConfig({
  testDir: "./e2e-inference", fullyParallel: false, workers: 1, retries: 0, timeout: 30000,
  outputDir: `${output}/artifacts`,
  reporter: [["list"], ["json", { outputFile: `${output}/report.json` }]],
  use: {
    baseURL: "http://127.0.0.1:15177", browserName: "chromium",
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure", screenshot: "only-on-failure",
  },
  webServer: {
    command: "npm run dev -- --port 15177 --strictPort",
    url: "http://127.0.0.1:15177", reuseExistingServer: false,
  },
});
