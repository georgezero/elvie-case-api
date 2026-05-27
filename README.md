# elvie-case-api

Minimal Bun + Hono server that serves pre-parsed case JSON to the elvie-viewer URL launch flow.

## Quick start

```bash
bun install
bun dev
```

Server starts on `http://localhost:8787`.

## Config

Copy `.env.example` to `.env`:

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8787` | Listen port |
| `CASES_DIR` | `./cases` | Directory of case JSON files |

## Routes

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `GET` | `/api/cases/:caseId` | Fetch case by file stem |
| `GET` | `/api/cases/by-accession/:accession` | Fetch case by `accession` field |

## Case files

Drop elvie-case-payload JSON files into `cases/`. The filename (without `.json`) becomes the `caseId`.

```
cases/
  json-api-demo-1-ct-head.json
  json-api-demo-2-mr-left-knee.json
  json-api-demo-3-cxr.json
```

## Viewer launch

Configure `Case API base URL = http://localhost:8787` in the viewer Settings panel, then:

```
index.html?caseId=json-api-demo-1-ct-head
index.html?accession=NI9f7fae
```

## curl examples

```bash
curl http://localhost:8787/api/cases/json-api-demo-1-ct-head
curl http://localhost:8787/api/cases/by-accession/NI9f7fae
curl http://localhost:8787/health
```

## Parsing reports

`parse_reports.py` calls an OpenAI-compatible LLM to convert radiology report text into case JSON.

```bash
export LLM_BASE=http://localhost:8000/v1
export LLM_MODEL=your-model-name

python3 parse_reports.py --layout 1x1 ct_head.txt
python3 parse_reports.py --layout 2x2 mr_knee.txt
```

Output is written to `cases/{caseId}.json`. Supported layouts: `1x1`, `1x2`, `1x3`, `2x2`.

## Case payload schema

```json
{
  "schemaVersion": "elvie-case-v1",
  "caseId": "...",
  "accession": "...",
  "study": { "modality": "CT", "studyDescription": "...", "viewerLayout": "1x1" },
  "report": { "text": "...", "sourceType": "api-preparsed" },
  "summary": "...",
  "explanation": "...",
  "findings": [...],
  "negativeFindings": [...]
}
```
