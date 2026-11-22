# Milestone 2.4 — Seed Document Validation Report

**Generated:** 2026-11-21T11:58:45.432635+00:00  
**Scope:** Every seed PDF is processed through Document → Extraction → Evidence Validation → Red Flag. Each reported value is compared with the source PDF; each citation page, quote, and numeric value is independently re-verified. Ratios are recomputed with Python `Decimal`.  
**Runtime profile:** offline hashing embeddings, deterministic mock LLM, local SQLite/ChromaDB.

## Summary

- Test cases: **102**
- Passed: **102**
- Failed: **0**
- Documents: **5**

## Pipeline Results

| Document | Phase | Metrics | Verified | Rejected | Red flags | Rejected red flags |
| --- | --- | --- | --- | --- | --- | --- |
| acme_cloud_technologies_sec_10k_fy25.pdf | COMPLETED | 21 | 21 | 0 | 0 | 1 |
| apex_financial_holdings_annual_report_fy25.pdf | COMPLETED | 14 | 14 | 0 | 0 | 1 |
| infosys_annual_report_fy24.pdf | COMPLETED | 21 | 21 | 0 | 0 | 1 |
| zenith_energy_earnings_call_q4_fy25.pdf | COMPLETED | 18 | 18 | 0 | 0 | 0 |
| acme_tech_10k_fy25.pdf | COMPLETED | 21 | 21 | 0 | 0 | 1 |

## Test Cases

