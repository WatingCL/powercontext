/**
 * 下载 bge-small-zh-v1.5 的 ONNX 权重到 public/models/。
 * 三档精度：fp32（基线）/ fp16 / int8，都放在同一个模型目录，前端按 dtype 选择。
 *
 * 用法：
 *   npm run setup:model                # 默认走 hf-mirror
 *   npm run setup:model -- --endpoint https://huggingface.co
 */
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const MODEL_ID = 'Xenova/bge-small-zh-v1.5';
const OUT_DIR = path.resolve('public/models/bge-small-zh-v1.5');

const FILES = [
  ['config.json', 'config.json'],
  ['tokenizer.json', 'tokenizer.json'],
  ['tokenizer_config.json', 'tokenizer_config.json'],
  ['special_tokens_map.json', 'special_tokens_map.json'],
  ['vocab.txt', 'vocab.txt'],
  ['onnx/model.onnx', 'onnx/model.onnx'],
  ['onnx/model_fp16.onnx', 'onnx/model_fp16.onnx'],
  ['onnx/model_int8.onnx', 'onnx/model_int8.onnx'],
];

const argEndpoint = (() => {
  const i = process.argv.indexOf('--endpoint');
  return i > -1 ? process.argv[i + 1] : null;
})();

const endpoints = {
  cn: 'https://hf-mirror.com',
  intl: 'https://huggingface.co',
};

const candidates = argEndpoint
  ? [argEndpoint, ...Object.values(endpoints)]
  : [endpoints.cn, endpoints.intl];

async function download(url, dest) {
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  const tmp = `${dest}.part`;
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 120000);
    const res = await fetch(url, { redirect: 'follow', signal: ctrl.signal });
    clearTimeout(timer);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    fs.writeFileSync(tmp, Buffer.from(await res.arrayBuffer()));
    fs.renameSync(tmp, dest);
    return;
  } catch (e) {
    // Node 的 fetch 不走系统代理，失败时退回 curl（Windows/macOS/Linux 均自带）
    const r = spawnSync('curl', ['-fsSL', '--max-time', '600', '-o', tmp, url], {
      stdio: 'ignore',
    });
    if (r.status !== 0) {
      fs.rmSync(tmp, { force: true });
      throw new Error(`fetch 与 curl 均失败：${e.message}`);
    }
    fs.renameSync(tmp, dest);
  }
}

const MB = (n) => (n / 1048576).toFixed(1) + 'MB';

let base = null;
for (const ep of candidates) {
  try {
    process.stdout.write(`探测下载源 ${ep} ... `);
    const res = await fetch(`${ep}/api/models/${MODEL_ID}`, { redirect: 'follow' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    base = ep;
    console.log('可用');
    break;
  } catch {
    console.log('不可用');
  }
}
if (!base) {
  console.error('所有下载源均不可用，请检查网络或手动放置模型文件到 public/models/bge-small-zh-v1.5/');
  process.exit(1);
}

let total = 0;
for (const [remote, local] of FILES) {
  const dest = path.join(OUT_DIR, local);
  const url = `${base}/${MODEL_ID}/resolve/main/${remote}`;
  if (fs.existsSync(dest) && fs.statSync(dest).size > 1024) {
    const s = fs.statSync(dest).size;
    total += s;
    console.log(`跳过 ${local} (${MB(s)})`);
    continue;
  }
  process.stdout.write(`下载 ${remote} ... `);
  try {
    await download(url, dest);
    const s = fs.statSync(dest).size;
    total += s;
    console.log(MB(s));
  } catch (e) {
    console.log(`失败：${e.message}`);
    process.exitCode = 1;
  }
}

const onnxDir = path.join(OUT_DIR, 'onnx');
if (fs.existsSync(onnxDir)) {
  console.log('\n模型体积：');
  let sum = 0;
  for (const f of fs.readdirSync(onnxDir).sort()) {
    const s = fs.statSync(path.join(onnxDir, f)).size;
    sum += s;
    console.log(`  ${f.padEnd(20)} ${MB(s)}`);
  }
  const fp32 = fs.statSync(path.join(onnxDir, 'model.onnx')).size;
  const int8 = fs.statSync(path.join(onnxDir, 'model_int8.onnx')).size;
  const fp16 = fs.statSync(path.join(onnxDir, 'model_fp16.onnx')).size;
  console.log(`  合计 ${MB(sum)}`);
  console.log(`  压缩比 fp32/int8 = ${(fp32 / int8).toFixed(2)}x，fp32/fp16 = ${(fp32 / fp16).toFixed(2)}x`);
}
console.log('\n完成，模型目录：' + OUT_DIR);
