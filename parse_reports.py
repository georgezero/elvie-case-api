#!/usr/bin/env python3
"""
parse_reports.py — Parse radiology reports with the elvie report parser prompt
and write elvie-case-v1 JSON files ready for the Case API.

Usage:
  python3 parse_reports.py [--layout 1x1|1x2|1x3|2x2] <report.txt> [<report.txt> ...]

  --layout   Viewer layout to embed in study.viewerLayout (default: none / let viewer decide).
             Applies to all reports in the current invocation.

Examples:
  python3 parse_reports.py --layout 1x1 ct_head.txt cxr.txt
  python3 parse_reports.py --layout 2x2 mr_knee.txt

Output files are written to ./cases/ using the caseId as the filename.
"""

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR  = Path(__file__).resolve().parent
PROMPT_FILE = SCRIPT_DIR / 'report-parser-prompt.txt'
CASES_DIR   = SCRIPT_DIR / 'cases'

LLM_BASE = os.environ.get('LLM_BASE', '')
MODEL    = os.environ.get('LLM_MODEL', '')

# Known report filenames → caseId (handles irregularities like mr-knee vs mr-left-knee)
CASEID_MAP = {
    'json_api_demo_1_ct_head_report':   'json-api-demo-1-ct-head',
    'json_api_demo_2_mr_knee_report':   'json-api-demo-2-mr-left-knee',
    'json_api_demo_3_cxr_report':       'json-api-demo-3-cxr',
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def slugify(s):
    return re.sub(r'-{2,}', '-', re.sub(r'[^a-z0-9]+', '-', s.lower())).strip('-')


def derive_case_id(path):
    stem = Path(path).stem
    if stem in CASEID_MAP:
        return CASEID_MAP[stem]
    # fallback: underscore → hyphen, drop trailing -report
    return re.sub(r'-report$', '', stem.replace('_', '-'))


def extract_meta(text):
    """Pull accession, modality, studyDescription from the report header."""
    accession = None
    m = re.search(r'ACCESSION[:\s]+(\S+)', text, re.IGNORECASE)
    if m:
        accession = m.group(1).strip()

    modality = study_desc = None
    m = re.search(r'EXAM[:\s]+(.+)', text, re.IGNORECASE)
    if not m:
        m = re.search(r'^(CT|MR[I]?|Chest radiograph|X-ray|Ultrasound).+', text, re.IGNORECASE | re.MULTILINE)
    if m:
        exam = m.group(1).strip()
        study_desc = exam.title()
        u = exam.upper()
        if 'CT' in u:                                           modality = 'CT'
        elif 'MR' in u:                                         modality = 'MR'
        elif any(x in u for x in ('CHEST', 'CXR', 'RADIOGRAPH', 'X-RAY', 'FRONTAL')): modality = 'CR'
        elif any(x in u for x in ('US', 'ULTRASOUND')):         modality = 'US'

    return accession, modality, study_desc


# ── LLM call ─────────────────────────────────────────────────────────────────

def build_system_prompt():
    base = PROMPT_FILE.read_text()
    return base + """

ADDITIONAL RULES:
- raw_text MUST be an exact verbatim phrase copied from the FINDINGS section of the report.
  NEVER use text from the IMPRESSION section as raw_text.
- For every finding in both "findings" and "negativeFindings", add:
    "patientFriendlyExplanation": "1-2 plain-language sentences about this specific finding. No jargon."
"""


def call_llm(report_text, system_prompt):
    user_msg = (
        'Parse this radiology report.\n'
        'IMPORTANT: raw_text must be copied verbatim from the FINDINGS section, '
        'not from the IMPRESSION section.\n\n'
        + report_text
    )
    payload = json.dumps({
        'model': MODEL,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user',   'content': user_msg},
        ],
        'temperature': 0.1,
    }).encode()

    req = urllib.request.Request(
        f'{LLM_BASE}/chat/completions',
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read())
    return data['choices'][0]['message']['content']


