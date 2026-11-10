/**
 * 无头浏览器端到端自检：真实加载模型 → 导入示例语料 → 检索 → 截图。
 * 用于生成 evidence 里的截图与浏览器侧时延，不参与应用运行。
 * 用法：node scripts/browser-check.mjs
 */
import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
import path from 'node:path';

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const URL = process.env.APP_URL || 'http://127.0.0.1:5173';
const OUT = path.resolve('evidence');
fs.mkdirSync(OUT, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--enable-unsafe-webgpu'],
  defaultViewport: { width: 1440, height: 1100 },
  protocolTimeout: 600000,
});
const page = await browser.newPage();
page.on('console', (m) => {
  const t = m.text();
  if (!t.includes('[vite]')) console.log(`[console:${m.type()}] ${t.slice(0, 220)}`);
});
page.on('requestfailed', (r) => console.log('[requestfailed]', r.url().slice(0, 120), r.failure()?.errorText));
page.on('response', (r) => { if (r.status() >= 400) console.log('[http' + r.status() + ']', r.url().slice(0, 140)); });
page.on('pageerror', (e) => console.log('[pageerror]', e.message.slice(0, 300)));

const t0 = Date.now();
await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
console.log('页面已打开，等待模型加载…');

await page.waitForFunction(
  () => {
    const t = document.querySelector('#badge-backend')?.textContent || '';
    return t.includes('·');
  },
  { timeout: 300000, polling: 1000 }
);
const badge = await page.$eval('#badge-backend', (el) => el.textContent.trim());
const badgeTip = await page.$eval('#badge-backend', (el) => el.getAttribute('title'));
console.log(`后端徽标：${badge}`);
console.log(`选择理由：${badgeTip}`);
console.log(`模型就绪耗时：${((Date.now() - t0) / 1000).toFixed(1)}s`);

// 导入示例语料
await page.click('#btn-sample');
console.log('开始导入示例语料…');
await page.waitForFunction(
  () => (document.querySelector('#log')?.textContent || '').includes('写入完成'),
  { timeout: 600000, polling: 1000 }
);
const importLog = await page.evaluate(() =>
  [...document.querySelectorAll('#log div')].map((d) => d.textContent).join('\n')
);
console.log('--- 导入日志 ---\n' + importLog);
const stats = await page.$eval('#stat-count', (el) => el.textContent);
console.log('统计：', stats);

await page.screenshot({ path: path.join(OUT, 'shot-1-imported.png') });

// 检索
await page.click('#q');
await page.type('#q', '冰箱启动的功率增量大概是多少');
await page.click('#btn-search');
await page.waitForFunction(() => document.querySelectorAll('.hit').length > 0, {
  timeout: 120000,
  polling: 500,
});
const timings = await page.$eval('#timings', (el) => el.textContent.replace(/\s+/g, ' ').trim());
const firstHit = await page.$eval('.hit .title', (el) => el.textContent);
console.log('检索时延：', timings);
console.log('首条结果：', firstHit);
await page.screenshot({ path: path.join(OUT, 'shot-2-search.png') });

// 基准测试
await page.click('#btn-bench');
await page.waitForFunction(
  () => (document.querySelector('#log')?.textContent || '').includes('基准完成'),
  { timeout: 300000, polling: 1000 }
);
const benchLine = await page.evaluate(() => {
  const lines = [...document.querySelectorAll('#log div')].map((d) => d.textContent);
  return lines.filter((l) => l.includes('基准完成')).pop();
});
console.log(benchLine);
await page.screenshot({ path: path.join(OUT, 'shot-3-bench.png') });

fs.writeFileSync(
  path.join(OUT, 'browser-check.json'),
  JSON.stringify(
    {
      at: new Date().toISOString(),
      backend: badge,
      reason: badgeTip,
      userAgent: await page.evaluate(() => navigator.userAgent),
      importLog,
      stats,
      searchTimings: timings,
      firstHit,
      bench: benchLine,
    },
    null,
    2
  )
);
console.log('截图与结果已写入 evidence/');
await browser.close();
