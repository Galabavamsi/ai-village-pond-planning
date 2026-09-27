// Capture the screenshots used in the Phase 3 report (output/screenshots/report).
//   POND_URL=http://10.1.75.53:3233/ node scripts/report-shots.mjs
import { chromium } from 'playwright-core'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

const BASE_URL = process.env.POND_URL ?? 'http://127.0.0.1:8000/'
const out = resolve('..', 'output', 'screenshots', 'report')
await mkdir(out, { recursive: true })
const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', args: ['--no-sandbox'] })
const problems = []

async function open(viewport, scale = 1.5) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: scale })
  const page = await context.newPage()
  page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`))
  for (let attempt = 1; ; attempt++) {
    try { await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 }); break }
    catch (error) { if (attempt === 5) throw error; await page.waitForTimeout(2000) }
  }
  await page.locator('.map-canvas[data-ready="true"]').waitFor({ timeout: 60000 })
  await page.waitForTimeout(2500)
  return { context, page }
}
const shot = (page, name, options = {}) => page.screenshot({ path: resolve(out, `${name}.png`), ...options })
const results = (page) => page.locator('.site-table').waitFor({ state: 'visible', timeout: 180000 })
const exampleButton = (page, name) => page.getByRole('button', { name })

// Desktop tour.
{
  const { context, page } = await open({ width: 1440, height: 900 })
  await page.getByRole('button', { name: 'Example areas with real terrain' }).click()
  await page.waitForTimeout(400)
  await shot(page, 'r02-examples')
  await page.getByRole('button', { name: 'Example areas with real terrain' }).click()
  await page.locator('.analyze-button').click()
  await results(page)
  await page.waitForTimeout(2500)
  await shot(page, 'r01-sample-results')
  await page.getByRole('button', { name: 'How it works' }).click()
  await page.waitForTimeout(400)
  await shot(page, 'r13-help')
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await page.locator('.place-search input').fill('Kanker')
  await page.locator('.place-results button').first().waitFor({ timeout: 20000 })
  await page.waitForTimeout(300)
  await shot(page, 'r03-search')
  await page.keyboard.press('Escape')
  await page.locator('.place-search input').fill('')
  await page.getByRole('button', { name: 'Example areas with real terrain' }).click()
  await exampleButton(page, /Maikal ridge front/).click()
  await page.locator('.analyze-button').click()
  await results(page)
  await page.waitForTimeout(3000)
  await page.locator('.map-notice button').click().catch(() => {})
  await shot(page, 'r04-example-topo')
  await page.getByRole('button', { name: 'Satellite', exact: true }).click()
  await page.getByRole('button', { name: '3D', exact: true }).click()
  await page.waitForTimeout(6000)
  await shot(page, 'r05-3d-satellite')
  await page.getByRole('button', { name: '3D', exact: true }).click()
  await page.locator('.maplibregl-ctrl-globe').click()
  const box = await page.locator('.map-canvas').boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  for (let i = 0; i < 18; i++) { await page.mouse.wheel(0, 600); await page.waitForTimeout(120) }
  await page.waitForTimeout(4500)
  await shot(page, 'r06-globe')
  await page.getByRole('button', { name: 'Inspect 3D model' }).click()
  await page.locator('.terrain-scene[data-ready="true"]').waitFor({ timeout: 30000 })
  await page.waitForTimeout(1200)
  await shot(page, 'r08-inspector-relief')
  await page.getByRole('button', { name: 'Satellite drape' }).click()
  await page.waitForTimeout(6000)
  await shot(page, 'r09-inspector-imagery')
  await context.close()
}

// Tall viewport so the whole results panel is visible at once.
{
  const { context, page } = await open({ width: 1440, height: 2700 }, 1.25)
  await page.getByRole('button', { name: 'Example areas with real terrain' }).click()
  await exampleButton(page, /Kanker west/).click()
  await page.locator('.analyze-button').click()
  await results(page)
  await page.getByRole('button', { name: 'Show as table' }).click()
  await page.waitForTimeout(1500)
  await page.locator('.results-panel').screenshot({ path: resolve(out, 'r07-results-panel.png') })
  await page.locator('.controls-panel').screenshot({ path: resolve(out, 'r14-controls-panel.png') })
  await context.close()
}

// Upload a real DEM-derived contour KML.
{
  const { context, page } = await open({ width: 1440, height: 900 })
  await page.locator('input[type=file]').setInputFiles(resolve('..', 'contour-maps', 'real', 'kanker-west_glo30.kml'))
  await page.getByText(/contour lines ·/).waitFor({ state: 'attached', timeout: 60000 })
  await page.locator('.analyze-button').click()
  await results(page)
  await page.waitForTimeout(2500)
  await shot(page, 'r11-upload-results')
  await context.close()
}

// Mobile.
{
  const { context, page } = await open({ width: 390, height: 844 }, 2)
  await page.locator('.mobile-analyze-bar button').click()
  await results(page)
  await page.waitForTimeout(2500)
  await shot(page, 'r10-mobile', { fullPage: true })
  await context.close()
}

// Swagger UI of the deployed API.
{
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1.25 })
  const page = await context.newPage()
  for (let attempt = 1; ; attempt++) {
    try { await page.goto(new URL('docs', BASE_URL).href, { waitUntil: 'networkidle', timeout: 60000 }); break }
    catch (error) { if (attempt === 5) throw error; await page.waitForTimeout(2000) }
  }
  await page.locator('.opblock').first().waitFor({ timeout: 30000 })
  await shot(page, 'r12-docs')
  await context.close()
}

console.log(JSON.stringify({ target: BASE_URL, problems }, null, 2))
await browser.close()
