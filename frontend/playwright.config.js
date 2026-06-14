import { defineConfig, devices } from '@playwright/test';

// La porta del dev server è configurabile (default 5173). Utile quando 5173
// è già occupata da un altro processo: E2E_PORT=5180 npm run e2e
const PORT = process.env.E2E_PORT || '5173';
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  retries: 1,
  reporter: 'html',

  use: {
    baseURL: BASE_URL,
    headless: true,
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],

  /* Avvia backend (API) e Vite prima dei test.
     Il backend usa un DB SQLite dedicato e ricreato a ogni run. */
  webServer: [
    {
      // Il venv è WSL-based: avvia uvicorn dentro WSL anche se node gira su Windows
      command: 'wsl -e bash -c "cd .. && rm -f e2e_test.db && '
             + 'source .venv/bin/activate && '
             + 'DATABASE_URL=sqlite:///./e2e_test.db '
             + 'SECRET_KEY=e2e-test-secret-key-32-chars-long! '
             + 'uvicorn backend.app.main:app --host 127.0.0.1 --port 8000"',
      url:     'http://127.0.0.1:8000/health',
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --port ${PORT} --strictPort`,
      url:     BASE_URL,
      reuseExistingServer: true,
      timeout: 30_000,
    },
  ],
});
