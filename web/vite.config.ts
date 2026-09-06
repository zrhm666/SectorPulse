import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  build: {
    // Preserve the previous Vite 5 syntax targets across the toolchain upgrade.
    target: ['es2020', 'edge88', 'firefox78', 'chrome87', 'safari14'],
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/testSetup.ts'],
    globals: true,
    exclude: ['**/node_modules/**', '**/e2e/**', '**/tooling/**'],
  },
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': 'http://127.0.0.1:9000',
    },
  },
  preview: {
    host: '127.0.0.1',
  },
})
