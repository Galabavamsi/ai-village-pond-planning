// Screenshot the main screens in both themes for a visual review (tmp/theme-review).
//   POND_URL=http://127.0.0.1:8000/ node scripts/theme-review.mjs
import { chromium } from 'playwright-core'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

const BASE_URL = process.env.POND_URL ?? 'http://127.0.0.1:8000/'
const out = resolve('..', 'tmp', 'theme-review')
await mkdir(out, { recursive: true })
const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', args: ['--no-sandbox'] })
const problems = []

for (const theme of ['dark', 'light']) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
  await context.addInitScript((value) => localStorage.setItem('pond-theme', value), theme)
  const page = await context.newPage()
  page.on('pageerror', (error) => problems.push(`${theme} pageerror: ${error.message}`))
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.locator('.map-canvas[data-ready="true"]').waitFor({ timeout: 60000 })
  await page.waitForTimeout(2500)
  await page.screenshot({ path: resolve(out, `${theme}-01-start.png`) })
  await page.getByRole('button', { name: 'Example areas with real terrain' }).click()
  await page.waitForTimeout(400)
  await page.screenshot({ path: resolve(out, `${theme}-02-examples.png`) })
  await page.getByRole('button', { name: 'Example areas with real terrain' }).click()
  await page.locator('.analyze-button').click()
  await page.locator('.site-table').waitFor({ state: 'visible', timeout: 180000 })
  await page.waitForTimeout(3000)
  await page.screenshot({ path: resolve(out, `${theme}-03-results.png`) })
  await page.locator('.results-panel, .results').first().evaluate((node) => node.scrollTo?.(0, 900)).catch(() => {})
  await page.mouse.move(1200, 500)
  await page.mouse.wheel(0, 900)
  await page.waitForTimeout(600)
  await page.screenshot({ path: resolve(out, `${theme}-04-results-scrolled.png`) })
  await page.mouse.wheel(0, 1600)
  await page.waitForTimeout(600)
  await page.screenshot({ path: resolve(out, `${theme}-05-results-bottom.png`) })
  await page.getByRole('button', { name: 'How it works' }).click()
  await page.waitForTimeout(400)
  await page.screenshot({ path: resolve(out, `${theme}-06-help.png`) })
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  const inspect = page.getByRole('button', { name: /Inspect 3D model/ })
  if (await inspect.count()) {
    await inspect.first().click()
    await page.waitForTimeout(7000)
    await page.screenshot({ path: resolve(out, `${theme}-07-inspector.png`) })
  }
  await context.close()
}

// Phone layout and the Google Earth view, dark theme only.
{
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true })
  const page = await context.newPage()
  page.on('pageerror', (error) => problems.push(`mobile pageerror: ${error.message}`))
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.locator('.map-canvas[data-ready="true"]').waitFor({ timeout: 60000 })
  await page.waitForTimeout(2000)
  await page.screenshot({ path: resolve(out, 'dark-08-mobile.png'), fullPage: true })
  await page.locator('.mobile-analyze-bar button').click()
  await page.locator('.site-summary strong').waitFor({ state: 'visible', timeout: 180000 })
  await page.waitForTimeout(1500)
  await page.screenshot({ path: resolve(out, 'dark-09-mobile-results.png'), fullPage: true })
  await context.close()
}
{
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()
  page.on('pageerror', (error) => problems.push(`earth pageerror: ${error.message}`))
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.locator('.map-canvas[data-ready="true"]').waitFor({ timeout: 60000 })
  await page.locator('.analyze-button').click()
  await page.locator('.site-table').waitFor({ state: 'visible', timeout: 180000 })
  const earth = page.getByRole('button', { name: /Google 3D Earth/ })
  if (await earth.count()) {
    await earth.first().click()
    await page.waitForTimeout(12000)
    await page.screenshot({ path: resolve(out, 'dark-10-earth.png') })
  }
  await context.close()
}
await browser.close()
console.log(problems.length ? problems.join('\n') : 'no page errors')
