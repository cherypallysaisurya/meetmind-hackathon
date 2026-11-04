import { defineConfig } from "electron-vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

// Three bundles, one per Electron context. Output goes to out/main, out/preload, out/renderer.
export default defineConfig({
  main: { build: { lib: { entry: resolve("src/main/index.ts") } } },
  preload: { build: { lib: { entry: resolve("src/preload/index.ts") } } },
  renderer: {
    root: resolve("src/renderer"),
    // assetsInlineLimit 0: the AudioWorklet file must stay a real file, not a data URL.
    build: { rollupOptions: { input: resolve("src/renderer/index.html") }, assetsInlineLimit: 0 },
    plugins: [react()],
  },
});
