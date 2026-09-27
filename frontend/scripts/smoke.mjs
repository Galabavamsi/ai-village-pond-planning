import { chromium } from 'playwright-core'

import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
// Target another deployment with POND_URL, e.g. http://10.1.75.53:3233/
const BASE_URL = process.env.POND_URL ?? 'http://127.0.0.1:8000/'

const browser = await chromium.launch({
  headless: true,
  executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  args: ['--no-sandbox'],
})
const screenshots = resolve('..', 'output', 'screenshots')
await mkdir(screenshots, { recursive: true })

async function runViewport(name, viewport) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 })
  const page = await context.newPage()
  const errors = []
  const tileResponses = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('requestfailed', (request) => errors.push(`${request.url()}: ${request.failure()?.errorText}`))
  page.on('response', (response) => {
    if (response.url().includes('opentopomap')) tileResponses.push(response.status())
  })
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' })
  const analyzeButton = name === 'mobile' ? page.locator('.mobile-analyze-bar button') : page.locator('.analyze-button')
  await analyzeButton.waitFor({ state: 'visible' })
  await page.waitForTimeout(1200)
  await page.screenshot({ path: resolve(screenshots, `${name}-before.png`), fullPage: true })
  await analyzeButton.click()
  await page.locator('.site-summary strong').waitFor({ state: 'visible', timeout: 60000 })
  await page.screenshot({ path: resolve(screenshots, `${name}-results.png`), fullPage: true })
  const text = await page.locator('.results-panel').innerText()
  console.log(JSON.stringify({ name, results: text.slice(0, 600), errors: errors.slice(0, 10), tileResponses: tileResponses.slice(0, 10) }, null, 2))
  if (name === 'desktop') {
    const firstSite = await page.locator('.site-summary').innerText()
    await page.getByRole('button', { name: 'Draw rectangle' }).click()
    const map = await page.locator('.map-canvas').boundingBox()
    if (!map) throw new Error('Map canvas has no bounds')
    const from = { x: map.x + map.width * 0.58, y: map.y + map.height * 0.28 }
    const to = { x: map.x + map.width * 0.82, y: map.y + map.height * 0.52 }
    await page.mouse.move(from.x, from.y)
    await page.mouse.down()
    await page.mouse.move(to.x, to.y, { steps: 12 })
    await page.mouse.up()
    await page.locator('.drawing-tip').waitFor({ state: 'hidden', timeout: 10000 })
    await analyzeButton.click()
    await page.locator('.site-summary strong').waitFor({ state: 'visible', timeout: 60000 })
    const nextSite = await page.locator('.site-summary').innerText()
    if (firstSite === nextSite) throw new Error('Drawing a different area did not change the recommended site')
    await page.screenshot({ path: resolve(screenshots, 'desktop-drawn-results.png'), fullPage: true })
    console.log(JSON.stringify({ drawnAreaChangedSite: true, firstSite, nextSite, errors: errors.slice(-5) }, null, 2))
  }
  await context.close()
}

try {
  await runViewport('desktop', { width: 1440, height: 900 })
  await runViewport('mobile', { width: 390, height: 844 })
} finally {
  await browser.close()
}
