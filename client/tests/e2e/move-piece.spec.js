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
  await expect(page.locator('.info-panel')).toContainText('Game ID:')
}

async function clickMove(page, fromSquare, toSquare, expectedMoveUci) {
  const moveResponsePromise = page.waitForResponse((response) =>
    isMoveResponse(response, expectedMoveUci),
  )

  await page.locator(`#deepsquare-board-square-${fromSquare}`).click()
  await page.locator(`#deepsquare-board-square-${toSquare}`).click()

  const moveResponse = await moveResponsePromise
  expect(moveResponse.status()).toBe(200)
  return moveResponse.json()
}

test('user can move a piece from e2 to e4 via board clicks', async ({ page }) => {
  await startFriendGame(page)

  const responseJson = await clickMove(page, 'e2', 'e4', 'e2e4')

  expect(responseJson.pgn).toContain('e4')
  await expect(page.locator('#deepsquare-board-piece-wP-e4')).toHaveCount(1)
  await expect(page.locator('#deepsquare-board-piece-wP-e2')).toHaveCount(0)
  await expect(page.locator('.history-table')).toContainText('e4')
})

test('illegal move by click is rejected and board remains unchanged', async ({ page }) => {
  await startFriendGame(page)

  const moveRequests = []
  const captureMoveRequest = (request) => {
    if (
      request.method() === 'POST' &&
      request.url().includes('/api/games/') &&
      request.url().includes('/move/')
    ) {
      moveRequests.push(request)
    }
  }

  page.on('request', captureMoveRequest)

  await page.locator('#deepsquare-board-square-e2').click()
  await page.locator('#deepsquare-board-square-e5').click()

  await page.waitForTimeout(400)
  page.off('request', captureMoveRequest)

  expect(moveRequests).toHaveLength(0)
  await expect(page.locator('.error-status')).toContainText('Illegal move')
  await expect(page.locator('#deepsquare-board-piece-wP-e2')).toHaveCount(1)
  await expect(page.locator('#deepsquare-board-piece-wP-e5')).toHaveCount(0)
  await expect(page.locator('.history-table tbody tr')).toHaveCount(0)
})

test('promotion opens chooser and sends promotion suffix', async ({ page }) => {
  await startFriendGame(page)

  await clickMove(page, 'h2', 'h4', 'h2h4')
  await clickMove(page, 'g7', 'g5', 'g7g5')
  await clickMove(page, 'h4', 'g5', 'h4g5')
  await clickMove(page, 'f7', 'f6', 'f7f6')
  await clickMove(page, 'g5', 'f6', 'g5f6')
  await clickMove(page, 'f8', 'g7', 'f8g7')
  await clickMove(page, 'f6', 'g7', 'f6g7')
  await clickMove(page, 'b7', 'b6', 'b7b6')

  const promotionResponsePromise = page.waitForResponse((response) =>
    isMoveResponse(response, 'g7h8q'),
  )

  await page.locator('#deepsquare-board-square-g7').click()
  await page.locator('#deepsquare-board-square-h8').click()

  await expect(page.locator('.promotion-modal')).toBeVisible()
  await page.locator('.promotion-button[data-promo="q"]').click()

  const promotionResponse = await promotionResponsePromise
  expect(promotionResponse.status()).toBe(200)

  const responseJson = await promotionResponse.json()
  expect(responseJson.pgn).toContain('=Q')

  await expect(page.locator('.promotion-modal')).toHaveCount(0)
  await expect(page.locator('#deepsquare-board-piece-wQ-h8')).toHaveCount(1)
})
