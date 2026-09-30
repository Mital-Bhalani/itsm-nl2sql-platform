import { expect, test, type Page } from '@playwright/test'

// Every page: hash route and the title in its header band.
const PAGES = [
  { route: '/', title: 'ITSM Insights', nav: 'Home' },
  { route: '/ask', title: 'Ask a question', nav: 'Ask' },
  { route: '/dashboard', title: 'Service dashboard', nav: 'Dashboard' },
  { route: '/explorer', title: 'Data explorer', nav: 'Explorer' },
  { route: '/incident', title: 'Incident detail', nav: 'Incident' },
  { route: '/catalog', title: 'Semantic catalog', nav: 'Catalog' },
  { route: '/evals', title: 'Evaluation', nav: 'Evals' },
  { route: '/data-check', title: 'Data check', nav: 'Data check' },
]

/** Collect console errors and uncaught exceptions for the life of the page. */
function watchErrors(page: Page) {
  const errors: string[] = []
  page.on('console', (msg) => {
    // A 404 from the eval-history endpoints only means an older API without them: the page
    // shows its empty state, which is the behaviour under test, so it is not an error here.
    if (msg.type() === 'error' && !/\/api\/evals(\/history)?(\?|$)/.test(msg.location().url)) errors.push(msg.text())
  })
  page.on('pageerror', (err) => errors.push(err.message))
  return errors
}

const open = (page: Page, route: string, theme?: 'light' | 'dark') =>
  page.goto(`${theme ? `?theme=${theme}` : ''}#${route}`)

for (const theme of ['light', 'dark'] as const) {
  test.describe(`pages render in ${theme} theme`, () => {
    for (const { route, title } of PAGES) {
      test(`${route} shows "${title}" without console errors`, async ({ page }) => {
        const errors = watchErrors(page)
        await open(page, route, theme)
        await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()
        await expect(page.locator('html')).toHaveClass(theme === 'dark' ? /\bdark\b/ : /^(?!.*\bdark\b)/)
        // Let data queries settle so late errors are caught too.
        await page.waitForLoadState('networkidle')
        expect(errors, errors.join('\n')).toEqual([])
      })
    }
  })
}

test('theme toggle sits in the top-right corner of every page', async ({ page }) => {
  const width = page.viewportSize()!.width
  for (const { route } of PAGES) {
    await open(page, route)
    const box = await page.getByTestId('theme-toggle').boundingBox()
    expect(box, route).not.toBeNull()
    expect(box!.x, `${route}: x`).toBeGreaterThan(width * 0.8)
    expect(box!.y, `${route}: y`).toBeLessThan(60)
  }
})

test('theme toggle flips dark mode and the choice survives a reload', async ({ page }) => {
  await open(page, '/dashboard')
  const html = page.locator('html')
  await expect(html).not.toHaveClass(/\bdark\b/)
  await page.getByTestId('theme-toggle').click()
  await expect(html).toHaveClass(/\bdark\b/)
  await page.reload()
  await expect(page.getByRole('heading', { level: 1, name: 'Service dashboard' })).toBeVisible()
  await expect(html).toHaveClass(/\bdark\b/)
  await page.getByTestId('theme-toggle').click()
  await expect(html).not.toHaveClass(/\bdark\b/)
  await page.reload()
  await expect(html).not.toHaveClass(/\bdark\b/)
})

test.describe('phone layout', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('sidebar becomes a drawer: menu opens it, Escape closes it and returns focus', async ({ page }) => {
    await open(page, '/')
    await expect(page.getByRole('heading', { level: 1, name: 'ITSM Insights' })).toBeVisible()
    // The desktop sidebar is not shown; the drawer is not rendered until opened.
    await expect(page.locator('aside').filter({ hasText: 'NL2SQL over ticket data' })).toBeHidden()
    const menu = page.getByRole('button', { name: 'Open menu' })
    await expect(menu).toBeVisible()
    await menu.click()
    const drawer = page.getByTestId('drawer')
    await expect(drawer).toBeVisible()
    await expect(drawer.getByRole('link', { name: 'Dashboard' })).toBeVisible()
    // Focus moved inside the drawer.
    expect(await drawer.evaluate((el) => el.contains(document.activeElement))).toBe(true)
    await page.keyboard.press('Escape')
    await expect(drawer).toHaveCount(0)
    await expect(menu).toBeFocused()
    // Navigating from the drawer closes it.
    await menu.click()
    await page.getByTestId('drawer').getByRole('link', { name: 'Catalog' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Semantic catalog' })).toBeVisible()
    await expect(page.getByTestId('drawer')).toHaveCount(0)
    await expect(page.getByTestId('theme-toggle')).toBeVisible()
  })
})

test('page switches never wait for a code download after the first page', async ({ page }) => {
  await open(page, '/')
  await expect(page.getByRole('heading', { level: 1, name: 'ITSM Insights' })).toBeVisible()
  await page.waitForLoadState('networkidle') // idle-time prefetch of every page chunk has run
  const pageSpinner = page.getByText('Loading page…')
  for (const { nav, title } of PAGES.slice(1)) {
    await page.getByRole('navigation').getByRole('link', { name: nav, exact: true }).click()
    // The chunk-loading fallback must not appear at any point in the next 200 ms.
    const started = Date.now()
    while (Date.now() - started < 200) {
      expect(await pageSpinner.count(), `${nav}: chunk spinner shown`).toBe(0)
      await page.waitForTimeout(20)
    }
    await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()
  }
})

test('saved questions: star on the Ask page, listed on Home, removable', async ({ page }) => {
  // Seed a saved question the same way the app stores it (no model call needed).
  await open(page, '/')
  await page.evaluate(() => localStorage.setItem('itsm-insights-saved', JSON.stringify(['How many P1 incidents are open?'])))
  await page.reload()
  await expect(page.getByTestId('home-saved')).toContainText('How many P1 incidents are open?')
  await page.getByRole('navigation').getByRole('link', { name: 'Ask', exact: true }).click()
  const strip = page.getByTestId('saved-questions')
  await expect(strip).toContainText('How many P1 incidents are open?')
  await strip.getByRole('button', { name: /Remove saved question/ }).click()
  await expect(page.getByTestId('saved-questions')).toHaveCount(0)
})

test('evals page shows its history cards (empty state or stored runs)', async ({ page }) => {
  await open(page, '/evals')
  await expect(page.getByTestId('recent-runs')).toBeVisible()
  await expect(page.getByTestId('flaky-questions')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Run evaluation' })).toBeEnabled()
})
