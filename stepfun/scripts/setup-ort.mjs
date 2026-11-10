/**
 * npm install 后自动执行：把 onnxruntime-web 的 wasm 运行时复制到 src/ort/。
 * 目的有两个：
 *   1. 推理完全本地化，判题机断网也能跑（不走 jsdelivr CDN）；
 *   2. onnxruntime-web 的 package.json exports 不暴露 ./dist/*，
 *      放进 src/ 才能用 `?url` 让 Vite 正确产出文件地址。
 */
import fs from 'node:fs';
import path from 'node:path';

const src = path.resolve('node_modules/onnxruntime-web/dist');
const dst = path.resolve('src/ort');

if (!fs.existsSync(src)) {
  console.log('[setup-ort] 未找到 onnxruntime-web，跳过');
  process.exit(0);
}

fs.mkdirSync(dst, { recursive: true });
const wanted = /^ort-wasm.*\.(wasm|mjs)$/;
let n = 0;
for (const f of fs.readdirSync(src)) {
  if (!wanted.test(f)) continue;
  const from = path.join(src, f);
  const to = path.join(dst, f);
  const size = fs.statSync(from).size;
  if (fs.existsSync(to) && fs.statSync(to).size === size) continue;
  fs.copyFileSync(from, to);
  n++;
}
console.log(`[setup-ort] 已同步 ${n} 个 onnxruntime 运行时文件到 src/ort/`);
