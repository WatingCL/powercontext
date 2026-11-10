import { defineConfig } from 'vite';

/**
 * 刻意不开 COOP/COEP：
 * 开了之后页面进入 cross-origin isolated，虽然能让 WASM 用多线程，
 * 但 Vite 的 worker 脚本会被 COEP 拦掉（ERR_BLOCKED_BY_RESPONSE）。
 * 这里优先稳定性，WASM 走单线程；主路径是 WebGPU，不受影响。
 */
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8787',
      // onnxruntime 的 wasm/mjs 由 API 进程原样托管，绕开 Vite 的模块转译
      '/ort': 'http://127.0.0.1:8787',
    },
  },
  optimizeDeps: {
    exclude: ['@huggingface/transformers'],
  },
  build: {
    target: 'esnext',
    chunkSizeWarningLimit: 4000,
  },
  worker: { format: 'es' },
});
