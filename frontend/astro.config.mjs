// @ts-check
import { defineConfig } from 'astro/config';

import tailwindcss from '@tailwindcss/vite';

import node from '@astrojs/node';

// https://astro.build/config
export default defineConfig({
  output: 'server',
  // Prefetch every internal link on hover/focus so the next page is usually
  // ready by the time it's clicked (pages send "private, no-cache", which lets
  // the browser reuse a prefetched page; "no-store" would discard it).
  prefetch: {
    prefetchAll: true,
    defaultStrategy: 'hover',
  },

  security: {
    checkOrigin: false,
  },

  server: {
    port: 7330,
  },

  vite: {
    plugins: [tailwindcss()],
    server: {
      allowedHosts: ['abstract-dev.bellamylab.com', 'scrob-dev.bellamylab.com'],
    }
  },

  adapter: node({
    mode: 'standalone'
  })
});
