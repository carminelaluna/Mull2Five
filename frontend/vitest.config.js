import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.js'],
    include:  ['tests/**/*.test.js'],   // solo unit tests, esclude e2e/
    exclude:  ['e2e/**', 'node_modules/**'],
    coverage: {
      provider: 'v8',
      include: ['js/**/*.js'],
    },
  },
});
