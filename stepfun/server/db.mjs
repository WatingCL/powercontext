import { seekdb } from '@oceanbase/seekdb-node';
import mysql from 'mysql2/promise';
import { DB_NAME, DIM, resolveDbDir, ensureDir } from './config.mjs';

let dbHandle = null;
let pool = null;
let info = { dir: '', endpoint: null, version: '', bootMs: 0, dirReason: '' };

const slug = (name) =>
  String(name || '')
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 40);

export const tableName = (name) => `t_${slug(name)}`;

const vecLiteral = (v) => '[' + v.map((x) => Number(x).toFixed(6)).join(',') + ']';

/** query_string 语法里这些字符会被当成操作符，先抹平再交给分词器 */
const sanitizeQuery = (q) =>
  String(q || '')
    .replace(/[+\-&|!(){}[\]^"~*?:\\/]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 200);

export async function initDb() {
  if (pool) return info;
  const { dir, reason } = resolveDbDir();
  ensureDir(dir);
  const t0 = Date.now();
  dbHandle = await seekdb.open(dir, {
    parameters: { memory_budget: process.env.SEEKDB_MEMORY || '1G' },
  });
  const bootMs = Date.now() - t0;
  const ep = dbHandle.connectionOptions();
  if (ep.transport !== 'tcp') {
    throw new Error(`当前仅支持 TCP 连接，实际为 ${ep.transport}`);
  }

  const bootstrap = await mysql.createConnection({
    host: ep.host,
    port: ep.port,
    user: ep.user,
    password: '',
    database: 'test',
  });
  await bootstrap.query(`CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\``);
  await bootstrap.end();

  pool = mysql.createPool({
    host: ep.host,
    port: ep.port,
    user: ep.user,
    password: '',
    database: DB_NAME,
    connectionLimit: 4,
    multipleStatements: false,
    charset: 'utf8mb4',
  });

  const [[ver]] = await pool.query('SELECT VERSION() AS v');
  await pool.query(`CREATE TABLE IF NOT EXISTS collections_meta (
      name VARCHAR(64) PRIMARY KEY,
      label VARCHAR(190),
      dim INT NOT NULL,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ORGANIZATION HEAP`);

  info = {
    dir,
    dirReason: reason,
    endpoint: { host: ep.host, port: ep.port, user: ep.user, database: DB_NAME },
    version: ver.v,
    bootMs,
    mode: 'embedded-server（随应用启动的本地 seekdb 进程）',
  };
  return info;
}

export const dbInfo = () => info;

export async function listCollections() {
  const [rows] = await pool.query(
    `SELECT name, label, dim, created_at FROM collections_meta ORDER BY created_at`
  );
  const out = [];
  for (const r of rows) {
    let chunks = 0;
    try {
      const [[c]] = await pool.query(`SELECT COUNT(*) AS c FROM \`${tableName(r.name)}\``);
      chunks = Number(c.c);
    } catch {
      chunks = -1;
    }
    out.push({
      name: r.name,
      label: r.label,
      dim: r.dim,
      chunks,
      createdAt: r.created_at,
      table: tableName(r.name),
    });
  }
  return out;
}

export async function createCollection(name, label) {
  const t = tableName(name);
  if (!t || t === 't_') throw new Error('集合名不合法');
  await pool.query(`CREATE TABLE IF NOT EXISTS \`${t}\` (
      id VARCHAR(96) PRIMARY KEY,
      doc_id VARCHAR(64) NOT NULL,
      doc_title VARCHAR(255),
      seq INT,
      content TEXT,
      embedding VECTOR(${DIM}),
      VECTOR INDEX vidx(embedding) WITH (distance=cosine, type=hnsw, lib=vsag),
      FULLTEXT INDEX fidx(content) WITH PARSER ik
    ) ORGANIZATION HEAP`);
  await pool.query(
    `INSERT INTO collections_meta (name, label, dim) VALUES (?,?,?)
     ON DUPLICATE KEY UPDATE label = VALUES(label)`,
    [name, label || name, DIM]
  );
  return { name, label: label || name, table: t };
}

export async function dropCollection(name) {
  const t = tableName(name);
  await pool.query(`DROP TABLE IF EXISTS \`${t}\``);
  await pool.query(`DELETE FROM collections_meta WHERE name = ?`, [name]);
  return { ok: true };
}

export async function insertChunks(collection, chunks) {
  if (!chunks.length) return { inserted: 0, writeMs: 0 };
  const t = tableName(collection);
  const t0 = Date.now();
  const BATCH = 32;
  let inserted = 0;
  for (let i = 0; i < chunks.length; i += BATCH) {
    const slice = chunks.slice(i, i + BATCH);
    const placeholders = slice.map(() => '(?,?,?,?,?,?)').join(',');
    const params = [];
    for (const c of slice) {
      params.push(
        c.id,
        c.docId,
        c.title || '',
        Number(c.seq || 0),
        c.text,
        vecLiteral(c.vector)
      );
    }
    await pool.query(
      `INSERT INTO \`${t}\` (id, doc_id, doc_title, seq, content, embedding)
       VALUES ${placeholders}
       ON DUPLICATE KEY UPDATE doc_title=VALUES(doc_title), content=VALUES(content), embedding=VALUES(embedding)`,
      params
    );
    inserted += slice.length;
  }
  return { inserted, writeMs: Date.now() - t0 };
}

export async function countChunks(collection) {
  const [[r]] = await pool.query(`SELECT COUNT(*) AS c FROM \`${tableName(collection)}\``);
  return Number(r.c);
}

export async function refreshIndex() {
  const t0 = Date.now();
  await pool.query('CALL dbms_index_manager.refresh()');
  return { refreshMs: Date.now() - t0 };
}

/**
 * 混合检索完全在 seekdb 内完成：DBMS_HYBRID_SEARCH.SEARCH 同时执行
 * 全文（ik 分词）+ 向量（HNSW）并按 boost 融合打分，客户端不做任何拼合。
 */
export async function hybridSearch(collection, { query, vector, topK = 8, kwBoost = 1.0, vecBoost = 1.0, vectorOnly = false }) {
  const t = tableName(collection);
  const total = await countChunks(collection);
  if (total === 0) return { hits: [], dbMs: 0, total: 0, sqlPath: 'empty' };

  const parm = {
    ...(vectorOnly
      ? {}
      : {
          query: {
            query_string: {
              fields: ['content'],
              query: sanitizeQuery(query),
              boost: Number(kwBoost),
            },
          },
        }),
    knn: {
      field: 'embedding',
      k: Math.max(1, Math.min(50, Number(topK) || 8)),
      query_vector: vector.map((x) => Number(Number(x).toFixed(6))),
      boost: Number(vecBoost),
    },
  };

  const t0 = Date.now();
  try {
    await pool.query('SET @parm = ?', [JSON.stringify(parm)]);
    const [rows] = await pool.query(
      `SELECT DBMS_HYBRID_SEARCH.SEARCH('${DB_NAME}.${t}', @parm) AS r`
    );
    const dbMs = Date.now() - t0;
    const raw = rows[0]?.r;
    const list = Array.isArray(raw) ? raw : raw ? JSON.parse(String(raw)) : [];
    const hits = list.map((r) => ({
      id: r.id,
      docId: r.doc_id,
      title: r.doc_title || r.doc_id,
      seq: r.seq,
      content: r.content,
      score: Number(r._score),
    }));
    return { hits, dbMs, total, sqlPath: vectorOnly ? 'DBMS_HYBRID_SEARCH（仅 knn）' : 'DBMS_HYBRID_SEARCH.SEARCH' };
  } catch (e) {
    // 全文语法异常时退回纯向量检索（仍在库内完成），并把错误带回前端便于排查
    const t1 = Date.now();
    const [rows] = await pool.query(
      `SELECT id, doc_id, doc_title, seq, content, cosine_distance(embedding, ?) AS d
       FROM \`${t}\` ORDER BY d LIMIT ?`,
      [vecLiteral(vector), parm.knn.k]
    );
    return {
      hits: rows.map((r) => ({
        id: r.id,
        docId: r.doc_id,
        title: r.doc_title || r.doc_id,
        seq: r.seq,
        content: r.content,
        score: 1 - Number(r.d),
      })),
      dbMs: Date.now() - t1,
      total,
      sqlPath: 'vector-only（混合检索报错后的降级）',
      warning: e.message,
    };
  }
}

export async function closeDb() {
  if (pool) await pool.end();
  if (dbHandle) dbHandle.close();
  pool = null;
  dbHandle = null;
}
