/**
 * 推理全部放在 Web Worker 里：模型加载与 ONNX 编译会长时间占用线程，
 * 放在主线程会让页面假死（进度条不刷新、按钮点不动）。
 */
export const MODEL_ID = 'bge-small-zh-v1.5';
export const DIM = 512;
export const QUERY_PREFIX = '为这个句子生成表示以用于检索相关文章：';

export type Device = 'webgpu' | 'wasm';
export type Dtype = 'fp32' | 'fp16' | 'int8';
export type PreferMode = 'auto' | 'wasm-int8' | 'wasm-fp32' | 'webgpu-fp16';

export interface BackendInfo {
  device: Device;
  dtype: Dtype;
  label: string;
  adapter: string;
  reason: string;
  loadMs: number;
  warmMs: number;
}

export interface EmbedProgress {
  done: number;
  total: number;
  elapsedMs: number;
}

let worker: Worker | null = null;
let current: BackendInfo | null = null;
let seq = 0;
const pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();
let onLogRef: ((msg: string, isErr?: boolean) => void) | null = null;

export const backend = () => current;

function ensureWorker() {
  if (worker) return worker;
  worker = new Worker(new URL('./embed-worker.ts', import.meta.url), { type: 'module' });
  worker.onmessage = (ev: MessageEvent) => {
    const m = ev.data || {};
    if (m.type === 'log') {
      onLogRef?.(m.text);
      return;
    }
    const task = pending.get(m.id ?? -1);
    if (m.type === 'error') {
      if (task) {
        pending.delete(m.id);
        task.reject(new Error(m.message));
      } else {
        onLogRef?.(m.message, true);
      }
      return;
    }
    if (!task) return;
    if (m.type === 'progress') return; // 进度由 embed 的 onProgress 单独处理
    pending.delete(m.id);
    if (m.type === 'loaded') task.resolve(m.info);
    else if (m.type === 'embedded') task.resolve({ vectors: m.vectors, elapsedMs: m.elapsedMs });
    else if (m.type === 'progress-embedded') task.resolve(m);
  };
  worker.onerror = (e) => {
    onLogRef?.('Worker 错误：' + (e.message || '未知'), true);
  };
  return worker;
}

function call<T>(payload: Record<string, unknown>, onProgress?: (p: EmbedProgress) => void): Promise<T> {
  const w = ensureWorker();
  const id = ++seq;
  return new Promise<T>((resolve, reject) => {
    pending.set(id, { resolve: resolve as (v: unknown) => void, reject });
    if (onProgress) {
      const handler = (ev: MessageEvent) => {
        const m = ev.data || {};
        if (m.type === 'progress' && m.id === id) {
          onProgress({ done: m.done, total: m.total, elapsedMs: m.elapsedMs });
        }
        if ((m.type === 'embedded' || m.type === 'error') && m.id === id) {
          w.removeEventListener('message', handler);
        }
      };
      w.addEventListener('message', handler);
    }
    w.postMessage({ ...payload, id });
  });
}

export async function loadModel(mode: PreferMode = 'auto', onLog?: (m: string, e?: boolean) => void): Promise<BackendInfo> {
  onLogRef = onLog || null;
  if (current) return current;
  try {
    const info = await call<BackendInfo>({ type: 'load', mode });
    current = info;
    return info;
  } catch (e) {
    if (mode === 'auto') {
      onLog?.('WebGPU 路径失败，回退 WASM + INT8：' + (e as Error).message, true);
      const info = await call<BackendInfo>({ type: 'load', mode: 'wasm-int8' });
      current = info;
      return info;
    }
    throw e;
  }
}

export async function embed(
  texts: string[],
  opts: { isQuery?: boolean; batchSize?: number; onProgress?: (p: EmbedProgress) => void } = {}
): Promise<number[][]> {
  const { isQuery = false, batchSize = 8, onProgress } = opts;
  const r = await call<{ vectors: number[][] }>({ type: 'embed', texts, isQuery, batchSize }, onProgress);
  return r.vectors;
}

export async function detectWebGPU(): Promise<{ ok: boolean; adapter: string; reason: string }> {
  const nav = navigator as Navigator & { gpu?: GPU };
  if (!nav.gpu) return { ok: false, adapter: 'n/a', reason: '浏览器未暴露 navigator.gpu' };
  try {
    const adapter = await nav.gpu.requestAdapter();
    if (!adapter) return { ok: false, adapter: 'n/a', reason: 'requestAdapter() 返回空' };
    const info = (adapter as any).info;
    const desc = [info?.vendor, info?.architecture, info?.description].filter(Boolean).join(' / ') || 'WebGPU 适配器';
    return { ok: true, adapter: desc, reason: 'navigator.gpu 可用' };
  } catch (e) {
    return { ok: false, adapter: 'n/a', reason: '请求适配器失败：' + (e as Error).message };
  }
}

export const isReady = () => !!current;
