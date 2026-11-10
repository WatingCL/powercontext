const j = async (res: Response) => {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((data as { error?: string }).error || `HTTP ${res.status}`);
  return data;
};

export interface CollectionInfo {
  name: string;
  label: string;
  dim: number;
  chunks: number;
  table: string;
}

export interface Hit {
  id: string;
  docId: string;
  title: string;
  seq: number;
  content: string;
  score: number;
}

export interface SearchResult {
  hits: Hit[];
  dbMs: number;
  total: number;
  sqlPath: string;
  warning?: string;
}

export interface HealthInfo {
  ok: boolean;
  db: {
    dir: string;
    dirReason: string;
    endpoint: { host: string; port: number; user: string; database: string };
    version: string;
    bootMs: number;
    mode: string;
  };
  model: { dir: string; label: string; dim: number };
}

export const api = {
  health: () => fetch('/api/health').then(j) as Promise<HealthInfo>,
  collections: () => fetch('/api/collections').then(j) as Promise<{ collections: CollectionInfo[] }>,
  createCollection: (name: string, label: string) =>
    fetch('/api/collections', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name, label }),
    }).then(j),
  deleteCollection: (name: string) =>
    fetch('/api/collections/' + encodeURIComponent(name), { method: 'DELETE' }).then(j),
  addDocuments: (collection: string, documents: unknown) =>
    fetch('/api/documents', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ collection, documents }),
    }).then(j) as Promise<{ inserted: number; total: number; timings: { writeMs: number; refreshMs: number } }>,
  search: (payload: unknown) =>
    fetch('/api/search', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(j) as Promise<SearchResult>,
  corpus: () =>
    fetch('/api/corpus').then(j) as Promise<{ files: { name: string; size: number; text: string }[] }>,
  bench: (payload: unknown) =>
    fetch('/api/bench', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(j),
};
