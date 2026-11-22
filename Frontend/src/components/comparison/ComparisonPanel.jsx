import React, { useEffect, useMemo, useState } from "react";
import { AlertTriangle, GitCompare, RefreshCw, ShieldCheck } from "lucide-react";
import api from "../../services/api";

/**
 * Cross-company benchmarking panel.
 * Only displays values returned by the Comparison Agent; no client-side
 * financial calculations or placeholder values are used.
 */
export default function ComparisonPanel({ documents = [], session = null, setPage }) {
  const indexedDocuments = useMemo(
    () => documents.filter((doc) => doc && (doc.status === "Ready" || doc.pages > 0)),
    [documents]
  );

  const sessionDocuments = useMemo(() => {
    const sessionDocIds = (session?.documents || [])
      .map((doc) => doc.id || doc.documentId)
      .filter(Boolean);
    if (!sessionDocIds.length) return [];
    return indexedDocuments.filter((doc) => sessionDocIds.includes(doc.id));
  }, [indexedDocuments, session]);

  const [selectedIds, setSelectedIds] = useState([]);
  const [result, setResult] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    // Default to the active session's filings, but allow any indexed filing so
    // cross-company comparisons are possible when a session holds only one company.
    const defaults = sessionDocuments.length >= 2 ? sessionDocuments : indexedDocuments;
    setSelectedIds(defaults.slice(0, 4).map((doc) => doc.id));
    setResult(null);
    setError(null);
  }, [session?.id, sessionDocuments, indexedDocuments]);

  function toggleDocument(docId) {
    setSelectedIds((prev) =>
      prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId]
    );
  }

  async function handleCompare() {
    if (selectedIds.length < 2) {
      setError("Select at least two indexed filings to compare.");
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const response = await api.compareCompanies({ document_ids: selectedIds });
      setResult(response);
    } catch (err) {
      setResult(null);
      setError(err?.message || "The Comparison Agent could not complete this comparison.");
    } finally {
      setIsLoading(false);
    }
  }

  function metricFor(company, metricName) {
    return (company.metrics || []).find((metric) => metric.metric_name === metricName);
  }

  if (!indexedDocuments.length) {
    return (
      <div className="tab-content animate-fadeIn">
        <div className="fin-empty-inquiry-box py-8 text-center">
          <GitCompare size={26} className="mx-auto text-muted mb-2" />
          <h3 className="text-base font-semibold text-main">No indexed filings available</h3>
          <p className="text-xs text-muted mt-1">
            Upload or ingest at least two company documents before running a peer comparison.
          </p>
          {setPage && (
            <button type="button" className="fin-btn fin-btn-primary fin-btn-xs mt-4" onClick={() => setPage("Documents")}>
              Open Document Library
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="tab-content animate-fadeIn">
      <div className="fin-card p-4 mb-4">
        <div className="flex-row items-center justify-between gap-3 flex-wrap">
          <div>
            <h3 className="text-sm font-bold text-main flex-row items-center gap-2">
              <GitCompare size={16} className="text-teal" />
              Cross-Company Benchmarking
            </h3>
            <p className="text-xs text-muted mt-1">
              Values come from evidence-validated extractions. Units are normalized to millions for
              same-currency peers; currencies and periods are never silently mixed.
            </p>
          </div>
          <button
            type="button"
            className="fin-btn fin-btn-primary fin-btn-xs"
            onClick={handleCompare}
            disabled={isLoading || selectedIds.length < 2}
          >
            {isLoading ? <RefreshCw size={13} className="animate-spin mr-1" /> : <GitCompare size={13} className="mr-1" />}
            {isLoading ? "Comparing..." : "Compare Selected"}
          </button>
        </div>

        <div className="flex-row flex-wrap gap-2 mt-3">
          {indexedDocuments.map((doc) => (
            <button
              key={doc.id}
              type="button"
              onClick={() => toggleDocument(doc.id)}
              className={`fin-btn fin-btn-xs ${selectedIds.includes(doc.id) ? "fin-btn-primary" : "fin-btn-secondary"}`}
              title={doc.name}
            >
              {selectedIds.includes(doc.id) ? "✓ " : ""}
              {doc.company || doc.name}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="fin-chat-error-card mb-4">
          <div className="flex-row items-center gap-2">
            <AlertTriangle size={15} className="text-danger" />
            <strong className="text-xs text-danger">Comparison Error</strong>
          </div>
          <p className="text-xs text-muted mt-1">{error}</p>
        </div>
      )}

      {result && (
        <div className="space-y-4">
          <div className="fin-card p-4">
            <h4 className="text-xs font-bold uppercase tracking-wider text-muted mb-2">Agent Summary</h4>
            <p className="text-xs text-main leading-relaxed">{result.summary}</p>
            {result.warnings?.length > 0 && (
              <ul className="mt-2 space-y-1">
                {result.warnings.map((warning, index) => (
                  <li key={index} className="text-xs text-warning flex-row items-start gap-1">
                    <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                    <span>{warning}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
            {result.companies.map((company) => (
              <div key={company.document_id} className="fin-card p-3">
                <div className="flex-row items-center justify-between gap-2">
                  <strong className="text-xs text-main">{company.company_name}</strong>
                  <span className="fin-badge fin-badge-xs fin-badge-outline">
                    {company.fiscal_year ? `FY${company.fiscal_year}` : "Period n/a"} · {company.currency || "Currency n/a"}
                  </span>
                </div>
                <span className="text-[11px] text-muted block truncate mt-1" title={company.filename}>
                  {company.filename}
                </span>

                <table className="fin-custom-table mt-2">
                  <thead>
                    <tr>
                      <th>Metric</th>
                      <th>Value</th>
                      <th>Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.metric_names.map((metricName) => {
                      const metric = metricFor(company, metricName);
                      return (
                        <tr key={metricName}>
                          <td>{metricName.replace(/_/g, " ")}</td>
                          <td>
                            {metric?.display_value || (
                              <span className="text-warning">Unavailable</span>
                            )}
                          </td>
                          <td>
                            {metric?.page_number ? (
                              <span className="text-teal">p. {metric.page_number}</span>
                            ) : (
                              <span className="text-muted">—</span>
                            )}
                            {metric?.is_calculated && <span className="text-muted"> (calc)</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>

                {company.missing_metrics?.length > 0 && (
                  <p className="text-[11px] text-muted mt-2">
                    Missing: {company.missing_metrics.map((m) => m.replace(/_/g, " ")).join(", ")}
                  </p>
                )}
              </div>
            ))}
          </div>

          <div className="fin-card p-3">
            <h4 className="text-xs font-bold uppercase tracking-wider text-muted mb-1 flex-row items-center gap-1">
              <ShieldCheck size={13} className="text-teal" /> Limitations
            </h4>
            <ul className="space-y-1">
              {(result.limitations || []).map((item, index) => (
                <li key={index} className="text-[11px] text-muted">• {item}</li>
              ))}
            </ul>
            {result.citations?.length > 0 && (
              <p className="text-[11px] text-muted mt-2">
                {result.citations.length} page-level citation(s) returned with this comparison.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
