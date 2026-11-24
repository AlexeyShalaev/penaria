import {fileURLToPath} from 'node:url'

import react from '@vitejs/plugin-react'
import {defineConfig} from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  resolve: {alias: {'@': fileURLToPath(new URL('./src', import.meta.url))}},
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/system': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // The time zone the browser reports, so tests of the defaults do not depend on the machine.
    env: {TZ: 'Europe/Berlin'},
    coverage: {reporter: ['text', 'lcov']},
  },
})
