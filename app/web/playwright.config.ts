import {defineConfig, devices} from '@playwright/test'

// Smoke suite against the built site. `channel: 'chrome'` reuses an installed
// Chrome so CI only needs `npx playwright install chromium` when no channel is
// available; locally nothing is downloaded.
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: {timeout: 10_000},
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:4177',
    channel: process.env.CI ? undefined : 'chrome',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{name: 'chromium', use: {...devices['Desktop Chrome']}}],
  webServer: {
    command:
      'npm run build && npx vite preview --port 4177 --strictPort',
    url: 'http://localhost:4177',
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
})
