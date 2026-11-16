import { expect, test, type Page } from '@playwright/test'

/** Sidebar pages (src/app/nav.ts). */
const PAGES = ['/', '/inbox', '/journal', '/bias', '/digests', '/calculator', '/settings'] as const
const WIDTHS = [1280, 1600, 1920, 2560] as const

/** Every API call fails fast: pages render their error/empty states, nothing reaches a backend. */
async function mockApi(page: Page) {
  // Match the URL path, not a glob: '**/api/**' would also catch the source module /src/api/client.ts.
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => route.fulfill({ status: 503, json: { detail: 'e2e' } }))
}

interface Geometry {
  innerWidth: number
  innerHeight: number
  scrollWidth: number
  scrollHeight: number
  scrollX: number
  scrollY: number
  footerBottom: number
}

function geometry(page: Page): Promise<Geometry> {
  return page.evaluate(() => {
    const doc = document.scrollingElement ?? document.documentElement
    const footer = document.querySelector('footer')
    if (!footer) throw new Error('status bar <footer> not found')
    return {
      innerWidth: window.innerWidth,
      innerHeight: window.innerHeight,
      scrollWidth: doc.scrollWidth,
      scrollHeight: doc.scrollHeight,
      scrollX: window.scrollX,
      scrollY: window.scrollY,
      footerBottom: footer.getBoundingClientRect().bottom,
    }
  })
}

/** Footer sits on the viewport bottom; the document is exactly one viewport, no page scroll. */
async function expectPinnedLayout(page: Page, where: string) {
  const g = await geometry(page)
  expect(Math.round(g.footerBottom), `${where}: footer bottom`).toBe(g.innerHeight)
  expect(g.scrollHeight, `${where}: document height`).toBeLessThanOrEqual(g.innerHeight)
  expect(g.scrollWidth, `${where}: document width`).toBeLessThanOrEqual(g.innerWidth)
  expect([g.scrollX, g.scrollY], `${where}: page scroll`).toEqual([0, 0])
}

/**
 * Long page: a tall block plus `.sr-only` texts at its bottom and far right, the exact shape that
 * stretched the document before M8-11 (absolute elements escaping a non-positioned <main>).
 */
async function addLongContent(page: Page) {
  await page.evaluate(() => {
    const main = document.querySelector('main')
    if (!main) throw new Error('<main> not found')
    const block = document.createElement('div')
    block.dataset.e2eLong = ''
    block.style.height = '3000px'
    const bottom = document.createElement('span')
    bottom.className = 'sr-only'
    bottom.textContent = 'bottom'
    const right = document.createElement('span')
    right.className = 'sr-only'
    right.style.marginLeft = '4000px'
    right.textContent = 'right'
    block.append(right)
    main.append(block, bottom)
  })
}

/** Loads a page and waits until the lazy app shell is on screen. */
async function open(page: Page, path: string) {
  await page.goto(path)
  await expect(page.locator('main')).toBeVisible()
}

async function gotoViaSidebar(page: Page, path: string) {
  await page.locator(`aside nav a[href="${path}"]`).click()
  await expect(page).toHaveURL((url) => url.pathname === path)
}

test.beforeEach(async ({ page }) => {
  await mockApi(page)
})

test('footer stays at the viewport bottom on every page and width, short and long content', async ({ page }) => {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 900 })
    for (const path of PAGES) {
      await open(page, path)
      await expectPinnedLayout(page, `${path} @${width} short`)
      await addLongContent(page)
      await expectPinnedLayout(page, `${path} @${width} long`)
    }
  }
})

test('scrolling past the end of a long page moves only the content area', async ({ page }) => {
  await open(page, '/journal')
  await addLongContent(page)
  const main = page.locator('main')
  await main.hover()
  for (let i = 0; i < 8; i += 1) await page.mouse.wheel(0, 2000)
  await expect.poll(() => main.evaluate((el) => el.scrollTop)).toBeGreaterThan(0)
  await expectPinnedLayout(page, 'after wheel overscroll')
  await page.keyboard.press('End')
  await expectPinnedLayout(page, 'after End key')
})

test('switching pages resets the content scroll to the top, footer stays pinned', async ({ page }) => {
  await open(page, '/')
  for (let round = 0; round < 3; round += 1) {
    for (const path of PAGES) {
      await gotoViaSidebar(page, path)
      await addLongContent(page)
      await page.locator('main').evaluate((el) => {
        el.scrollTop = el.scrollHeight
      })
      const next = PAGES[(PAGES.indexOf(path) + 1) % PAGES.length]
      await gotoViaSidebar(page, next)
      await expect.poll(() => page.locator('main').evaluate((el) => el.scrollTop), { message: `${path} -> ${next}` }).toBe(0)
      await expectPinnedLayout(page, `${path} -> ${next}`)
    }
  }
})

test('window resize keeps the footer at the bottom', async ({ page }) => {
  await open(page, '/')
  await addLongContent(page)
  for (const [width, height] of [
    [1280, 720],
    [2560, 1440],
    [1366, 768],
    [1920, 1080],
  ] as const) {
    await page.setViewportSize({ width, height })
    await expectPinnedLayout(page, `resize ${width}x${height}`)
  }
})
