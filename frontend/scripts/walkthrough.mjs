// Visual walkthrough of the Phase 3.1 planner; writes screenshots to tmp/shots.
import { chromium } from 'playwright-core'

import { resolve } from 'node:path'
// Target another deployment with POND_URL, e.g. http://10.1.75.53:3233/
const BASE_URL = process.env.POND_URL ?? 'http://127.0.0.1:8000/'

const out = resolve('..', 'tmp', 'shots')
const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const problems = []
page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`))
page.on('console', (message) => { if (message.type() === 'error') problems.push(`console: ${message.text()}`) })
const shot = (name) => page.screenshot({ path: resolve(out, `${name}.png`) })
const results = () => page.locator('.site-table').waitFor({ state: 'visible', timeout: 90000 })

process.on('uncaughtException', async (error) => {
  await page.screenshot({ path: resolve(out, 'failure.png') }).catch(() => {})
  const message = await page.locator('.error-message, .map-notice').allInnerTexts().catch(() => [])
  console.error('walkthrough failed:', error.message.split('\n')[0], '| on-page messages:', message, '| problems:', problems)
  process.exit(1)
})
// Lossy campus links can drop the first connection; retry the initial load.
for (let attempt = 1; ; attempt++) {
  try { await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 }); break }
  catch (error) { if (attempt === 4) throw error; await page.waitForTimeout(2000) }
}
await page.locator('.map-canvas[data-ready="true"]').waitFor({ timeout: 30000 })
await page.waitForTimeout(2500)
await shot('01-start')
await page.locator('.analyze-button').click()
await results()
await page.waitForTimeout(1500)
await shot('02-sample-results')
console.log('sample table:', (await page.locator('.site-table').innerText()).replace(/\s+/g, ' '))
await page.getByRole('button', { name: 'Satellite', exact: true }).click()
await page.waitForTimeout(2500)
await shot('03-satellite')
await page.getByRole('button', { name: '3D', exact: true }).click()
await page.waitForTimeout(4000)
await shot('04-3d-terrain')
await page.getByRole('button', { name: '3D', exact: true }).click()
await page.getByRole('button', { name: 'Topo', exact: true }).click()
await page.getByText('Copernicus GLO-30').click()
await page.waitForTimeout(1500)
const selectionVisible = await page.evaluate(() => document.querySelector('.control-hint')?.textContent)
await shot('05-copernicus-switch')
console.log('after source switch hint:', selectionVisible)
await page.getByRole('button', { name: 'Example areas with real terrain' }).click()
await page.getByRole('button', { name: /Maikal ridge front/ }).click()
await page.waitForTimeout(1500)
await page.locator('.analyze-button').click()
await results()
await page.waitForTimeout(2500)
await shot('06-example-results')
console.log('example table:', (await page.locator('.site-table').innerText()).replace(/\s+/g, ' '))
await page.locator('.result-scroll').evaluate((node) => node.scrollTo(0, 900))
await page.waitForTimeout(500)
await shot('07-results-scrolled')
await page.getByRole('button', { name: 'Inspect 3D model' }).click()
await page.locator('.terrain-scene[data-ready="true"]').waitFor({ timeout: 30000 })
await page.waitForTimeout(1000)
await shot('08-inspector')
await page.getByRole('button', { name: 'Satellite drape' }).click()
await page.waitForTimeout(5000)
await shot('09-inspector-imagery')
await page.getByRole('button', { name: 'Close 3D view' }).click()
await page.getByRole('button', { name: 'Satellite', exact: true }).click()
await page.getByRole('button', { name: '3D', exact: true }).click()
await page.waitForTimeout(5000)
await shot('09b-example-3d-satellite')
await page.getByRole('button', { name: '3D', exact: true }).click()
await page.locator('.maplibregl-ctrl-globe').click()
const mapBox = await page.locator('.map-canvas').boundingBox()
await page.mouse.move(mapBox.x + mapBox.width / 2, mapBox.y + mapBox.height / 2)
for (let i = 0; i < 18; i++) { await page.mouse.wheel(0, 600); await page.waitForTimeout(120) }
await page.waitForTimeout(4000)
await shot('09c-globe')
await page.locator('.place-search input').fill('Ralegan Siddhi')
await page.locator('.place-results button').first().waitFor({ timeout: 15000 }).catch(() => problems.push('no search results'))
await shot('10-search')
console.log(JSON.stringify({ problems: problems.slice(0, 20) }, null, 2))
await browser.close()
