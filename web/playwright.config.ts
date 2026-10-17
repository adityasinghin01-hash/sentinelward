import {defineConfig} from '@playwright/test';

// Screens are checked against an already running Vite dev server (SW_WEB_URL) whose /api and /ws
// proxy to the backend (SW_API_TARGET, e.g. the SSH tunnel). Nothing here starts or changes the backend.
export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  workers: 1,
  reporter: [['list']],
  use: {baseURL: process.env.SW_WEB_URL || 'http://127.0.0.1:5180', colorScheme: 'dark',
        // Use the installed Google Chrome so no browser download is needed.
        channel: process.env.SW_PW_CHANNEL || 'chrome'},
});
