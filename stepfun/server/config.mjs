import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';

export const PORT = Number(process.env.PORT || 8787);
export const DB_NAME = 'kb';
export const MODEL_DIR = 'bge-small-zh-v1.5';
export const MODEL_LABEL = 'BAAI/bge-small-zh-v1.5（INT8/FP16 量化版）';
export const DIM = 512;

/**
 * seekdb 原生层不支持非 ASCII 路径（实测：中文目录直接 errno=2）。
 * 因此数据库目录按以下顺序解析，并在降级时打印原因。
 */
export function resolveDbDir() {
  if (process.env.SEEKDB_DIR) {
    return { dir: path.resolve(process.env.SEEKDB_DIR), reason: '来自 SEEKDB_DIR' };
  }
  const preferred = path.resolve('data/seekdb');
  if (!/[^\x00-\x7F]/.test(preferred)) {
    return { dir: preferred, reason: '项目内 data/seekdb' };
  }
  const drive = path.parse(process.cwd()).root;
  const fallback = path.join(drive, 'stepfun-kb-data', 'seekdb');
  return {
    dir: fallback,
    reason: '项目路径含中文，原生层无法打开，已降级到纯英文路径（可用 SEEKDB_DIR 覆盖）',
  };
}

export function ensureDir(dir) {
  // seekdb 只创建最后一级目录，父目录必须先存在
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

export const corpusDir = path.resolve('data/corpus');
export const evalFile = path.resolve('data/eval/queries.json');
export const evidenceDir = path.resolve('evidence');

export function tmpInfo() {
  return { platform: process.platform, arch: process.arch, cpus: os.cpus().length, node: process.version };
}
