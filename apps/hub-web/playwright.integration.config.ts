import { defineConfig, devices } from "@playwright/test";

const apiOrigin = "http://127.0.0.1:8001";
const allowedWebOrigin = "http://127.0.0.1:4174";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "api-integration.spec.ts",
  fullyParallel: false,
  reporter: "list",
  use: {
    baseURL: allowedWebOrigin,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "api-integration-chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: "../../.venv/bin/python ../hub-api/tests/browser_api_server.py",
      url: `${apiOrigin}/api/v1/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        HUB_BROWSER_TEST_ORIGIN: allowedWebOrigin,
      },
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 4174 --strictPort",
      url: allowedWebOrigin,
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        HUB_API_PROXY_TARGET: apiOrigin,
      },
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 4175 --strictPort",
      url: "http://127.0.0.1:4175",
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        HUB_API_PROXY_TARGET: apiOrigin,
      },
    },
  ],
});
