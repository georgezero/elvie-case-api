import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { mkdir, readdir, readFile, rename, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const PORT      = Number(process.env.PORT) || 8787;
const CASES_DIR = process.env.CASES_DIR    || './cases';

const app = new Hono();

// Echo any origin back — this dev server has no auth so all origins are fine.
// Credentials require a reflected origin (can't use '*' with credentials:true).
app.use('*', cors({
  origin: (origin) => origin || '*',
  allowMethods: ['GET', 'PUT', 'OPTIONS'],
  allowHeaders: ['Content-Type'],
  credentials: true,
}));

app.get('/health', (c) => c.json({ ok: true, casesDir: CASES_DIR }));

app.put('/api/cases/:caseId', async (c) => {
  const caseId = c.req.param('caseId');
  if (!/^[A-Za-z0-9_\-]+$/.test(caseId)) {
    return c.json({ error: 'Invalid caseId' }, 400);
  }

  let payload: any;
  try {
    payload = await c.req.json();
  } catch {
    return c.json({ error: 'Request body must be JSON' }, 400);
  }

  if (payload?.caseId && payload.caseId !== caseId) {
    return c.json({ error: 'caseId in body must match URL caseId' }, 400);
  }

  payload = { ...payload, caseId };
  const filePath = join(CASES_DIR, `${caseId}.json`);
  const tempPath = join(CASES_DIR, `.${caseId}.${Date.now()}.tmp`);

  try {
    await mkdir(CASES_DIR, { recursive: true });
    await writeFile(tempPath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
    await rename(tempPath, filePath);
    return c.json({ ok: true, caseId, accession: payload.accession || null });
  } catch (e: any) {
    return c.json({ error: 'Failed to write case', detail: e.message }, 500);
  }
});

// Must be registered before /api/cases/:caseId to prevent "by-accession" being swallowed
app.get('/api/cases/by-accession/:accession', async (c) => {
  const accession = c.req.param('accession');
  if (!/^[A-Za-z0-9_\-]+$/.test(accession)) {
    return c.json({ error: 'Invalid accession' }, 400);
  }

  let files: string[];
  try {
    files = (await readdir(CASES_DIR)).filter(f => f.endsWith('.json'));
  } catch (e: any) {
    return c.json({ error: 'Cannot read cases directory', detail: e.message }, 500);
  }

  for (const file of files) {
    let payload: any;
    try {
      payload = JSON.parse(await readFile(join(CASES_DIR, file), 'utf8'));
    } catch {
      continue;
    }
    if (String(payload?.accession || '').trim() === accession) {
      return c.json(payload);
    }
  }

  return c.json({ error: 'Case not found', accession }, 404);
});

app.get('/api/cases/:caseId', async (c) => {
  const caseId = c.req.param('caseId');
  if (!/^[A-Za-z0-9_\-]+$/.test(caseId)) {
    return c.json({ error: 'Invalid caseId' }, 400);
  }

  const filePath = join(CASES_DIR, `${caseId}.json`);
  let raw: string;
  try {
    raw = await readFile(filePath, 'utf8');
  } catch (e: any) {
    if (e.code === 'ENOENT') return c.json({ error: 'Case not found', caseId }, 404);
    return c.json({ error: 'Failed to read case', detail: e.message }, 500);
  }

  try {
    return c.json(JSON.parse(raw));
  } catch {
    return c.json({ error: 'Case file contains invalid JSON', caseId }, 500);
  }
});

console.log(`elvie-case-api listening on port ${PORT}`);
console.log(`  cases dir  : ${CASES_DIR}`);

export default { port: PORT, hostname: '0.0.0.0', fetch: app.fetch };
