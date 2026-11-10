import './style.css';
import { api, type CollectionInfo, type HealthInfo, type SearchResult } from './api';
import { chunkDocument, highlight } from './chunker';
import { loadModel, embed, backend, detectWebGPU, DIM, MODEL_ID, type PreferMode } from './embedder';

const state = {
  collections: [] as CollectionInfo[],
  current: '' as string,
  mode: 'auto' as PreferMode,
  topK: 8,
  kw: 1.0,
  vec: 1.0,
  busy: false,
  health: null as HealthInfo | null,
  lastQuery: '',
};

const $ = <T extends HTMLElement>(sel: string) => document.querySelector(sel) as T;

const app = $('#app');
app.innerHTML = `
<header class="top">
  <h1>端侧知识库 · seekdb 混合检索</h1>
  <span class="sub">浏览器本地向量化 → seekdb 内融合检索</span>
  <span class="spacer"></span>
  <span class="badge plain" id="badge-db"><span class="dot"></span>数据库连接中…</span>
  <span class="badge plain" id="badge-backend"><span class="dot"></span>推理后端待检测</span>
</header>

<main>
  <section>
    <div class="panel">
      <h2>知识库 <span class="tag" id="tag-dim">512 维</span></h2>

      <label class="field">当前集合</label>
      <div class="row">
        <select id="sel-collection"></select>
        <button id="btn-new" class="small">新建</button>
        <button id="btn-drop" class="small danger">删除</button>
      </div>

      <label class="field">推理配置</label>
      <select id="sel-mode">
        <option value="auto">自动（WebGPU 优先，否则 WASM）</option>
        <option value="wasm-int8">WASM · INT8（降级路径）</option>
        <option value="wasm-fp32">WASM · FP32（未量化基线）</option>
        <option value="webgpu-fp16">强制 WebGPU · FP16</option>
      </select>

      <label class="field">导入语料</label>
      <div class="drop" id="drop">
        把 .md / .txt 拖到这里，或
        <button id="btn-sample" class="small" style="margin-left:6px">载入示例语料</button>
        <button id="btn-file" class="small">选择文件</button>
        <input id="file-input" type="file" accept=".md,.txt,text/plain" multiple hidden />
      </div>

      <div class="progress" id="progress">
        <div class="bar"><div id="bar"></div></div>
        <div class="meta"><span id="prog-text">准备中</span><span id="prog-time"></span></div>
      </div>

      <div style="margin-top:14px">
        <div class="kv"><span>文档 / 块</span><span id="stat-count">-</span></div>
        <div class="kv"><span>最近写入</span><span id="stat-write">-</span></div>
        <div class="kv"><span>索引刷新</span><span id="stat-refresh">-</span></div>
      </div>

      <div class="log" id="log">等待操作…</div>
    </div>
  </section>

  <section>
    <div class="panel">
      <h2>检索 <span class="tag">向量 + 全文，由 seekdb 融合</span></h2>
      <div class="searchbar">
        <input id="q" type="search" placeholder="例如：冰箱启动的功率增量是多少？" autocomplete="off" />
        <button id="btn-search" class="primary">检索</button>
      </div>

      <div class="sliders">
        <div class="item">TopK <b id="v-topk">8</b>
          <input id="r-topk" type="range" min="3" max="20" value="8" step="1" />
        </div>
        <div class="item">关键词权重 <b id="v-kw">1.0</b>
          <input id="r-kw" type="range" min="0.2" max="3" value="1" step="0.1" />
        </div>
        <div class="item">语义权重 <b id="v-vec">1.0</b>
          <input id="r-vec" type="range" min="0.2" max="3" value="1" step="0.1" />
        </div>
      </div>

      <div class="results" id="results">
        <div class="empty">导入语料后输入问题，结果会显示在这里</div>
      </div>

      <div class="timings" id="timings"></div>
      <div class="row" style="margin-top:12px">
        <button id="btn-bench" class="small">跑基准（当前查询 × 10 次）</button>
        <button id="btn-eval" class="small">导出评测集规模</button>
      </div>
    </div>
  </section>
</main>
`;

