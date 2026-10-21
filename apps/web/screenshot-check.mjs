import { chromium } from '@playwright/test'

const base = 'http://localhost:8080'
const out = `${process.env.TEMP}\\predicare-logo`
const browser = await chromium.launch()
const errors = []

const contexte = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await contexte.newPage()
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(`console: ${m.text()}`)
})
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
page.on('requestfailed', (r) =>
  errors.push(`requestfailed: ${r.url()} ${r.failure()?.errorText ?? ''}`),
)

await page.goto(`${base}/connexion`, { waitUntil: 'networkidle' })
await page.screenshot({ path: `${out}\\login-1440.png`, fullPage: true })

await page.fill('input[type=email]', 'gestionnaire@predicare.local')
await page.fill('input[type=password]', 'PrediCare2026!')
await page.click('button[type=submit]')
await page.waitForURL((url) => !url.pathname.includes('/connexion'), { timeout: 20000 })
await page.waitForLoadState('networkidle')
await page.waitForTimeout(600)
await page.screenshot({ path: `${out}\\nav-1440.png` })
await page.locator('header.sticky').screenshot({ path: `${out}\\header-1440.png` })

await page.getByRole('button', { name: 'Replier la navigation' }).click()
await page.waitForTimeout(350)
await page.locator('header.sticky').screenshot({ path: `${out}\\header-rail-1440.png` })

const contexteMobile = await browser.newContext({ viewport: { width: 390, height: 844 } })
const mobile = await contexteMobile.newPage()
await mobile.goto(`${base}/connexion`, { waitUntil: 'networkidle' })
await mobile.screenshot({ path: `${out}\\login-390.png`, fullPage: true })

await browser.close()
console.log(JSON.stringify({ errors }, null, 2))
