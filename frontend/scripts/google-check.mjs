// Browser check for the optional Google layers (needs GOOGLE_MAPS_API_KEY on the server).
//   node scripts/google-check.mjs            (local)   POND_URL=http://10.1.75.53:3233/ node scripts/google-check.mjs
// Screenshots contain Google imagery: they go to tmp/ for review and should be deleted afterwards.
import { chromium } from 'playwright-core'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

const BASE_URL = process.env.POND_URL ?? 'http://127.0.0.1:8000/'
const out = resolve('..', 'tmp', 'shots-google')
await mkdir(out, { recursive: true })
const browser = await chromium.launch({
  headless: true, executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
})
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const problems = []
page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`))
page.on('console', (message) => { if (message.type() === 'error') problems.push(`console: ${message.text().slice(0, 200)}`) })
const shot = (name) => page.screenshot({ path: resolve(out, `${name}.png`) })
const checks = {}

for (let attempt = 1; ; attempt++) {
  try { await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 }); break }
  catch (error) { if (attempt === 4) throw error; await page.waitForTimeout(2000) }
}
await page.locator('.map-canvas[data-ready="true"]').waitFor({ timeout: 60000 })
checks.keyConfigured = await page.evaluate(async () => !!(await (await fetch('/api/config')).json()).google_maps_key)
await page.locator('.analyze-button').click()
await page.locator('.site-table').waitFor({ timeout: 120000 })
await page.getByRole('button', { name: 'Satellite', exact: true }).click()
await page.locator('.map-canvas[data-basemap="google"]').waitFor({ timeout: 20000 }).then(() => { checks.googleBasemap = true }, () => { checks.googleBasemap = false })
await page.waitForTimeout(4000)
checks.credit = (await page.locator('.google-credit').innerText().catch(() => '')).trim()
await shot('g1-google-satellite')
await page.getByRole('button', { name: '3D', exact: true }).click()
await page.waitForTimeout(6000)
await shot('g2-google-3d-map')
await page.getByRole('button', { name: '3D', exact: true }).click()

await page.locator('.place-search input').fill('Malgaon Kanker')
await page.locator('.place-results button').first().waitFor({ timeout: 20000 })
checks.searchProvider = (await page.locator('.place-results-credit img').count()) ? 'google' : 'photon'
checks.firstSuggestion = (await page.locator('.place-results button').first().innerText()).replace(/\s+/g, ' ')
await shot('g3-google-search')
await page.locator('.place-results button').first().click()
await page.waitForTimeout(2500)
checks.pickedNotice = (await page.locator('.map-notice').innerText().catch(() => '')).slice(0, 90)

await page.getByRole('button', { name: 'Example areas with real terrain' }).click()
await page.getByRole('button', { name: /Kanker west/ }).click()
await page.locator('.analyze-button').click()
await page.locator('.site-table').waitFor({ timeout: 120000 })
await page.waitForTimeout(1500)
checks.siteLinks = await page.locator('.site-links a').count()
await page.getByRole('button', { name: 'Inspect 3D model' }).click()
await page.locator('.terrain-scene[data-ready="true"]').waitFor({ timeout: 30000 })
await page.getByRole('button', { name: /satellite drape/i }).click()
await page.waitForTimeout(7000)
checks.inspectorCredit = (await page.locator('.google-credit--inspector').innerText().catch(() => '')).trim()
await shot('g4-inspector-google-drape')
await page.getByRole('button', { name: 'Close 3D view' }).click()

await page.getByRole('button', { name: 'Google 3D Earth' }).click()
await page.locator('.earth-viewport[data-ready="true"]').waitFor({ timeout: 40000 }).then(() => { checks.earthView = true }, () => { checks.earthView = false })
await page.waitForTimeout(12000)
await shot('g5-google-earth-site1')
await page.locator('.terrain-site-tabs button').nth(1).click()
await page.waitForTimeout(8000)
await shot('g6-google-earth-site2')
checks.earthOverlays = await page.evaluate(() => document.querySelectorAll('[data-planner-overlay]').length)

console.log(JSON.stringify({ target: BASE_URL, checks, problems: problems.slice(0, 12) }, null, 2))
await browser.close()
