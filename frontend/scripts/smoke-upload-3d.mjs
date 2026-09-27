import { chromium } from 'playwright-core'

import { createHash } from 'node:crypto'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
// Target another deployment with POND_URL, e.g. http://10.1.75.53:3233/
const BASE_URL = process.env.POND_URL ?? 'http://127.0.0.1:8000/'

const browser = await chromium.launch({
  headless: true,
  executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader'],
})
const sampleFile = resolve('..', 'contour-maps', 'contours_1m.kml')
const independentFile = resolve('..', 'contour-maps', 'copernicus_glo30_demo.kml')
const screenshots = resolve('..', 'output', 'screenshots')
await mkdir(screenshots, { recursive: true })

async function exercise(name, viewport) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  const analysisResponses = []
  page.on('response', async (response) => {
    if (response.url().endsWith('/api/analyze-area')) {
      analysisResponses.push({ status: response.status(), body: await response.json() })
    }
  })
  // Lossy campus links can drop the first connection; retry the initial load.
  for (let attempt = 1; ; attempt++) {
    try { await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 }); break }
    catch (error) { if (attempt === 4) throw error; await page.waitForTimeout(2000) }
  }
  if (!(await page.title()).includes('Village Pond')) throw new Error('Unexpected page title')
  if (name === 'mobile') await page.getByRole('button', { name: 'Open study area controls' }).click()
  await page.locator('input[type=file]').setInputFiles(sampleFile)
  await page.getByText(/contour lines ·/).waitFor({ state: 'attached', timeout: 30000 })
  if (name === 'mobile') await page.getByRole('button', { name: 'Open study area controls' }).click()
  await page.getByRole('button', { name: 'Enter rainfall' }).click()
  if (name === 'mobile') await page.getByRole('button', { name: 'Close controls' }).click()
  const analyze = name === 'mobile' ? page.locator('.mobile-analyze-bar button') : page.locator('.analyze-button')
  await analyze.click()
  await page.locator('.site-summary strong').waitFor({ state: 'visible', timeout: 60000 })
  const analysis = analysisResponses.at(-1)
  if (!analysis || analysis.status !== 200 || !analysis.body.elevation.source.includes('Uploaded contours')) {
    throw new Error('Analysis did not use the uploaded contour grid')
  }
  if (analysis.body.terrain_preview.elevation_m.length < 100) throw new Error('3D grid missing')
  const open3D = name === 'mobile' ? page.locator('.map-mobile-actions button').filter({ hasText: '3D model' }) : page.getByRole('button', { name: 'Inspect 3D model' })
  await open3D.click()
  await page.locator('.terrain-scene[data-ready=true] canvas').waitFor({ state: 'visible', timeout: 20000 })
  await page.screenshot({ path: resolve(screenshots, `upload-3d-${name}-initial.png`), fullPage: false })
  const canvas = page.locator('.terrain-scene canvas')
  const first = await canvas.screenshot()
  const firstHash = createHash('sha256').update(first).digest('hex')
  const box = await canvas.boundingBox()
  if (!box) throw new Error('3D canvas has no bounds')
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2 + 150, box.y + box.height / 2 + 30, { steps: 12 })
  await page.mouse.up()
  await page.waitForTimeout(300)
  const movedHash = createHash('sha256').update(await canvas.screenshot()).digest('hex')
  if (firstHash === movedHash) throw new Error('Dragging did not change the 3D rendered view')
  await page.getByRole('button', { name: 'Reset 3D view' }).click()
  const slider = page.locator('.terrain-range input')
  await slider.focus()
  await slider.press('End')
  if (!(await page.locator('.terrain-range').innerText()).includes('40×')) throw new Error('Vertical exaggeration did not update')
  await page.locator('.terrain-site-tabs button').nth(1).click()
  if (!(await page.locator('.terrain-inspector-top').innerText()).includes('Site 02')) throw new Error('3D site selection did not update')
  await page.screenshot({ path: resolve(screenshots, `upload-3d-${name}.png`), fullPage: false })
  await page.getByRole('button', { name: 'Close 3D view' }).click()
  if (!(await page.locator('.map-canvas').isVisible())) throw new Error('2D fallback map is missing')
  if (errors.length) throw new Error(`Browser errors: ${errors.join(' | ')}`)
  console.log(JSON.stringify({ viewport: name, upload: 'sample KML', source: analysis.body.elevation.source, sites: analysis.body.recommendations.length, meshVertices: analysis.body.terrain_preview.elevation_m.length, rotated: true, slider: '40×', selected: 'Site 02', errors }, null, 2))
  await context.close()
}

async function exerciseIndependentContours() {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  let analysis = null
  page.on('response', async (response) => {
    if (response.url().endsWith('/api/analyze-area')) analysis = { status: response.status(), body: await response.json() }
  })
  // Lossy campus links can drop the first connection; retry the initial load.
  for (let attempt = 1; ; attempt++) {
    try { await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 }); break }
    catch (error) { if (attempt === 4) throw error; await page.waitForTimeout(2000) }
  }
  await page.locator('input[type=file]').setInputFiles(independentFile)
  await page.getByText(/73 contour lines/).waitFor({ state: 'attached', timeout: 30000 })
  await page.getByRole('button', { name: 'Enter rainfall' }).click()
  await page.locator('.analyze-button').click()
  await page.locator('.site-summary strong').waitFor({ state: 'visible', timeout: 60000 })
  if (!analysis || analysis.status !== 200 || !analysis.body.elevation.source.includes('copernicus_glo30_demo.kml')) {
    throw new Error('Independent contours were not used for analysis')
  }
  if (analysis.body.recommendations[0].location.coordinates[0] <= 81.3) throw new Error('Result remained in sample map extent')
  await page.getByRole('button', { name: 'Inspect 3D model' }).click()
  await page.locator('.terrain-scene[data-ready=true] canvas').waitFor({ state: 'visible', timeout: 20000 })
  await page.screenshot({ path: resolve(screenshots, 'upload-3d-independent-dem.png'), fullPage: false })
  if (errors.length) throw new Error(`Independent upload browser errors: ${errors.join(' | ')}`)
  console.log(JSON.stringify({ upload: 'independent real GLO-30-derived KML', sites: analysis.body.recommendations.length, longitude: analysis.body.recommendations[0].location.coordinates[0], contourLines: 73, errors }, null, 2))
  await context.close()
}

try {
  await exercise('desktop', { width: 1440, height: 900 })
  await exercise('mobile', { width: 390, height: 844 })
  await exerciseIndependentContours()
} finally {
  await browser.close()
}