function log(msg: string, isErr = false) {
  const el = $('#log');
  const line = document.createElement('div');
  if (isErr) line.className = 'err';
  line.textContent = `[${new Date().toLocaleTimeString('zh-CN', { hour12: false })}] ${msg}`;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

function setBadge(el: HTMLElement, text: string, kind: 'gpu' | 'cpu' | 'err' | 'plain') {
  el.className = `badge ${kind}`;
  el.innerHTML = `<span class="dot"></span>${text}`;
}

function setProgress(on: boolean, text = '', time = '', ratio = 0) {
  $('#progress').classList.toggle('on', on);
  $('#prog-text').textContent = text;
  $('#prog-time').textContent = time;
  $('#bar').style.width = `${Math.round(ratio * 100)}%`;
}

async function refreshCollections(selectName?: string) {
  const { collections } = await api.collections();
  state.collections = collections;
  const sel = $<HTMLSelectElement>('#sel-collection');
  sel.innerHTML = collections.length
    ? collections.map((c) => `<option value="${c.name}">${c.label}（${c.chunks} 块）</option>`).join('')
    : `<option value="">（暂无集合，请新建）</option>`;
  const wanted = selectName || state.current || collections[0]?.name || '';
  if (collections.some((c) => c.name === wanted)) {
    sel.value = wanted;
    state.current = wanted;
  } else {
    state.current = collections[0]?.name || '';
    if (state.current) sel.value = state.current;
  }
  const c = collections.find((x) => x.name === state.current);
  $('#stat-count').textContent = c ? `${new Set<string>().size || '—'} / ${c.chunks}` : '—';
  if (c) {
    const docs = Number(localStorage.getItem(`docs:${c.name}`) || 0);
    $('#stat-count').textContent = docs ? `${docs} 篇 / ${c.chunks} 块` : `${c.chunks} 块`;
  }
  $('#tag-dim').textContent = `${DIM} 维 · ${MODEL_ID}`;
}

async function ensureCollection() {
  if (state.current) return state.current;
  const name = 'kb-default';
  await api.createCollection(name, '默认知识库');
  await refreshCollections(name);
  log('已创建默认集合 kb-default');
  return name;
}

async function ensureModel() {
  if (backend()) return backend()!;
  setProgress(true, '加载模型…', '', 0.02);
  try {
    const info = await loadModel(state.mode, log);
    const ok = info.device === 'webgpu';
    setBadge($('#badge-backend'), info.label, ok ? 'gpu' : 'cpu');
    $('#badge-backend').title = `${info.reason}｜适配器：${info.adapter}`;
    return info;
  } finally {
    setProgress(false);
  }
}

/** 导入管线：分块 → 本地向量化（分批）→ 写入 seekdb → 索引刷新 → 可见 */
async function importFiles(files: { name: string; text: string }[]) {
  if (state.busy) return;
  state.busy = true;
  const btnStates = ['#btn-sample', '#btn-file', '#btn-drop'].map((s) => $(s) as HTMLButtonElement);
  btnStates.forEach((b) => (b.disabled = true));
  const tAll = performance.now();

  try {
    const col = await ensureCollection();
    await ensureModel();

    const docs = files.map((f) => chunkDocument(f.name, f.text));
    const totalChunks = docs.reduce((n, d) => n + d.chunks.length, 0);
    if (!totalChunks) throw new Error('没有解析出可用的文本块');
    log(`分块完成：${docs.length} 篇 → ${totalChunks} 块（320 字/块，重叠 60 字）`);

    const flat: { docIdx: number; chunk: { id: string; seq: number; text: string } }[] = [];
    docs.forEach((d, i) => d.chunks.forEach((c) => flat.push({ docIdx: i, chunk: c })));

    setProgress(true, `向量化 0/${totalChunks}`, '', 0.05);
    const tEmbed = performance.now();
    const vectors = await embed(
      flat.map((x) => x.chunk.text),
      {
        batchSize: 8,
        onProgress: (p) => {
          setProgress(true, `向量化 ${p.done}/${p.total}`, `${(p.elapsedMs / 1000).toFixed(1)}s`, 0.05 + 0.7 * (p.done / p.total));
        },
      }
    );
    const embedMs = performance.now() - tEmbed;
    const throughput = (totalChunks / (embedMs / 1000)).toFixed(1);
    log(`向量化完成：${totalChunks} 块 / ${(embedMs / 1000).toFixed(2)}s（${throughput} 块/秒）`);

    const payload = docs.map((d, i) => ({
      docId: d.docId,
      title: d.title,
      chunks: d.chunks.map((c) => {
        const idx = flat.findIndex((f) => f.docIdx === i && f.chunk.id === c.id);
        return { id: c.id, seq: c.seq, text: c.text, vector: vectors[idx] };
      }),
    }));

    setProgress(true, '写入 seekdb 并刷新索引…', '', 0.85);
    const tWrite = performance.now();
    const res = await api.addDocuments(col, payload);
    const writeTotal = performance.now() - tWrite;
    log(
      `写入完成：${res.inserted} 块，库内共 ${res.total} 块｜写入 ${res.timings.writeMs}ms，索引刷新 ${res.timings.refreshMs}ms`
    );

    const prev = Number(localStorage.getItem(`docs:${col}`) || 0);
    localStorage.setItem(`docs:${col}`, String(prev + docs.length));
    await refreshCollections(col);
    setProgress(true, '完成', `${((performance.now() - tAll) / 1000).toFixed(2)}s`, 1);
    $('#stat-write').textContent = `${res.timings.writeMs}ms`;
    $('#stat-refresh').textContent = `${res.timings.refreshMs}ms`;
    $('#stat-count').textContent = `${prev + docs.length} 篇 / ${res.total} 块`;
    setTimeout(() => setProgress(false), 1200);

    if (res.timings.refreshMs >= 0) {
      log(`端到端导入 ${((performance.now() - tAll) / 1000).toFixed(2)}s（含向量化 ${(embedMs / 1000).toFixed(2)}s）`);
    }
  } catch (e) {
    log('导入失败：' + (e as Error).message, true);
    setProgress(false);
  } finally {
    state.busy = false;
    btnStates.forEach((b) => (b.disabled = false));
  }
}

function renderResults(r: SearchResult, query: string, embedMs: number, totalMs: number) {
  const box = $('#results');
  if (!r.hits.length) {
    box.innerHTML = `<div class="empty">没有命中。试试调低关键词权重，或换一种说法</div>`;
  } else {
    box.innerHTML = r.hits
      .map(
        (h, i) => `
      <article class="hit">
        <div class="head">
          <span class="idx">${i + 1}</span>
          <span class="title">${h.title || h.docId}</span>
          <span class="src">${h.docId} · 块 ${h.seq}</span>
          <span class="score">score ${h.score.toFixed(3)}</span>
        </div>
        <p class="body">${highlight(h.content, query)}</p>
      </article>`
      )
      .join('');
  }
  $('#timings').innerHTML = `
    <span>查询向量化 <b>${embedMs.toFixed(1)}ms</b></span>
    <span>seekdb 检索 <b>${r.dbMs}ms</b></span>
    <span>端到端 <b>${totalMs.toFixed(1)}ms</b></span>
    <span>命中 <b>${r.hits.length}</b> / 库内 ${r.total} 块</span>
    <span>路径 <b>${r.sqlPath}</b></span>
    ${r.warning ? `<span style="color:#a32d2d">降级原因：${r.warning}</span>` : ''}
  `;
}

async function doSearch() {
  const q = $<HTMLInputElement>('#q').value.trim();
  if (!q) return;
  if (!state.current) {
    log('请先导入语料或新建集合', true);
    return;
  }
  state.lastQuery = q;
  const btn = $<HTMLButtonElement>('#btn-search');
  btn.disabled = true;
  const t0 = performance.now();
  try {
    await ensureModel();
    const [vector] = await embed([q], { isQuery: true });
    const embedMs = performance.now() - t0;
    const r = await api.search({
      collection: state.current,
      query: q,
      vector,
      topK: state.topK,
      kwBoost: state.kw,
      vecBoost: state.vec,
    });
    renderResults(r, q, embedMs, performance.now() - t0);
  } catch (e) {
    log('检索失败：' + (e as Error).message, true);
  } finally {
    btn.disabled = false;
  }
}

// ---------- 事件绑定 ----------
$('#sel-collection').addEventListener('change', (e) => {
  state.current = (e.target as HTMLSelectElement).value;
  refreshCollections(state.current);
});

$('#btn-new').addEventListener('click', async () => {
  const name = prompt('新集合名（英文/数字/短横线，如 kb-nilm）', 'kb-' + Date.now().toString(36).slice(-4));
  if (!name) return;
  try {
    await api.createCollection(name, name);
    await refreshCollections(name);
    log(`集合 ${name} 已创建（VECTOR(${DIM}) + HNSW + FULLTEXT ik）`);
  } catch (e) {
    log('创建失败：' + (e as Error).message, true);
  }
});

$('#btn-drop').addEventListener('click', async () => {
  if (!state.current) return;
  if (!confirm(`删除集合 ${state.current} 及其全部数据？`)) return;
  try {
    await api.deleteCollection(state.current);
    log(`集合 ${state.current} 已删除`);
    state.current = '';
    await refreshCollections();
  } catch (e) {
    log('删除失败：' + (e as Error).message, true);
  }
});

$('#sel-mode').addEventListener('change', async (e) => {
  const mode = (e.target as HTMLSelectElement).value as PreferMode;
  if (mode === state.mode) return;
  state.mode = mode;
  log(`切换推理配置为 ${mode}，需重新加载模型（刷新页面生效）`);
  location.reload();
});

$('#btn-file').addEventListener('click', () => $<HTMLInputElement>('#file-input').click());
$('#file-input').addEventListener('change', async (e) => {
  const input = e.target as HTMLInputElement;
  const files = Array.from(input.files || []);
  if (!files.length) return;
  const loaded = await Promise.all(files.map(async (f) => ({ name: f.name, text: await f.text() })));
  await importFiles(loaded);
  input.value = '';
});

$('#btn-sample').addEventListener('click', async () => {
  try {
    const { files } = await api.corpus();
    if (!files.length) return log('data/corpus/ 为空，请先放入 .md / .txt', true);
    log(`载入示例语料 ${files.length} 篇`);
    await importFiles(files);
  } catch (e) {
    log('载入失败：' + (e as Error).message, true);
  }
});

const drop = $('#drop');
['dragenter', 'dragover'].forEach((t) =>
  drop.addEventListener(t, (e) => {
    e.preventDefault();
    drop.classList.add('over');
  })
);
['dragleave', 'drop'].forEach((t) =>
  drop.addEventListener(t, (e) => {
    e.preventDefault();
    drop.classList.remove('over');
  })
);
drop.addEventListener('drop', async (e) => {
  const dt = (e as DragEvent).dataTransfer;
  const files = Array.from(dt?.files || []).filter((f) => /\.(md|txt)$/i.test(f.name));
  if (!files.length) return log('只支持 .md / .txt', true);
  const loaded = await Promise.all(files.map(async (f) => ({ name: f.name, text: await f.text() })));
  await importFiles(loaded);
});

$('#btn-search').addEventListener('click', doSearch);
$('#q').addEventListener('keydown', (e) => {
  if ((e as KeyboardEvent).key === 'Enter') doSearch();
});

const bindRange = (id: string, key: 'topK' | 'kw' | 'vec', fmt: (v: number) => string) => {
  const el = $<HTMLInputElement>(id);
  el.addEventListener('input', () => {
    const v = Number(el.value);
    (state as unknown as Record<string, number>)[key] = v;
    $(id.replace('r-', 'v-')).textContent = fmt(v);
  });
};
bindRange('#r-topk', 'topK', (v) => String(v));
bindRange('#r-kw', 'kw', (v) => v.toFixed(1));
bindRange('#r-vec', 'vec', (v) => v.toFixed(1));

$('#btn-bench').addEventListener('click', async () => {
  const q = state.lastQuery || $<HTMLInputElement>('#q').value.trim() || '事件检测的常用方法';
  if (!state.current) return log('请先导入语料', true);
  try {
    await ensureModel();
    const runs: number[] = [];
    const dbRuns: number[] = [];
    for (let i = 0; i < 10; i++) {
      const t0 = performance.now();
      const [vector] = await embed([q], { isQuery: true });
      const tEmbed = performance.now() - t0;
      const r = await api.search({
        collection: state.current, query: q, vector,
        topK: state.topK, kwBoost: state.kw, vecBoost: state.vec,
      });
      runs.push(tEmbed + r.dbMs);
      dbRuns.push(r.dbMs);
    }
    const med = (a: number[]) => [...a].sort((x, y) => x - y)[Math.floor(a.length / 2)];
    const info = backend()!;
    const payload = {
      backend: info.label,
      device: info.device,
      dtype: info.dtype,
      adapter: info.adapter,
      query: q,
      topK: state.topK,
      chunks: state.collections.find((c) => c.name === state.current)?.chunks ?? 0,
      loadMs: info.loadMs,
      warmMs: info.warmMs,
      embedPlusDbMedianMs: Number(med(runs).toFixed(2)),
      dbMedianMs: Number(med(dbRuns).toFixed(2)),
      all: runs.map((x) => Number(x.toFixed(2))),
      userAgent: navigator.userAgent,
    };
    const res = await api.bench(payload);
    log(`基准完成（中位数 端到端 ${payload.embedPlusDbMedianMs}ms，库内检索 ${payload.dbMedianMs}ms），已写入 ${res.file}`);
  } catch (e) {
    log('基准失败：' + (e as Error).message, true);
  }
});

$('#btn-eval').addEventListener('click', async () => {
  const c = state.collections.find((x) => x.name === state.current);
  log(`当前集合 ${state.current}：${c?.chunks ?? 0} 块；语料目录 data/corpus；评测集 data/eval/queries.json（npm run eval 计算 Recall@K）`);
});

// ---------- 启动 ----------
(async function boot() {
  try {
    const h = await api.health();
    state.health = h;
    setBadge($('#badge-db'), `seekdb ${h.db.version.replace('5.7.25-', '')}`, 'gpu');
    $('#badge-db').title = `${h.db.mode}\n数据目录：${h.db.dir}\n${h.db.dirReason}\n监听 ${h.db.endpoint.host}:${h.db.endpoint.port}`;
    log(`seekdb 就绪：${h.db.version}，启动 ${h.db.bootMs}ms，目录 ${h.db.dir}`);
    if (h.db.dirReason.includes('降级')) log(h.db.dirReason, true);

    await refreshCollections();
    if (!state.collections.length) {
      await api.createCollection('kb-default', '默认知识库');
      await refreshCollections('kb-default');
      log('已自动创建默认集合 kb-default');
    }

    const gpu = await detectWebGPU();
    log(`WebGPU 检测：${gpu.ok ? '可用' : '不可用'}（${gpu.reason}${gpu.ok ? '，适配器 ' + gpu.adapter : ''}）`);

    await ensureModel();
  } catch (e) {
    log('启动失败：' + (e as Error).message, true);
    setBadge($('#badge-db'), '数据库不可用', 'err');
    setBadge($('#badge-backend'), '推理未就绪', 'err');
  }
})();