def extract_findings_json(content):
    """Extract the findings JSON from the LLM response.

    Handles: raw JSON, ```findings-json``` blocks, and ```json``` blocks.
    """
    # Model may return raw JSON directly
    try:
        return json.loads(content.strip())
    except json.JSONDecodeError:
        pass

    # Code-fenced block
    for pattern in [r'```findings-json\s*(.*?)\s*```', r'```json\s*(.*?)\s*```']:
        m = re.search(pattern, content, re.DOTALL)
        if m:
            return json.loads(m.group(1))

    # Walk chars to find the first complete {...} object
    depth, in_str, escape, start = 0, False, False, -1
    for i, c in enumerate(content):
        if escape:           escape = False; continue
        if c == '\\' and in_str: escape = True; continue
        if c == '"':         in_str = not in_str; continue
        if not in_str:
            if c == '{':
                if depth == 0: start = i
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0 and start != -1:
                    return json.loads(content[start:i+1])

    raise ValueError('No JSON found in LLM response')


# ── Payload builder ───────────────────────────────────────────────────────────

def enrich_finding(f, idx):
    """Add id and source fields; preserve all LLM fields."""
    return {
        'id': slugify(f.get('label', f'finding-{idx}')),
        **f,
        'source': 'api-preparsed',
    }


def build_payload(report_path, parsed, viewer_layout=None):
    text = Path(report_path).read_text()
    accession, modality, study_desc = extract_meta(text)
    case_id = derive_case_id(report_path)

    findings     = [enrich_finding(f, i) for i, f in enumerate(parsed.get('findings',         []))]
    neg_findings = [enrich_finding(f, i) for i, f in enumerate(parsed.get('negativeFindings', []))]

    study = {
        'modality':         modality,
        'studyDescription': study_desc,
        'studyDate':        None,
        'mrn':              None,
    }
    if viewer_layout:
        study['viewerLayout'] = viewer_layout

    return {
        'schemaVersion': 'elvie-case-v1',
        'caseId':        case_id,
        'accession':     accession,
        'study':         study,
        'report': {
            'text':       text,
            'sourceType': 'api-preparsed',
        },
        'findings':         findings,
        'negativeFindings': neg_findings,
        'summary':     parsed.get('summary',     ''),
        'explanation': parsed.get('explanation', ''),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_report(report_path, system_prompt, viewer_layout=None):
    print(f'\n── {Path(report_path).name}')
    text    = Path(report_path).read_text()
    print('  calling LLM...')
    content = call_llm(text, system_prompt)
    parsed  = extract_findings_json(content)
    payload = build_payload(report_path, parsed, viewer_layout=viewer_layout)

    CASES_DIR.mkdir(exist_ok=True)
    out_path = CASES_DIR / f"{payload['caseId']}.json"
    out_path.write_text(json.dumps(payload, indent=2))
    layout_note = f', layout={viewer_layout}' if viewer_layout else ''
    print(f'  {len(payload["findings"])} findings, {len(payload["negativeFindings"])} negative{layout_note}')
    print(f'  saved → {out_path}')
    return out_path


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    viewer_layout = None
    if '--layout' in args:
        idx = args.index('--layout')
        if idx + 1 >= len(args):
            print('ERROR: --layout requires a value (1x1, 1x2, 1x3, 2x2)')
            sys.exit(1)
        viewer_layout = args[idx + 1]
        if viewer_layout not in ('1x1', '1x2', '1x3', '2x2'):
            print(f'ERROR: invalid layout {viewer_layout!r}, must be one of: 1x1 1x2 1x3 2x2')
            sys.exit(1)
        args = args[:idx] + args[idx + 2:]

    if not args:
        print('ERROR: no report files specified')
        sys.exit(1)

    if not LLM_BASE or not MODEL:
        print('ERROR: LLM_BASE and LLM_MODEL environment variables must be set')
        print('  export LLM_BASE=http://localhost:8000/v1')
        print('  export LLM_MODEL=your-model-name')
        sys.exit(1)

    system_prompt = build_system_prompt()
    for path in args:
        try:
            parse_report(path, system_prompt, viewer_layout=viewer_layout)
        except Exception as e:
            print(f'  ERROR: {e}')
            raise


if __name__ == '__main__':
    main()
