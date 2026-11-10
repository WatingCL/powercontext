import express from 'express';
import fs from 'node:fs';
import path from 'node:path';
import {
  PORT, DIM, MODEL_DIR, MODEL_LABEL, corpusDir, evalFile, evidenceDir,
} from './config.mjs';
import {
  initDb, dbInfo, listCollections, createCollection, dropCollection,
  insertChunks, countChunks, refreshIndex, hybridSearch, closeDb,
} from './db.mjs';

const app = express();
app.use(express.json({ limit: '80mb' }));

const asyncRoute = (fn) => (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next);

app.get('/api/health', asyncRoute(async (_req, res) => {
  res.json({
    ok: true,
    db: dbInfo(),
    model: { dir: MODEL_DIR, label: MODEL_LABEL, dim: DIM },
    serverTime: new Date().toISOString(),
  });
}));

app.get('/api/collections', asyncRoute(async (_req, res) => {
  res.json({ collections: await listCollections() });
}));

app.post('/api/collections', asyncRoute(async (req, res) => {
  const { name, label } = req.body || {};
  if (!name) return res.status(400).json({ error: '缺少 name' });
  const c = await createCollection(name, label);
  res.json({ ok: true, collection: { ...c, chunks: 0 } });
}));

app.delete('/api/collections/:name', asyncRoute(async (req, res) => {
  res.json(await dropCollection(req.params.name));
}));

app.post('/api/documents', asyncRoute(async (req, res) => {
  const { collection, documents } = req.body || {};
  if (!collection) return res.status(400).json({ error: '缺少 collection' });
  if (!Array.isArray(documents) || !documents.length) {
    return res.status(400).json({ error: 'documents 为空' });
  }
  const chunks = [];
  for (const d of documents) {
    for (const c of d.chunks || []) {
      if (!Array.isArray(c.vector) || c.vector.length !== DIM) {
        return res.status(400).json({ error: `块 ${c.id} 向量维度不是 ${DIM}` });
      }
      chunks.push({ id: c.id, docId: d.docId, title: d.title, seq: c.seq, text: c.text, vector: c.vector });
    }
  }
  const t0 = Date.now();
  const write = await insertChunks(collection, chunks);
  const refresh = await refreshIndex();
  const total = await countChunks(collection);
  res.json({
    ok: true,
    inserted: write.inserted,
    total,
    timings: { writeMs: write.writeMs, refreshMs: refresh.refreshMs, serverMs: Date.now() - t0 },
  });
}));

app.post('/api/search', asyncRoute(async (req, res) => {
  const { collection, query, vector, topK, kwBoost, vecBoost, vectorOnly } = req.body || {};
  if (!collection) return res.status(400).json({ error: '缺少 collection' });
  if (!Array.isArray(vector) || vector.length !== DIM) {
    return res.status(400).json({ error: `查询向量维度不是 ${DIM}` });
  }
  const r = await hybridSearch(collection, { query, vector, topK, kwBoost, vecBoost, vectorOnly });
  res.json({ ok: true, ...r });
}));

app.post('/api/refresh', asyncRoute(async (req, res) => {
  const { collection } = req.body || {};
  const r = await refreshIndex();
  const total = collection ? await countChunks(collection) : null;
  res.json({ ok: true, ...r, total });
}));

app.get('/api/corpus', asyncRoute(async (_req, res) => {
  if (!fs.existsSync(corpusDir)) return res.json({ files: [] });
  const files = fs
    .readdirSync(corpusDir)
    .filter((f) => /\.(md|txt)$/i.test(f))
    .sort()
    .map((f) => ({
      name: f,
      size: fs.statSync(path.join(corpusDir, f)).size,
      text: fs.readFileSync(path.join(corpusDir, f), 'utf8'),
    }));
  res.json({ files });
}));

app.get('/api/eval-set', asyncRoute(async (_req, res) => {
  if (!fs.existsSync(evalFile)) return res.json({ queries: [] });
  res.json(JSON.parse(fs.readFileSync(evalFile, 'utf8')));
}));

app.post('/api/bench', asyncRoute(async (req, res) => {
  fs.mkdirSync(evidenceDir, { recursive: true });
  const file = path.join(evidenceDir, 'browser-bench.json');
  let all = [];
  if (fs.existsSync(file)) {
    try { all = JSON.parse(fs.readFileSync(file, 'utf8')); } catch { all = []; }
  }
  all.push({ at: new Date().toISOString(), ...req.body });
  fs.writeFileSync(file, JSON.stringify(all, null, 2));
  res.json({ ok: true, records: all.length, file: 'evidence/browser-bench.json' });
}));

// onnxruntime 运行时（由 scripts/setup-ort.mjs 复制到 src/ort）
app.use('/ort', express.static(path.resolve('src/ort'), { maxAge: '7d' }));

const dist = path.resolve('dist');
if (fs.existsSync(dist)) {
  app.use(express.static(dist));
  app.get(/^(?!\/api).*/, (_req, res) => res.sendFile(path.join(dist, 'index.html')));
}

app.use((err, _req, res, _next) => {
  console.error('[api error]', err.message);
  res.status(500).json({ error: err.message });
});

const info = await initDb();
console.log('seekdb 已就绪：', JSON.stringify(info, null, 2));
if (info.dirReason.includes('降级')) console.warn('[注意]', info.dirReason);

const server = app.listen(PORT, () => {
  console.log(`API 服务 http://127.0.0.1:${PORT}`);
});
const shutdown = async () => {
  console.log('\n关闭中...');
  server.close();
  await closeDb();
  process.exit(0);
};
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
