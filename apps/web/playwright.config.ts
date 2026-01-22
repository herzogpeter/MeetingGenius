import { defineConfig } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const configDir = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(configDir, '../..')
const serveScript = path.join(repoRoot, 'scripts', 'e2e-serve.sh')

const host = process.env.E2E_HOST ?? '127.0.0.1'
const rawFrontendPort = Number.parseInt(process.env.E2E_FRONTEND_PORT ?? '5174', 10)
const rawBackendPort = Number.parseInt(process.env.E2E_BACKEND_PORT ?? '8010', 10)
const frontendPort = Number.isFinite(rawFrontendPort) ? rawFrontendPort : 5174
const backendPort = Number.isFinite(rawBackendPort) ? rawBackendPort : 8010
const baseURL = `http://${host}:${frontendPort}`
const reporter = process.env.CI ? [['html', { open: 'never' }], ['list']] : 'list'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  timeout: 3 * 60 * 1000,
  expect: { timeout: 30_000 },
  retries: process.env.CI ? 1 : 0,
  reporter,
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: [
      `E2E_HOST=${host}`,
      `E2E_FRONTEND_PORT=${frontendPort}`,
      `E2E_BACKEND_PORT=${backendPort}`,
      'bash',
      `"${serveScript}"`,
    ].join(' '),
    cwd: repoRoot,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 2 * 60 * 1000,
  },
})
