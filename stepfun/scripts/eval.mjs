/**
 * 质量评测：同一套语料与查询，分别用 FP32 基线和 INT8（以及 FP16）权重
 * 生成向量 → 写入 seekdb → 混合检索 → 计算 Recall@K / nDCG@10 / MRR。
 *
 * 额外报告「向量保真度」：同一批文本在量化前后向量的平均余弦相似度，
 * 用来解释质量变化到底来自哪里。
 *
 * 用法：先 node server/index.mjs，再 node scripts/eval.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { pipeline, env } from '@huggingface/transformers';

env.allowRemoteModels = false;
env.allowLocalModels = true;
env.localModelPath = path.resolve('public/models') + path.sep;

const MODEL = 'bge-small-zh-v1.5';
const DIM = 512;
const PREFIX = '为这个句子生成表示以用于检索相关文章：';
const API = 'http://127.0.0.1:8787';
const CORPUS = path.resolve('data/corpus');
const EVAL = path.resolve('data/eval/queries.json');
const OUT = path.resolve('evidence');

const MAX_CHARS = 320;
const OVERLAP = 60;

function hash(str) {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16).padStart(8, '0');
}

function clean(text) {
  return text
    .replace(/\r\n/g, '\n')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/[*_`>]/g, '')
    .replace(/[ \t]+/g, ' ')
    .trim();
}

function chunkDoc(fileName, raw) {
  const text = clean(raw);
  const heading = raw.match(/^#\s+(.+)$/m);
  const title = heading ? heading[1].trim() : fileName.replace(/\.md$/, '');
  const sentences = text.split(/(?<=[。！？；\n])/).filter((s) => s.trim());
  const chunks = [];
  let buf = '';
  const push = () => {
    const body = buf.trim();
    if (body.length < 12) { buf = ''; return; }
    chunks.push({ id: `${hash(fileName)}-${chunks.length}-${hash(body.slice(0, 80))}`, seq: chunks.length, text: body });
    buf = body.slice(Math.max(0, body.length - OVERLAP));
  };
  for (const s of sentences) {
    if (buf.length + s.length > MAX_CHARS && buf) push();
    buf += s;
    while (buf.length > MAX_CHARS * 2) { buf = buf.slice(0, MAX_CHARS); push(); }
  }
  if (buf.trim().length >= 12) {
    chunks.push({ id: `${hash(fileName)}-${chunks.length}-${hash(buf.trim().slice(0, 80))}`, seq: chunks.length, text: buf.trim() });
  }
  return { docId: fileName, title, chunks };
}

const post = (p, body) =>
  fetch(API + p, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })
    .then(async (r) => {
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
      return d;
    });

async function embedAll(pipe, texts, batch = 8, isQuery = false) {
  const out = [];
  const input = isQuery ? texts.map((t) => PREFIX + t) : texts;
  for (let i = 0; i < input.length; i += batch) {
    const res = await pipe(input.slice(i, i + batch), { pooling: 'cls', normalize: true });
    for (const v of res.tolist()) out.push(v);
  }
  return out;
}

const cosine = (a, b) => {
  let s = 0;
  for (let i = 0; i < a.length; i++) s += a[i] * b[i];
  return s;
};

function metrics(hits, gold, k) {
  const ids = hits.map((h) => h.docId);
  const uniq = [];
  for (const id of ids) if (!uniq.includes(id)) uniq.push(id);
  const hitSet = uniq.slice(0, k).filter((id) => gold.includes(id));
  const recall = hitSet.length / gold.length;
  let dcg = 0;
  uniq.slice(0, 10).forEach((id, i) => {
    if (gold.includes(id)) dcg += 1 / Math.log2(i + 2);
  });
  let idcg = 0;
  for (let i = 0; i < Math.min(gold.length, 10); i++) idcg += 1 / Math.log2(i + 2);
  const ndcg = idcg ? dcg / idcg : 0;
  let mrr = 0;
  const first = uniq.findIndex((id) => gold.includes(id));
  if (first >= 0) mrr = 1 / (first + 1);
  return { recall, ndcg, mrr };
}

async function runConfig(dtype) {
  console.log(`\n=== ${dtype.toUpperCase()} ===`);
  const t0 = Date.now();
  const pipe = await pipeline('feature-extraction', MODEL, { device: 'cpu', dtype });
  const loadMs = Date.now() - t0;
  await pipe(['预热'], { pooling: 'cls', normalize: true });
  console.log(`模型加载 ${loadMs}ms`);

  const files = fs.readdirSync(CORPUS).filter((f) => /\.(md|txt)$/i.test(f)).sort();
  const docs = files.map((f) => chunkDoc(f, fs.readFileSync(path.join(CORPUS, f), 'utf8')));
  const flat = docs.flatMap((d) => d.chunks.map((c) => ({ docId: d.docId, ...c })));
  console.log(`语料：${docs.length} 篇 / ${flat.length} 块`);

  const t1 = Date.now();
  const docVecs = await embedAll(pipe, flat.map((c) => c.text), 8);
  const embedMs = Date.now() - t1;
  console.log(`文档向量化 ${(embedMs / 1000).toFixed(2)}s，吞吐 ${(flat.length / (embedMs / 1000)).toFixed(1)} 块/秒`);

  const colName = `eval-${dtype}`;
  await post('/api/collections', { name: colName, label: `评测 ${dtype}` }).catch(() => {});
  const byDoc = new Map();
  flat.forEach((c, i) => {
    if (!byDoc.has(c.docId)) byDoc.set(c.docId, []);
    byDoc.get(c.docId).push({ id: c.id, seq: c.seq, text: c.text, vector: docVecs[i] });
  });
  const t2 = Date.now();
  const addRes = await post('/api/documents', {
    collection: colName,
    documents: [...byDoc.entries()].map(([docId, chunks]) => ({ docId, title: docId, chunks })),
  });
  console.log(`写入+刷新 ${Date.now() - t2}ms，库内 ${addRes.total} 块`);

  const { queries } = JSON.parse(fs.readFileSync(EVAL, 'utf8'));
  const qVecs = await embedAll(pipe, queries.map((q) => q.query), 8, true);
  const perHy = [];
  const perVec = [];
  const dbTimes = [];
  for (let i = 0; i < queries.length; i++) {
    const base = { collection: colName, query: queries[i].query, vector: qVecs[i], topK: 10, kwBoost: 1, vecBoost: 1 };
    const rh = await post('/api/search', base);
    dbTimes.push(rh.dbMs);
    const mh = metrics(rh.hits, queries[i].gold, 5);
    perHy.push({ id: queries[i].id, top1: rh.hits[0]?.docId, top5: rh.hits.slice(0, 5).map((h) => h.docId), ...mh });
    const rv = await post('/api/search', { ...base, vectorOnly: true });
    const mv = metrics(rv.hits, queries[i].gold, 5);
    perVec.push({ id: queries[i].id, top1: rv.hits[0]?.docId, ...mv });
  }
  const avg = (arr) => arr.reduce((a, b) => a + b, 0) / (arr.length || 1);
  const pack = (per) => ({
    recallAt5: Number(avg(per.map((p) => p.recall)).toFixed(4)),
    ndcgAt10: Number(avg(per.map((p) => p.ndcg)).toFixed(4)),
    mrr: Number(avg(per.map((p) => p.mrr)).toFixed(4)),
  });
  const summary = {
    dtype,
    model: MODEL,
    loadMs,
    embedMs,
    chunks: flat.length,
    docs: docs.length,
    throughput: Number((flat.length / (embedMs / 1000)).toFixed(2)),
    hybrid: pack(perHy),
    vectorOnly: pack(perVec),
    dbMedianMs: [...dbTimes].sort((a, b) => a - b)[Math.floor(dbTimes.length / 2)],
    detail: perHy,
  };
  console.log(
    `混合 Recall@5 ${summary.hybrid.recallAt5} nDCG@10 ${summary.hybrid.ndcgAt10} MRR ${summary.hybrid.mrr}`
  );
  console.log(
    `纯向量 Recall@5 ${summary.vectorOnly.recallAt5} nDCG@10 ${summary.vectorOnly.ndcgAt10} MRR ${summary.vectorOnly.mrr}`
  );
  return { summary, docVecs, flat };
}

const t0 = Date.now();
fs.mkdirSync(OUT, { recursive: true });

const fp32 = await runConfig('fp32');
const int8 = await runConfig('int8');
let fp16 = null;
try {
  fp16 = await runConfig('fp16');
} catch (e) {
  console.log('FP16 评测失败（CPU 上可能不支持），跳过：' + e.message);
}

// 向量保真度：FP32 与量化后向量的平均余弦
const fidelity = (a, b, n = 80) => {
  const step = Math.max(1, Math.floor(a.docVecs.length / n));
  let sum = 0, cnt = 0;
  for (let i = 0; i < a.docVecs.length; i += step) {
    sum += cosine(a.docVecs[i], b.docVecs[i]);
    cnt++;
  }
  return Number((sum / cnt).toFixed(5));
};

const sizes = {};
const onnxDir = path.resolve('public/models/bge-small-zh-v1.5/onnx');
for (const f of fs.readdirSync(onnxDir)) {
  sizes[f] = Number((fs.statSync(path.join(onnxDir, f)).size / 1048576).toFixed(2));
}

/** 与 FP32 基线的排序一致性：Top1 相同率 + Top5 重合率 */
const agreement = (base, other) => {
  let sameTop1 = 0;
  let inter = 0;
  let union = 0;
  base.summary.detail.forEach((b, i) => {
    const o = other.summary.detail[i];
    if (b.top1 === o.top1) sameTop1++;
    const sb = new Set(b.top5);
    const so = new Set(o.top5);
    inter += [...sb].filter((x) => so.has(x)).length;
    union += new Set([...sb, ...so]).size;
  });
  return {
    'Top1 一致率': Number((sameTop1 / base.summary.detail.length).toFixed(4)),
    'Top5 重合率': Number((inter / union).toFixed(4)),
  };
};

