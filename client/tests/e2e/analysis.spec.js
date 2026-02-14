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

async function startFriendGame(page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Play vs Friend' }).click()
  await expect(page.locator('.status')).toContainText('human vs human')
}

async function clickMove(page, fromSquare, toSquare, expectedMoveUci) {
  const moveResponsePromise = page.waitForResponse((response) =>
    isMoveResponse(response, expectedMoveUci),
  )

  await page.locator(`#deepsquare-board-square-${fromSquare}`).click()
  await page.locator(`#deepsquare-board-square-${toSquare}`).click()

  const moveResponse = await moveResponsePromise
  expect(moveResponse.status()).toBe(200)
}

async function playEightPlies(page) {
  await clickMove(page, 'e2', 'e4', 'e2e4')
  await clickMove(page, 'e7', 'e5', 'e7e5')
  await clickMove(page, 'g1', 'f3', 'g1f3')
  await clickMove(page, 'b8', 'c6', 'b8c6')
  await clickMove(page, 'f1', 'c4', 'f1c4')
  await clickMove(page, 'g8', 'f6', 'g8f6')
  await clickMove(page, 'd2', 'd3', 'd2d3')
  await clickMove(page, 'f8', 'c5', 'f8c5')
}

test('analyze game renders elo cards, key moves, turning points, and summary', async ({ page }) => {
  await startFriendGame(page)
  await playEightPlies(page)

  const payload = {
    game_id: 1,
    analysis_profile: 'balanced',
    analyzed_plies: 8,
    white: {
      estimated_elo: 1720,
      accuracy_percent: 81,
      avg_centipawn_loss: 54,
      move_counts: { best: 2, good: 2, inaccuracy: 0, mistake: 0, blunder: 0 },
    },
    black: {
      estimated_elo: 1640,
      accuracy_percent: 76,
      avg_centipawn_loss: 68,
      move_counts: { best: 1, good: 3, inaccuracy: 0, mistake: 0, blunder: 0 },
    },
    key_moves: [
      {
        ply: 6,
        side: 'black',
        san: 'Nf6',
        uci: 'g8f6',
        category: 'best',
        cp_loss: 12,
        eval_before_cp: 20,
        eval_after_cp: 8,
        commentary: 'High-quality move.',
      },
    ],
    turning_points: [
      {
        ply: 7,
        side: 'white',
        san: 'd3',
        swing_cp: 110,
        commentary: 'Largest swing in the game.',
      },
    ],
    summary: 'Detailed narrative summary for this game.',
    reliability: { sufficient_sample: true, note: 'Performance Elo estimate for this game only.' },
  }

  await page.route('**/api/games/*/analysis/', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    })
  })

  await page.getByRole('button', { name: 'Analyze Game' }).click()

  await expect(page.locator('.analysis-panel')).toContainText('Your Performance Elo')
  await expect(page.locator('.analysis-panel')).toContainText('Opponent Performance Elo')
  await expect(page.locator('.analysis-panel')).toContainText('Nf6')
  await expect(page.locator('.analysis-panel')).toContainText('Turning Points')
  await expect(page.locator('.analysis-panel')).toContainText('Game Summary')
  await expect(page.locator('.analysis-summary')).toContainText('Detailed narrative summary')
})

test('analysis request failure shows error banner', async ({ page }) => {
  await startFriendGame(page)
  await playEightPlies(page)

  await page.route('**/api/games/*/analysis/', async (route) => {
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({
        error: 'Analysis engine unavailable',
        code: 'analysis_unavailable',
      }),
    })
  })

  await page.getByRole('button', { name: 'Analyze Game' }).click()
  await expect(page.locator('.analysis-error')).toContainText('Analysis engine unavailable')
})
