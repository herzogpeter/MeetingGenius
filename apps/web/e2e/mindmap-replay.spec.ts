import path from 'node:path'
import { expect, test } from '@playwright/test'

type MindmapMetrics = {
  nodeCount: number
  uniqueNormalizedCount: number
  uniqueRatio: number
  duplicates: Array<{ text: string; count: number }>
  hasCategories: Record<string, boolean>
}

function asBool(value: unknown): boolean {
  const normalized = String(value ?? '').trim().toLowerCase()
  return normalized === '1' || normalized === 'true' || normalized === 'yes' || normalized === 'on'
}

test('replay transcript drives mindmap updates', async ({ page }, testInfo) => {
  await page.goto('/')
  await expect(page.getByText('WS: open')).toBeVisible({ timeout: 60_000 })

  await page.getByRole('button', { name: 'Reset' }).click()

  const viewToggle = page.getByRole('button', { name: /^View:/ })
  const viewText = (await viewToggle.textContent()) ?? ''
  if (viewText.includes('Whiteboard')) await viewToggle.click()
  await expect(page.locator('.mgMindmap')).toBeVisible()

  await page.locator('summary', { hasText: 'Replay transcript (simulation)' }).click()

  const fixturePath = path.join(path.dirname(testInfo.file), 'fixtures', 'complex_transcript.txt')
  await page.locator('#mgReplayFile').setInputFiles(fixturePath)
  await expect(page.getByLabel('Full transcript')).not.toHaveValue('')

  await page.getByLabel('WPM').fill('1200')
  await page.getByLabel('Max words/chunk').fill('18')
  await page.getByLabel('Min sec/chunk').fill('0.2')

  const asFinal = page.getByLabel('Send chunks as final (triggers board AI per chunk)')
  if (await asFinal.isChecked()) await asFinal.uncheck()

  await page.getByRole('button', { name: 'Start replay' }).click()
  await expect(page.getByText(/Status: (running|done)/)).toBeVisible()

  try {
    await page.waitForFunction(
      () => document.querySelectorAll('.mgMindmapNodeText').length >= 10,
      null,
      { timeout: 90_000 },
    )
  } catch {
    if (await page.getByText(/Mindmap AI disabled:/).isVisible()) {
      test.skip(true, 'Mindmap AI is disabled. Set provider API keys (see .env.example).')
    }
    throw new Error('Mindmap nodes did not appear after replay started (is the backend AI configured?).')
  }

  const targetChunksRaw = process.env.E2E_TARGET_CHUNKS
  if (targetChunksRaw) {
    const targetChunks = Number.parseInt(targetChunksRaw, 10)
    if (Number.isFinite(targetChunks) && targetChunks > 0) {
      // Optional: let the replay progress so metrics reflect more than the first chunk.
      await page.waitForFunction(
        (target: number) => {
          const muted = Array.from(document.querySelectorAll('.mgMuted'))
          const statusEl = muted.find((el) => (el.textContent ?? '').trim().startsWith('Status:'))
          const text = (statusEl?.textContent ?? '').trim()
          const match = text.match(/Status:\s*(\w+)(?:.*?(\d+)\/(\d+)\s*chunks)?/)
          if (!match) return false
          const status = (match[1] ?? '').toLowerCase()
          const idx = match[2] ? Number.parseInt(match[2], 10) : 0
          if (status === 'done') return true
          if (status !== 'running') return false
          return idx >= target
        },
        targetChunks,
        { timeout: 90_000 },
      )
    }
  }

  const metrics = await page.evaluate<MindmapMetrics>(() => {
    const normalize = (s: string) =>
      s
        .trim()
        .toLowerCase()
        .replace(/\s+/g, ' ')
        .replace(/[^a-z0-9 ]/g, '')
        .replace(/\s+/g, ' ')
        .trim()

    const raw = Array.from(document.querySelectorAll('.mgMindmapNodeText'))
      .map((el) => (el.textContent ?? '').trim())
      .filter(Boolean)

    const normalized = raw.map(normalize).filter(Boolean)
    const counts: Record<string, number> = {}
    for (const t of normalized) counts[t] = (counts[t] ?? 0) + 1

    const duplicates = Object.entries(counts)
      .filter(([, c]) => c > 1)
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, 20)
      .map(([text, count]) => ({ text, count }))

    const categories = ['decisions', 'action items', 'open questions', 'risks blockers', 'next steps']
    const hasCategories: Record<string, boolean> = {}
    for (const c of categories) hasCategories[c] = (counts[c] ?? 0) > 0

    const nodeCount = raw.length
    const uniqueNormalizedCount = Object.keys(counts).length
    const uniqueRatio = nodeCount ? uniqueNormalizedCount / nodeCount : 0

    return { nodeCount, uniqueNormalizedCount, uniqueRatio, duplicates, hasCategories }
  })

  await testInfo.attach('mindmap-metrics.json', {
    body: JSON.stringify(metrics, null, 2),
    contentType: 'application/json',
  })
  await testInfo.attach('mindmap.png', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  })
  console.log('Mindmap metrics:', metrics)

  const stop = page.getByRole('button', { name: 'Stop' })
  if (await stop.isEnabled().catch(() => false)) await stop.click()

  if (asBool(process.env.E2E_STRICT)) {
    const minNodes = Number.parseInt(process.env.E2E_MIN_NODES ?? '12', 10)
    const minUniqueRatio = Number.parseFloat(process.env.E2E_MIN_UNIQUE_RATIO ?? '0.4')
    expect(metrics.nodeCount).toBeGreaterThanOrEqual(minNodes)
    expect(metrics.uniqueRatio).toBeGreaterThanOrEqual(minUniqueRatio)
  }
})
