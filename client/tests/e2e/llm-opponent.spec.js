import { expect, test } from '@playwright/test'

function isMoveResponse(response, expectedMoveUci) {
  const request = response.request()
  return (
    request.method() === 'POST' &&
    response.url().includes('/api/games/') &&
    response.url().includes('/move/') &&
    (request.postData() ?? '').includes(`"move_uci":"${expectedMoveUci}"`)
  )
}

test('user can start game vs llm and receive an AI reply', async ({ page }) => {
  await page.goto('/')

  await expect(page.locator('#llm-provider')).toBeVisible()
  await expect(page.locator('#llm-model')).toBeVisible()
  await page.getByRole('button', { name: 'Play vs LLM' }).click()

  await expect(page.locator('.status')).toContainText('human vs llm')
  await expect(page.locator('.opponent-info')).toContainText('LLM Opponent')
  await expect(page.locator('.opponent-info')).toContainText('Provider:')
  await expect(page.locator('.opponent-info')).toContainText('Model:')

  const moveResponsePromise = page.waitForResponse((response) => isMoveResponse(response, 'e2e4'))

  await page.locator('#deepsquare-board-square-e2').click()
  await page.locator('#deepsquare-board-square-e4').click()

  const moveResponse = await moveResponsePromise
  expect(moveResponse.status()).toBe(200)

  const responseJson = await moveResponse.json()
  const plies = responseJson.pgn
    .replace(/\d+\.\s*/g, '')
    .trim()
    .split(/\s+/)
    .filter(Boolean)

  expect(plies.length).toBeGreaterThanOrEqual(2)
  expect(responseJson.fen.split(' ')[1]).toBe('w')
  await expect(page.locator('.history-table tbody tr')).toHaveCount(1)
})
