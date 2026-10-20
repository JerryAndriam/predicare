import { defineConfig, devices } from '@playwright/test'

/**
 * Tests de parcours de l'interface.
 *
 * Ils s'executent sur la pile COMPLETE (docker compose up) : c'est la
 * seule façon de vérifier qu'un écran et l'API qu'il consomme se parlent
 * vraiment. Un test qui.mockerait l'API ne prouverait que le rendu.
 *
 * Avant exécution :
 *     docker compose up -d
 *     npm --prefix apps/web run test:e2e
 */
export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.PREDICARE_BASE_URL ?? 'http://localhost:8080',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    locale: 'fr-FR',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
