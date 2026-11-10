/**
 * 清空数据库目录（重建知识库时用）。会删除所有集合与向量。
 * 用法：npm run reset
 */
import fs from 'node:fs';
import path from 'node:path';

const ascii = (p) => !/[^\x00-\x7F]/.test(p);
const preferred = path.resolve('data/seekdb');
const dir = process.env.SEEKDB_DIR
  ? path.resolve(process.env.SEEKDB_DIR)
  : ascii(preferred)
    ? preferred
    : path.join(path.parse(process.cwd()).root, 'stepfun-kb-data', 'seekdb');

if (!fs.existsSync(dir)) {
  console.log('数据库目录不存在，无需清理：' + dir);
  process.exit(0);
}

const size = Number(
  fs.readdirSync(dir).reduce((n, f) => {
    try {
      return n + fs.statSync(path.join(dir, f)).size;
    } catch {
      return n;
    }
  }, 0) / 1048576
).toFixed(1);

fs.rmSync(dir, { recursive: true, force: true });
console.log(`已删除数据库目录 ${dir}（约 ${size}MB）`);
console.log('下次启动 node server/index.mjs 会自动重新初始化。');
