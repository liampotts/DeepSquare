import process from 'node:process'
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL: 'http://127.0.0.1:5173',
    headless: true,
    trace: 'on-first-retry',
  },
  webServer: [
    {
      command:
        '../venv/bin/python manage.py migrate --noinput && ../venv/bin/python manage.py runserver 127.0.0.1:8001 --noreload',
      cwd: '../server',
      url: 'http://127.0.0.1:8001/api/games/',
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        LLM_FEATURE_ENABLED: 'true',
        OPENAI_API_KEY: 'test-openai-key',
        ANTHROPIC_API_KEY: 'test-anthropic-key',
        GEMINI_API_KEY: 'test-gemini-key',
        LLM_MOVE_TIMEOUT_SECONDS: '1',
      },
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5173',
      cwd: '.',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
})