const report = {
  at: new Date().toISOString(),
  device: 'CPU (onnxruntime-node, 与浏览器 WASM 同一份 ONNX 权重)',
  note: '浏览器端 WebGPU 的耗时另见 evidence/browser-bench.json；本文件只比较质量与体积',
  modelSizesMB: sizes,
  compression: {
    'fp32/int8': Number((sizes['model.onnx'] / sizes['model_int8.onnx']).toFixed(2)),
    'fp32/fp16': Number((sizes['model.onnx'] / sizes['model_fp16.onnx']).toFixed(2)),
  },
  fidelity: {
    'fp32 vs int8 平均余弦': fidelity(fp32, int8),
    ...(fp16 ? { 'fp32 vs fp16 平均余弦': fidelity(fp32, fp16) } : {}),
  },
  rankAgreement: {
    int8: agreement(fp32, int8),
    ...(fp16 ? { fp16: agreement(fp32, fp16) } : {}),
  },
  configs: [fp32.summary, int8.summary, ...(fp16 ? [fp16.summary] : [])],
};

const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
const outFile = path.join(OUT, `eval-${stamp}.json`);
fs.writeFileSync(outFile, JSON.stringify(report, null, 2));
fs.writeFileSync(path.join(OUT, 'eval-latest.json'), JSON.stringify(report, null, 2));

const pct = (x) => (x * 100).toFixed(1) + '%';
console.log('\n| 配置 | 模型体积 | 向量化吞吐 | 检索路径 | Recall@5 | nDCG@10 | MRR |');
console.log('| --- | --- | --- | --- | --- | --- | --- |');
for (const c of report.configs) {
  const size =
    c.dtype === 'fp32' ? sizes['model.onnx'] : c.dtype === 'int8' ? sizes['model_int8.onnx'] : sizes['model_fp16.onnx'];
  for (const [mode, label] of [['hybrid', '混合'], ['vectorOnly', '纯向量']]) {
    const m = c[mode];
    console.log(
      `| ${c.dtype.toUpperCase()} | ${size}MB | ${c.throughput} 块/秒 | ${label} | ${pct(m.recallAt5)} | ${pct(m.ndcgAt10)} | ${pct(m.mrr)} |`
    );
  }
}
console.log('\n向量保真度：' + JSON.stringify(report.fidelity));
console.log(`结果已写入 ${outFile}`);
console.log(`总耗时 ${((Date.now() - t0) / 1000).toFixed(1)}s`);
