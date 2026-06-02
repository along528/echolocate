import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Standalone sonar frontend. VITE_VECTOR_API_URL points at the vector service
// (baked in at build time, same convention as the legacy frontend).
export default defineConfig({
  base: '/',
  plugins: [react()],
  server: { port: 5180 },
});
