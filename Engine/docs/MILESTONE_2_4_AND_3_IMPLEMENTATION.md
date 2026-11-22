# Milestones 2.4 and 3 — Implementation Report

**Status:** Implemented and tested on the bundled seed documents.  
**Runtime verified:** Python 3.13 virtualenv, FastAPI TestClient, SQLite + ChromaDB, offline hashing embeddings.  
**Cloud dependencies:** none required for the verified path. OpenAI / Supabase / Qdrant remain optional production profiles.

---

## 1. Milestone 2.4 — Testing and evidence validation

### 1.1 Evidence validation (`app/orchestration/evidence.py`, `workflow.py`)

| Requirement | Implementation |
| --- | --- |
| Metric has a valid source document | `validate_metrics` requires the document row to exist and the citation `document_id` to match |
| Citation references an existing document | Same check; mismatches are rejected with a reason |
| Cited page exists in the PDF | Page must satisfy `1 <= page <= total_pages`; page text is loaded from bytes, disk, or storage |
| Quoted snippet verifiable on page | Normalized substring match, then token-coverage + numeric-agreement fallback; quotes with unsupported numbers always fail |
| Unsupported metrics rejected | Rejected metrics are removed from state and **deleted from `ai_financial_metrics`** by replacing the persisted set with the verified subset |
| Calculated ratios | Accepted only when `formula` references input metrics that were themselves verified |
| Red flag evidence | Narrative findings must have a verified quote; rule findings must cite a page carrying a verified metric |
| Validation failures recorded | `validation_issues`, `ai_agent_runs` (`EVIDENCE_VALIDATION`), job `error_message`, and failed phase |
| No silent acceptance | Zero verified metrics fails the pipeline; unsupported findings are not persisted |

Additional extraction correctness fix: canonical label matching is prefix-based, so
`Prepaid and Other Current Assets` no longer overrides `Current Assets`.

### 1.2 Red Flag failure handling (`red_flag_agent_node`)

- Exceptions set `is_failed = True`, `validation_passed = False`, clear partial findings,
  update the processing job to `FAILED` with `RED_FLAG_AGENT`, and write a failed
  `ai_agent_runs` row.
- The persistence node now computes success as `not is_failed and validation_passed`, so a
  failed job can never be overwritten as `COMPLETED`.
- Findings rejected by evidence validation are removed from the state and the database.

### 1.3 Tests and report

- `tests/test_m24_validation.py` — 32 tests covering document upload/parse/dedupe/empty PDF/
  chunk metadata/embeddings, extraction values and ratios, unsupported metric rejection,
  red-flag rules and evidence checks, and orchestration failure handling.
- `scripts/validate_seed_documents.py` — runs all five bundled PDFs and writes
  `docs/VALIDATION_REPORT.md` + `docs/validation_report.json`.
- Current result: **102/102 validation cases pass**; 5/5 documents complete the pipeline.
  The deterministic mock LLM's fabricated page-197 finding is rejected on every 2-page
  filing, demonstrating hallucination suppression.

---

## 2. Milestone 3 — Research, Comparison, Report

### 2.1 Research Agent (`app/agents/research_agent/`)

- Decomposes multi-part questions into retrieval sub-questions.
- Resolves documents from explicit IDs, the session's documents, or the workspace.
- Retrieves per document with the existing vector store (per-document filters, so Qdrant
  and Chroma both work).
- Numeric facts come only from persisted metrics (`ai_financial_metrics`) with page/quote
  citations; narrative evidence comes from retrieved chunks.
- Produces direct facts, calculated values, deterministic conclusions, unavailable
  information, step-by-step retrieval trace, and citations.
- Follow-up questions use prior session turns for pronoun/short-question resolution.
- Session history is stored in `ai_research_messages` (SQLite + PostgreSQL).
- No LLM answer generation: synthesis is deterministic to avoid unsupported claims.

### 2.2 Comparison Agent (`app/agents/comparison_agent/`)

- Compares revenue, net income, assets, liabilities, debt, equity, cash flow and ratios.
- Normalizes CRORES/LAKHS/MILLIONS/BILLIONS/THOUSANDS to millions for same-currency peers.
- Warns on differing fiscal periods and currencies; never ranks across currencies.
- Marks missing metrics explicitly and preserves per-value page citations.
- Surfaced in the UI at Analysis → Peer Comparison
  (`Frontend/src/components/comparison/ComparisonPanel.jsx`): multi-select filings, calls
  `POST /comparison`, and renders per-company metric tables, warnings, missing metrics and
  citation counts. It never computes values client-side.

### 2.3 Conversational interface (`Frontend/src/pages/ConversationalResearch.jsx`)

- The `Research` route now renders this page directly (`App.jsx`); the previous
  "Milestone 3 — Under Development" stub is gone.
- Uses `POST /research/sessions/{id}/query` and the persisted message history.
- Shows agent progress, structured answer, step trace, source excerpts, citations, and an
  explicit "Not Available in Source Documents" block.
- Citation chips open the existing citation panel; "Open Document at Page N" hands the
  cited document and page to the existing document viewer.
- API errors are surfaced; the previous mock-answer fallback was removed so the UI never
  displays fabricated financial analysis.

### 2.4 Report Agent (`app/agents/report_agent/`)

- Section registry with `executive_summary` and `key_financials` implemented.
- Executive Summary uses only stored metrics + evidence-validated red flags.
- Key Financials renders a citation-backed Markdown table grouped by statement.
- `Red Flags`, `Company Comparison`, `Outlook` are declared as planned sections for M4.
- No PDF export is claimed or implemented.

---

## 3. Data and API changes

- New table: `ai_research_messages` (SQLite DDL, PostgreSQL DDL, Alembic revision `002`).
- New endpoints: `/research/*`, `/comparison`, `/reports/generate`.
- New schemas: `app/schemas/research.py`.
- New optional embedding provider: deterministic 384-dim hashing provider used when
  SentenceTransformers is unavailable or `EMBEDDING_PROVIDER=hashing`.

---

## 4. Known limitations

- The research synthesis is extractive/deterministic. It prioritizes faithfulness over
  fluent prose; an LLM phrasing layer is intentionally not used.
- Seed filings are two pages each. Narrative retrieval quality on long filings depends on
  the configured embedding provider.
- OCR is not implemented for scanned PDFs.
- Report PDF export, Red Flags/Comparison/Outlook report sections, and report persistence
  remain Milestone 4 work.
- Multi-tenant authorization and storage RLS remain outstanding from the earlier audit.
