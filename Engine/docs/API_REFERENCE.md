# API Reference (Milestones 1–3)

Base URL: `http://localhost:8000`  
Interactive schema: `http://localhost:8000/docs`

All endpoints return JSON unless noted. Errors use FastAPI's `{"detail": "..."}` shape.
Financial claims are returned only when sourced from an ingested document; missing data is
represented as `null` / an `unavailable_information` entry, never as an invented value.

## Milestone 1 — Workspaces, sessions, documents

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Database, storage, vector-store, embedding and LLM readiness |
| POST | `/workspaces` | Create a research workspace |
| GET | `/workspaces` | List workspaces |
| GET | `/workspaces/{workspace_id}` | Workspace detail |
| POST | `/workspaces/{workspace_id}/sessions` | Create a named research session |
| GET | `/workspaces/{workspace_id}/sessions` | List sessions in a workspace |
| GET | `/sessions/{session_id}` | Session detail with document IDs |
| POST | `/documents/upload?workspace_id=&session_id=` | Upload/parse/chunk/embed/index a PDF and queue analysis |
| POST | `/sessions/{session_id}/documents/upload` | Upload directly into a session |
| GET | `/documents` | List documents (optional `workspace_id`) |
| GET | `/documents/{document_id}` | Document summary |
| GET | `/documents/{document_id}/file` | Stream the original PDF |
| POST | `/documents/seed` | Ingest bundled seed filings |
| DELETE | `/documents/{document_id}` | Delete metadata, file and associated records |
| POST | `/search` | Semantic chunk search (`query`, `top_k`, `document_id`, `filter_tables_only`) |

## Milestone 2 — Analysis pipeline and evidence

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/documents/process` (or `/documents/{id}/process`) | Run Document → Extraction → Evidence Validation → Red Flag |
| GET | `/documents/{document_id}/status` | Processing stage and agent run statuses |
| GET | `/documents/{document_id}/extraction` | Persisted metrics grouped by statement |
| GET | `/documents/{document_id}/red-flags` | Persisted, evidence-validated findings |
| GET | `/workflows/{job_id}/status` | Durable processing job status |

`POST /documents/{id}/process` returns `status: COMPLETED | FAILED`, the phase,
counts, `errors`, and per-node execution logs. A failed agent always marks the job
`FAILED`; partial outputs are not presented as validated findings.

## Milestone 3 — Research, comparison, report

### Research Agent

| Method | Path | Body / notes |
| --- | --- | --- |
| POST | `/research/sessions/{session_id}/query` | `{"question": str, "document_ids": [str]?, "top_k": int}` |
| POST | `/research/query` | Same body; stateless (no session persistence) |
| GET | `/research/sessions/{session_id}/messages` | Persisted conversation turns |
| DELETE | `/research/sessions/{session_id}/messages` | Clear conversation context |

Response (`ResearchAnswerResponse`):

```json
{
  "question": "...",
  "answer": "grounded narrative",
  "direct_facts": ["..."],
  "calculated_values": ["..."],
  "analytical_conclusions": ["..."],
  "unavailable_information": ["EBITDA was not found ..."],
  "citations": [
    {
      "document_id": "...",
      "document_name": "infosys_annual_report_fy24.pdf",
      "company": "Infosys Limited",
      "page_number": 1,
      "exact_quote": "Revenue from operations | 153,670 ...",
      "section": "FINANCIAL STATEMENTS",
      "metric_name": "REVENUE",
      "is_calculated": false
    }
  ],
  "steps": [{"step": 1, "title": "Question decomposition", "detail": "..."}],
  "documents_used": ["..."],
  "context_used": ["previous follow-up question if used"],
  "grounding": "strict_source_documents",
  "session_id": "...",
  "message_id": "..."
}
```

### Comparison Agent

`POST /comparison`

```json
{
  "document_ids": ["doc-a", "doc-b"],
  "metrics": ["REVENUE", "NET_INCOME", "TOTAL_ASSETS", "TOTAL_LIABILITIES",
              "CURRENT_RATIO", "DEBT_TO_EQUITY", "OPERATING_MARGIN"]
}
```

Returns per-company values with original value, unit-normalized value (millions),
page citation, `missing_metrics`, `warnings` (currency/period mismatches),
`limitations`, and a summary. Cross-currency ranking and deltas are deliberately
not computed.

### Report Agent (M3.4 initial)

`POST /reports/generate` — `{"document_id": "..."}`

Returns `GeneratedReport` with `sections` (`executive_summary`, `key_financials`),
`planned_sections` (`Red Flags`, `Company Comparison`, `Outlook`), citations,
and limitations. This is not PDF export; PDF export remains Milestone 4.