| ID | Company / Document | Case | Expected | Actual | Citation verification | Status | Failure explanation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| M24-001 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | Document parsed into pages | > 0 pages | 2 pages | n/a | **PASS** |  |
| M24-002 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | Chunks generated and indexed | chunks > 0 | 2 chunks | n/a | **PASS** |  |
| M24-003 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | Pipeline completed | COMPLETED | COMPLETED | n/a | **PASS** |  |
| M24-004 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | REVENUE value + citation | 14300 | 14300.00 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-005 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | GROSS_PROFIT value + citation | 9750 | 9750.00 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-006 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | NET_INCOME value + citation | 1184 | 1184.00 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-007 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | TOTAL_ASSETS value + citation | 18600 | 18600.00 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-008 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | CURRENT_ASSETS value + citation | 7950 | 7950.00 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-009 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | CURRENT_LIABILITIES value + citation | 5000 | 5000.00 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-010 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | TOTAL_DEBT value + citation | 2500 | 2500.00 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-011 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | TOTAL_LIABILITIES value + citation | 8700 | 8700.00 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-012 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | SHAREHOLDERS_EQUITY value + citation | 9900 | 9900.00 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-013 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | OPERATING_CASH_FLOW value + citation | 3150 | 3150.00 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-014 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | CAPITAL_EXPENDITURE value + citation | 1400 | 1400.00 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-015 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | CURRENT_RATIO value + citation | 1.59 | 1.59 | calculated; p.1 | **PASS** |  |
| M24-016 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | DEBT_TO_EQUITY value + citation | 0.25 | 0.25 | calculated; p.1 | **PASS** |  |
| M24-017 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | OPERATING_MARGIN value + citation | 16.08 | 16.08 | calculated; p.1 | **PASS** |  |
| M24-018 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | CURRENT_RATIO independent recomputation | 1.59 | 1.59 | inputs p.2/p.2 | **PASS** |  |
| M24-019 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | DEBT_TO_EQUITY independent recomputation | 0.25 | 0.25 | inputs p.2/p.2 | **PASS** |  |
| M24-020 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | OPERATING_MARGIN independent recomputation | 16.08 | 16.08 | inputs p.1/p.1 | **PASS** |  |
| M24-021 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | Red flag result | 0 or more evidence-backed findings | 0 findings | n/a | **PASS** |  |
| M24-022 | Acme Cloud Technologies, Inc. / acme_cloud_technologies_sec_10k_fy25.pdf | Unsupported finding rejected: Revenue Recognition Estimation Uncertainty | rejected and not persisted | Finding page 197 is outside range (1-2). | n/a | **PASS** |  |
| M24-023 | Apex Financial Holdings Group / apex_financial_holdings_annual_report_fy25.pdf | Document parsed into pages | > 0 pages | 2 pages | n/a | **PASS** |  |
| M24-024 | Apex Financial Holdings Group / apex_financial_holdings_annual_report_fy25.pdf | Chunks generated and indexed | chunks > 0 | 2 chunks | n/a | **PASS** |  |
| M24-025 | Apex Financial Holdings Group / apex_financial_holdings_annual_report_fy25.pdf | Pipeline completed | COMPLETED | COMPLETED | n/a | **PASS** |  |
| M24-026 | Apex Financial Holdings Group / apex_financial_holdings_annual_report_fy25.pdf | REVENUE value + citation | 9750 | 9750 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-027 | Apex Financial Holdings Group / apex_financial_holdings_annual_report_fy25.pdf | NET_INCOME value + citation | 2420 | 2420 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-028 | Apex Financial Holdings Group / apex_financial_holdings_annual_report_fy25.pdf | TOTAL_ASSETS value + citation | 94500 | 94500 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-029 | Apex Financial Holdings Group / apex_financial_holdings_annual_report_fy25.pdf | CURRENT_ASSETS value + citation | 28500 | 28500 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-030 | Apex Financial Holdings Group / apex_financial_holdings_annual_report_fy25.pdf | CURRENT_LIABILITIES value + citation | 18900 | 18900 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-031 | Apex Financial Holdings Group / apex_financial_holdings_annual_report_fy25.pdf | TOTAL_DEBT value + citation | 6400 | 6400 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-032 | Apex Financial Holdings Group / apex_financial_holdings_annual_report_fy25.pdf | SHAREHOLDERS_EQUITY value + citation | 11800 | 11800 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-033 | Apex Financial Holdings Group / apex_financial_holdings_annual_report_fy25.pdf | CURRENT_RATIO value + citation | 1.51 | 1.51 | calculated; p.1 | **PASS** |  |
| M24-034 | Apex Financial Holdings Group / apex_financial_holdings_annual_report_fy25.pdf | DEBT_TO_EQUITY value + citation | 0.54 | 0.54 | calculated; p.1 | **PASS** |  |
| M24-035 | Apex Financial Holdings Group / apex_financial_holdings_annual_report_fy25.pdf | OPERATING_MARGIN value + citation | 47.49 | 47.49 | calculated; p.1 | **PASS** |  |
| M24-036 | Apex Financial Holdings Group / apex_financial_holdings_annual_report_fy25.pdf | CURRENT_RATIO independent recomputation | 1.51 | 1.51 | inputs p.2/p.2 | **PASS** |  |
| M24-037 | Apex Financial Holdings Group / apex_financial_holdings_annual_report_fy25.pdf | DEBT_TO_EQUITY independent recomputation | 0.54 | 0.54 | inputs p.2/p.2 | **PASS** |  |
| M24-038 | Apex Financial Holdings Group / apex_financial_holdings_annual_report_fy25.pdf | OPERATING_MARGIN independent recomputation | 47.49 | 47.49 | inputs p.1/p.1 | **PASS** |  |
| M24-039 | Apex Financial Holdings Group / apex_financial_holdings_annual_report_fy25.pdf | Red flag result | 0 or more evidence-backed findings | 0 findings | n/a | **PASS** |  |
| M24-040 | Apex Financial Holdings Group / apex_financial_holdings_annual_report_fy25.pdf | Unsupported finding rejected: Revenue Recognition Estimation Uncertainty | rejected and not persisted | Finding page 197 is outside range (1-2). | n/a | **PASS** |  |
| M24-041 | Infosys Limited / infosys_annual_report_fy24.pdf | Document parsed into pages | > 0 pages | 2 pages | n/a | **PASS** |  |
| M24-042 | Infosys Limited / infosys_annual_report_fy24.pdf | Chunks generated and indexed | chunks > 0 | 2 chunks | n/a | **PASS** |  |
| M24-043 | Infosys Limited / infosys_annual_report_fy24.pdf | Pipeline completed | COMPLETED | COMPLETED | n/a | **PASS** |  |
| M24-044 | Infosys Limited / infosys_annual_report_fy24.pdf | REVENUE value + citation | 153670 | 153670 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-045 | Infosys Limited / infosys_annual_report_fy24.pdf | GROSS_PROFIT value + citation | 45820 | 45820 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-046 | Infosys Limited / infosys_annual_report_fy24.pdf | NET_INCOME value + citation | 26248 | 26248 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-047 | Infosys Limited / infosys_annual_report_fy24.pdf | TOTAL_ASSETS value + citation | 143260 | 143260 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-048 | Infosys Limited / infosys_annual_report_fy24.pdf | CURRENT_ASSETS value + citation | 89450 | 89450 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-049 | Infosys Limited / infosys_annual_report_fy24.pdf | CURRENT_LIABILITIES value + citation | 36210 | 36210 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-050 | Infosys Limited / infosys_annual_report_fy24.pdf | TOTAL_DEBT value + citation | 0 | 0 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-051 | Infosys Limited / infosys_annual_report_fy24.pdf | TOTAL_LIABILITIES value + citation | 44720 | 44720 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-052 | Infosys Limited / infosys_annual_report_fy24.pdf | SHAREHOLDERS_EQUITY value + citation | 98540 | 98540 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-053 | Infosys Limited / infosys_annual_report_fy24.pdf | OPERATING_CASH_FLOW value + citation | 28410 | 28410 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-054 | Infosys Limited / infosys_annual_report_fy24.pdf | CAPITAL_EXPENDITURE value + citation | 4428 | 4428 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-055 | Infosys Limited / infosys_annual_report_fy24.pdf | CURRENT_RATIO value + citation | 2.47 | 2.47 | calculated; p.1 | **PASS** |  |
| M24-056 | Infosys Limited / infosys_annual_report_fy24.pdf | OPERATING_MARGIN value + citation | 20.66 | 20.66 | calculated; p.1 | **PASS** |  |
| M24-057 | Infosys Limited / infosys_annual_report_fy24.pdf | CURRENT_RATIO independent recomputation | 2.47 | 2.47 | inputs p.2/p.2 | **PASS** |  |
| M24-058 | Infosys Limited / infosys_annual_report_fy24.pdf | OPERATING_MARGIN independent recomputation | 20.66 | 20.66 | inputs p.1/p.1 | **PASS** |  |
| M24-059 | Infosys Limited / infosys_annual_report_fy24.pdf | Red flag result | 0 or more evidence-backed findings | 0 findings | n/a | **PASS** |  |
| M24-060 | Infosys Limited / infosys_annual_report_fy24.pdf | Unsupported finding rejected: Revenue Recognition Estimation Uncertainty | rejected and not persisted | Finding page 197 is outside range (1-2). | n/a | **PASS** |  |
| M24-061 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | Document parsed into pages | > 0 pages | 2 pages | n/a | **PASS** |  |
| M24-062 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | Chunks generated and indexed | chunks > 0 | 2 chunks | n/a | **PASS** |  |
| M24-063 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | Pipeline completed | COMPLETED | COMPLETED | n/a | **PASS** |  |
| M24-064 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | REVENUE value + citation | 8420 | 8420 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-065 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | GROSS_PROFIT value + citation | 4850 | 4850 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-066 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | NET_INCOME value + citation | 1450 | 1450 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-067 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | TOTAL_ASSETS value + citation | 22400 | 22400 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-068 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | CURRENT_ASSETS value + citation | 6900 | 6900 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-069 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | CURRENT_LIABILITIES value + citation | 3200 | 3200 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-070 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | TOTAL_DEBT value + citation | 3800 | 3800 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-071 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | SHAREHOLDERS_EQUITY value + citation | 12100 | 12100 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-072 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | OPERATING_CASH_FLOW value + citation | 2650 | 2650 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-073 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | CAPITAL_EXPENDITURE value + citation | 1120 | 1120 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-074 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | CURRENT_RATIO value + citation | 2.16 | 2.16 | calculated; p.1 | **PASS** |  |
| M24-075 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | DEBT_TO_EQUITY value + citation | 0.31 | 0.31 | calculated; p.1 | **PASS** |  |
| M24-076 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | OPERATING_MARGIN value + citation | 23.52 | 23.52 | calculated; p.1 | **PASS** |  |
| M24-077 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | CURRENT_RATIO independent recomputation | 2.16 | 2.16 | inputs p.1/p.1 | **PASS** |  |
| M24-078 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | DEBT_TO_EQUITY independent recomputation | 0.31 | 0.31 | inputs p.1/p.1 | **PASS** |  |
| M24-079 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | OPERATING_MARGIN independent recomputation | 23.52 | 23.52 | inputs p.1/p.1 | **PASS** |  |
| M24-080 | Zenith Energy Resources Corp. / zenith_energy_earnings_call_q4_fy25.pdf | Red flag result | 0 or more evidence-backed findings | 0 findings | n/a | **PASS** |  |
| M24-081 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | Document parsed into pages | > 0 pages | 2 pages | n/a | **PASS** |  |
| M24-082 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | Chunks generated and indexed | chunks > 0 | 2 chunks | n/a | **PASS** |  |
| M24-083 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | Pipeline completed | COMPLETED | COMPLETED | n/a | **PASS** |  |
| M24-084 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | REVENUE value + citation | 14300 | 14300.00 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-085 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | GROSS_PROFIT value + citation | 9750 | 9750.00 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-086 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | NET_INCOME value + citation | 1184 | 1184.00 | p.1; quote=OK; value=OK | **PASS** |  |
| M24-087 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | TOTAL_ASSETS value + citation | 18600 | 18600.00 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-088 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | CURRENT_ASSETS value + citation | 7950 | 7950.00 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-089 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | CURRENT_LIABILITIES value + citation | 5000 | 5000.00 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-090 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | TOTAL_DEBT value + citation | 2500 | 2500.00 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-091 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | TOTAL_LIABILITIES value + citation | 8700 | 8700.00 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-092 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | SHAREHOLDERS_EQUITY value + citation | 9900 | 9900.00 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-093 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | OPERATING_CASH_FLOW value + citation | 3150 | 3150.00 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-094 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | CAPITAL_EXPENDITURE value + citation | 1400 | 1400.00 | p.2; quote=OK; value=OK | **PASS** |  |
| M24-095 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | CURRENT_RATIO value + citation | 1.59 | 1.59 | calculated; p.1 | **PASS** |  |
| M24-096 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | DEBT_TO_EQUITY value + citation | 0.25 | 0.25 | calculated; p.1 | **PASS** |  |
| M24-097 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | OPERATING_MARGIN value + citation | 16.08 | 16.08 | calculated; p.1 | **PASS** |  |
| M24-098 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | CURRENT_RATIO independent recomputation | 1.59 | 1.59 | inputs p.2/p.2 | **PASS** |  |
| M24-099 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | DEBT_TO_EQUITY independent recomputation | 0.25 | 0.25 | inputs p.2/p.2 | **PASS** |  |
| M24-100 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | OPERATING_MARGIN independent recomputation | 16.08 | 16.08 | inputs p.1/p.1 | **PASS** |  |
| M24-101 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | Red flag result | 0 or more evidence-backed findings | 0 findings | n/a | **PASS** |  |
| M24-102 | Acme Cloud Technologies, Inc. / acme_tech_10k_fy25.pdf | Unsupported finding rejected: Revenue Recognition Estimation Uncertainty | rejected and not persisted | Finding page 197 is outside range (1-2). | n/a | **PASS** |  |

## Notes and Remaining Issues

- The mock/deterministic LLM intentionally returns a fixed narrative auditor finding citing page 197. On the two-page seed filings this finding is rejected by evidence validation and never persisted; this demonstrates hallucination suppression rather than a missing feature.
- `acme_tech_10k_fy25.pdf` is a byte-identical copy of `acme_cloud_technologies_sec_10k_fy25.pdf`; it is included to confirm duplicate-content handling still validates citations.
- Apex Financial Holdings does not report total liabilities or cash-flow lines in its seed document, so those metrics are correctly absent rather than inferred.
- Neural SentenceTransformers embeddings are optional in this environment; retrieval validation uses the deterministic hashing embedding provider. Switch `EMBEDDING_PROVIDER=sentence-transformers` after installing that extra to use MiniLM vectors.
