export interface Chunk {
  id: string;
  seq: number;
  text: string;
}

export interface ChunkedDoc {
  docId: string;
  title: string;
  chunks: Chunk[];
}

const MAX_CHARS = 320;
const OVERLAP = 60;

/** 稳定短哈希（FNV-1a），用于生成幂等的块 ID：同一文档重复导入不会产生重复行 */
function hash(str: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16).padStart(8, '0');
}

function clean(text: string): string {
  return text
    .replace(/\r\n/g, '\n')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/[*_`>]/g, '')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/**
 * 按中文标点切句再聚合，避免把一句话切成两半。
 * 块大小 320 字、重叠 60 字：检索粒度与上下文完整性的折中。
 */
export function chunkDocument(fileName: string, raw: string, maxChars = MAX_CHARS, overlap = OVERLAP): ChunkedDoc {
  const text = clean(raw);
  const headingMatch = raw.match(/^#\s+(.+)$/m);
  const title = headingMatch ? headingMatch[1].trim() : fileName.replace(/\.(md|txt)$/i, '');

  const sentences = text.split(/(?<=[。！？；\n])/).filter((s) => s.trim().length > 0);
  const chunks: Chunk[] = [];
  let buf = '';

  const push = () => {
    const body = buf.trim();
    if (body.length < 12) {
      buf = '';
      return;
    }
    const seq = chunks.length;
    chunks.push({ id: `${hash(fileName)}-${seq}-${hash(body.slice(0, 80))}`, seq, text: body });
    buf = body.slice(Math.max(0, body.length - overlap));
  };

  for (const s of sentences) {
    if (buf.length + s.length > maxChars && buf.length > 0) push();
    buf += s;
    while (buf.length > maxChars * 2) {
      // 超长单句兜底：硬切
      const head = buf.slice(0, maxChars);
      buf = head;
      push();
    }
  }
  if (buf.trim().length >= 12) {
    const seq = chunks.length;
    const body = buf.trim();
    chunks.push({ id: `${hash(fileName)}-${seq}-${hash(body.slice(0, 80))}`, seq, text: body });
  }

  return { docId: fileName, title, chunks };
}

/** 查询词高亮：中文按 2-gram 打点，英文按词 */
export function highlight(text: string, query: string): string {
  const esc = text.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c] as string);
  const terms = new Set<string>();
  for (const w of query.split(/[\s,，、。;；:：]+/)) {
    if (!w) continue;
    if (/[\u4e00-\u9fa5]/.test(w)) {
      if (w.length <= 2) terms.add(w);
      for (let i = 0; i < w.length - 1; i++) terms.add(w.slice(i, i + 2));
    } else if (w.length > 1) {
      terms.add(w);
    }
  }
  const list = [...terms].filter((t) => t.length > 0).sort((a, b) => b.length - a.length).slice(0, 60);
  if (!list.length) return esc;
  const re = new RegExp('(' + list.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'gi');
  return esc.replace(re, '<mark>$1</mark>');
}
