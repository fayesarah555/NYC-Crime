/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // Split the four heavy vendors so no single chunk carries the app.
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('@astryxdesign/theme')) return 'astryx-theme'
          if (id.includes('@astryxdesign') || id.includes('@stylexjs')) return 'astryx'
          if (id.includes('leaflet')) return 'leaflet'
          if (id.includes('recharts') || id.includes('d3-') || id.includes('victory') || id.includes('react-smooth')) return 'recharts'
          if (id.includes('react') || id.includes('scheduler')) return 'react'
          return 'vendor'
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    exclude: ['node_modules/**', 'dist/**', 'e2e/**'],
    coverage: {
      provider: 'v8',
      include: ['src/lib/**/*.ts'],
      exclude: ['src/lib/**/*.test.ts'],
      thresholds: {
        lines: 85,
        functions: 85,
        statements: 85,
        branches: 75,
      },
    },
  },
})
