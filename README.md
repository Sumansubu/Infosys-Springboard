# Multi-Agent AI Analysis System for Financial Research and Business Insights

**Infosys Springboard — Vidzai Digital**

An evidence-grounded multi-agent system that ingests corporate financial disclosures
(annual reports, SEC 10-K/10-Q filings, earnings call transcripts), extracts audited
financial metrics, validates every citation against the source PDF, detects forensic red
flags, answers research questions, benchmarks peers, and drafts report sections.

**Core directive — strict source grounding:** every figure, ratio, and finding is bound to a
document, page, and verbatim quote. Arithmetic is performed in Python `Decimal`, not by an
LLM. When a value cannot be sourced, the API returns `null` / an `unavailable_information`
entry instead of inventing one.

---

## Repository layout

```
.
├── Engine/          FastAPI backend, agents, orchestration, tests, seed filings
├── Frontend/        React 19 + Vite analyst workspace
├── docs/            handoff documentation (architecture, API, environment, status)
├── .env.example     root configuration template (no real credentials)
├── .gitignore       excludes secrets, databases, vector stores, uploads, build output
└── package_submission.py  builds a clean submission ZIP (backend + frontend)
```

- `Engine/README.md` — backend overview, endpoints, and local run guide.
- `Frontend/README.md` — UI modules and frontend build guide.
- `Engine/docs/` — agent architecture, API reference, data models, testing strategy,
  validation report, and milestone implementation reports.

---

## Agents and pipeline

| # | Agent | Responsibility |
|---|---|---|
| 1 | Document Agent | PyMuPDF layout parsing, structure-aware chunking, embeddings, indexing |
| 2 | Extraction Agent | GAAP/IFRS line-item mapping, `Decimal` ratios, page/quote citations |
| — | Evidence Validation | Verifies cited document, page range, quote, and numeric value; rejects unsupported metrics and findings |
| 3 | Red Flag Agent | Deterministic forensic rules plus disclosure audits |
| 4 | Research Agent | Multi-document grounded Q&A with citations and session history |
| 5 | Comparison Agent | Unit-normalized peer benchmarking with currency/period warnings |
| 6 | Report Agent | Executive Summary and Key Financials sections from stored evidence |

Orchestration is a durable, database-backed pipeline (`POST /documents/{id}/process`)
with per-agent run records and job status. See `Engine/docs/ORCHESTRATION.md` and
`Engine/docs/AGENT_ARCHITECTURE.md`.

---

## Milestone status

| Milestone | Scope | Status |
|---|---|---|
| 1 | Document intelligence, workspaces/sessions, ingestion and vector indexing | Complete |
| 2 | Extraction Agent, Red Flag Agent, sequential orchestration | Complete |
| 2.4 | Evidence validation, hallucination suppression, seed validation report | Complete — 102/102 cases pass |
| 3 | Research Agent, Comparison Agent, conversational UI | Complete |
| 3.4 | Report Agent (Executive Summary + Key Financials) | Backend complete; Reports UI remains a Milestone 4 stub |
| 4 | Remaining report sections, PDF export, report persistence | Pending |

Details and evidence: `Engine/docs/IMPLEMENTATION_STATUS.md`,
`Engine/docs/MILESTONE_2_4_AND_3_IMPLEMENTATION.md`, `Engine/docs/VALIDATION_REPORT.md`.

---

## Local setup

### Backend

```powershell
cd Engine
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env          # then edit values; never commit .env
.\venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
```

API docs: <http://localhost:8000/docs>. The optional durable worker runs with
`.\venv\Scripts\python.exe worker.py`.

Offline profile (no cloud keys): `EMBEDDING_PROVIDER=hashing`, `VECTOR_STORE_TYPE=chroma`,
`LLM_PROVIDER=mock`, `STORAGE_PROVIDER=local`. `chromadb` is optional; if it is missing the
system falls back to a dependency-free persistent JSON cosine index.

### Frontend

```bash
cd Frontend
npm ci
npm run dev
```

Vite serves on port 5173 and proxies `/api` to `http://localhost:8000`.

### Seed filings

```powershell
cd Engine
.\venv\Scripts\python.exe scripts\create_seed_pdfs.py
.\venv\Scripts\python.exe scripts\test_seed_ingestion.py
```

Five PDFs ship in `Engine/seed_documents/` (Acme Cloud 10-K, Acme Tech 10-K Alternate,
Apex Financial annual report, Infosys annual report, Zenith Energy earnings call).

---

## Tests and validation

```powershell
cd Engine
.\venv\Scripts\python.exe run_tests.py                      # 115 tests, 1 skipped
.\venv\Scripts\python.exe scripts\validate_seed_documents.py
```

The test runner uses an isolated temporary SQLite database, temporary upload directory, and a
temporary vector index, so the demo data in `documents.db` is never modified. The seed
validation script writes `Engine/docs/VALIDATION_REPORT.md` and
`Engine/docs/validation_report.json`.

---

## Configuration and secrets

Copy `.env.example` (or `Engine/.env.example`) to `.env` and fill in values locally.
Keys are read from the environment by `Engine/app/config.py`.

| Variable group | Purpose |
|---|---|
| `DATABASE_URL` / `SQLITE_DB_PATH` | Supabase PostgreSQL in production, SQLite locally |
| `STORAGE_PROVIDER`, `SUPABASE_*`, `UPLOAD_DIR` | Local filesystem or Supabase Storage |
| `VECTOR_STORE_TYPE`, `QDRANT_*`, `CHROMA_*` | Qdrant primary, ChromaDB fallback |
| `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION` | OpenAI, SentenceTransformers, or offline hashing |
| `LLM_PROVIDER`, `OPENAI_API_KEY`, `LLM_MODEL` | Live reasoning or deterministic mock |

No credentials are committed. `.gitignore` excludes `.env*` (except `.env.example`),
databases, vector stores, uploaded PDFs, logs, virtualenvs, `node_modules`, and build output.

**Verified profile:** Python 3.13 venv, SQLite, local storage, ChromaDB, hashing embeddings,
mock LLM. The OpenAI, Supabase, and Qdrant cloud profiles are implemented adapters but were
not verified in this environment.

---

## Packaging a submission

```powershell
cd Engine
.\venv\Scripts\python.exe ..\package_submission.py
```

Produces `Infosys-Springboard-submission.zip` next to the project folder containing
`Engine/`, `Frontend/`, `docs/`, and the root files, while excluding runtime artifacts, and
then verifies that the required entry points are present inside the archive.
