/// <reference lib="webworker" />
import { pipeline, env } from '@huggingface/transformers';

env.allowRemoteModels = false;
env.allowLocalModels = true;
env.localModelPath = '/models/';
env.useBrowserCache = true;

const MODEL_ID = 'bge-small-zh-v1.5';
const PREFIX = '为这个句子生成表示以用于检索相关文章：';

let extractor: any = null;
let ready = false;
const lastLogged = new Map<string, number>();

async function detectWebGPU(): Promise<{ ok: boolean; adapter: string; reason: string }> {
  const nav = self.navigator as Navigator & { gpu?: GPU };
  if (!nav.gpu) return { ok: false, adapter: 'n/a', reason: '浏览器未暴露 navigator.gpu（非 Chrome/Edge 或未开启 WebGPU）' };
  try {
    const adapter = await nav.gpu.requestAdapter();
    if (!adapter) return { ok: false, adapter: 'n/a', reason: 'requestAdapter() 返回空（显卡或驱动不支持）' };
    const info = (adapter as any).info;
    const desc = [info?.vendor, info?.architecture, info?.description].filter(Boolean).join(' / ') || 'WebGPU 适配器';
    return { ok: true, adapter: desc, reason: 'navigator.gpu 可用' };
  } catch (e) {
    return { ok: false, adapter: 'n/a', reason: '请求适配器失败：' + (e as Error).message };
  }
}

self.onmessage = async (ev: MessageEvent) => {
  const msg = ev.data || {};
  const id = msg.id;
  try {
    if (msg.type === 'load') {
      const gpu = await detectWebGPU();
      let device: 'webgpu' | 'wasm';
      let dtype: 'fp32' | 'fp16' | 'int8';
      let reason: string;
      const mode = msg.mode || 'auto';

      if (mode === 'webgpu-fp16') {
        device = 'webgpu'; dtype = 'fp16';
        reason = gpu.ok ? '手动指定 WebGPU' : '手动指定 WebGPU，但检测显示不可用：' + gpu.reason;
      } else if (mode === 'wasm-int8') {
        device = 'wasm'; dtype = 'int8'; reason = '手动指定 WASM（验证降级路径）';
      } else if (mode === 'wasm-fp32') {
        device = 'wasm'; dtype = 'fp32'; reason = '手动指定 FP32 基线（质量对比）';
      } else if (gpu.ok) {
        device = 'webgpu'; dtype = 'fp16'; reason = '自动：检测到 WebGPU，使用 FP16 权重';
      } else {
        device = 'wasm'; dtype = 'int8'; reason = '自动降级：' + gpu.reason + '，改用 WASM + INT8';
      }

      // 运行时文件由后端静态托管（/ort/），用运行期拼出的绝对地址，
      // 避免 Vite 把 onnxruntime 的动态 import 当成源码去转译
      const ortBase = self.location.origin + '/ort/';
      env.backends.onnx.wasm.wasmPaths = ortBase;

      self.postMessage({ id, type: 'log', text: `推理后端：${device.toUpperCase()} / ${dtype.toUpperCase()}（${reason}）` });
      const t0 = performance.now();
      extractor = await pipeline('feature-extraction', MODEL_ID, {
        device,
        dtype,
        progress_callback: (p: any) => {
          if (p?.status === 'progress' && p.file) {
            const pct = Math.round(p.progress || 0);
            // 只按 10% 粒度报，避免刷屏
            if (pct >= (lastLogged.get(p.file) ?? -10) + 10 || pct === 100) {
              lastLogged.set(p.file, pct);
              self.postMessage({ id, type: 'log', text: `加载 ${p.file.replace(/^.*\//, '')} ${pct}%` });
            }
          }
        },
      });
      const loadMs = Math.round(performance.now() - t0);

      const t1 = performance.now();
      await extractor(['预热'], { pooling: 'cls', normalize: true });
      const warmMs = Math.round(performance.now() - t1);

      ready = true;
      self.postMessage({
        id,
        type: 'loaded',
        info: {
          device,
          dtype,
          label: `${device === 'webgpu' ? 'WebGPU' : 'WASM'} · ${dtype.toUpperCase()}`,
          adapter: gpu.adapter,
          reason,
          loadMs,
          warmMs,
        },
      });
      return;
    }

    if (msg.type === 'embed') {
      if (!ready || !extractor) throw new Error('模型尚未加载');
      const { texts, isQuery, batchSize = 8 } = msg;
      const input = isQuery ? texts.map((t: string) => PREFIX + t) : texts;
      const out: number[][] = [];
      const t0 = performance.now();
      for (let i = 0; i < input.length; i += batchSize) {
        const res = await extractor(input.slice(i, i + batchSize), { pooling: 'cls', normalize: true });
        for (const v of res.tolist()) out.push(v);
        self.postMessage({
          id,
          type: 'progress',
          done: out.length,
          total: input.length,
          elapsedMs: Math.round(performance.now() - t0),
        });
      }
      self.postMessage({ id, type: 'embedded', vectors: out, elapsedMs: Math.round(performance.now() - t0) });
    }
  } catch (e) {
    self.postMessage({ id, type: 'error', message: (e as Error).message || String(e) });
  }
};
