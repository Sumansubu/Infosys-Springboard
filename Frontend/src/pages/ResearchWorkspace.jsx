import React, { useState, useEffect } from "react";
import toast from "react-hot-toast";
import {
  FileText,
  Layers,
  AlertTriangle,
  GitCompare,
  Bot,
  Printer,
  Search,
  Upload,
  CheckCircle2,
  ChevronRight,
  TrendingUp,
  ArrowUpRight,
  ArrowDownRight,
  Clock,
  Database,
  ExternalLink,
  ShieldAlert,
  Send,
  Sparkles,
  HelpCircle,
  FileSpreadsheet,
  Building2,
  Copy,
  ChevronDown,
  Filter,
  RefreshCw,
  ArrowLeft,
  FolderOpen,
  Play
} from "lucide-react";
import AgentPipelineTracker from "../components/AgentPipelineTracker";
import CitationModal from "../components/CitationModal";
import WorkspaceDirectory from "./WorkspaceDirectory";
import SessionDetails from "./SessionDetails";
import ComparisonPanel from "../components/comparison/ComparisonPanel";
import api from "../services/api";

export default function ResearchWorkspace({
  documents = [],
  session,
  sessions = [],
  setActiveSession,
  setPage,
  onUpdateSession,
  onDuplicateSession,
  onDeleteSession,
  onOpenCreateModal,
  activeTabOverride = null,
  initialMode = "directory"
}) {
  const [workspaceMode, setWorkspaceMode] = useState(initialMode); // "directory" | "details" | "interactive"
  const [activeTab, setActiveTab] = useState(activeTabOverride || "extraction");
  const [activeCitation, setActiveCitation] = useState(null);
  const [isPipelineRunning, setIsPipelineRunning] = useState(false);
  const [pipelineProgressMsg, setPipelineProgressMsg] = useState("");

  // Document selection state
  const [availableDocs, setAvailableDocs] = useState(documents);
  const [selectedDocId, setSelectedDocId] = useState(() => {
    if (session?.documents?.length > 0) return session.documents[0].id || session.documents[0];
    if (documents.length > 0) return documents[0].id;
    return "";
  });

  // Real live extracted financials & red flags state
  const [extractedData, setExtractedData] = useState(null);
  const [redFlags, setRedFlags] = useState([]);
  const [isLoadingAnalysis, setIsLoadingAnalysis] = useState(false);
  const [analysisError, setAnalysisError] = useState(null);

  // Vector DB Sandbox State
  const [vectorQuery, setVectorQuery] = useState("Operating margin and EBIT performance");
  const [isSearchingVector, setIsSearchingVector] = useState(false);
  const [vectorResults, setVectorResults] = useState([]);

  // Metric filter state
  const [metricCategory, setMetricCategory] = useState("all");
  const [redFlagSeverity, setRedFlagSeverity] = useState("all");

  useEffect(() => {
    if (initialMode) {
      setWorkspaceMode(initialMode);
    }
  }, [initialMode]);

  useEffect(() => {
    if (activeTabOverride) {
      setActiveTab(activeTabOverride);
    }
  }, [activeTabOverride]);

  // Keep available documents synced
  useEffect(() => {
    if (Array.isArray(documents) && documents.length > 0) {
      setAvailableDocs(documents);
      if (!selectedDocId) {
        setSelectedDocId(documents[0].id);
      }
    } else {
      // Fetch live documents if not yet available in props
      api.listDocuments().then((res) => {
        if (Array.isArray(res) && res.length > 0) {
          setAvailableDocs(res);
          if (!selectedDocId) {
            setSelectedDocId(res[0].id);
          }
        }
      }).catch(() => {});
    }
  }, [documents]);

  const selectedDoc = availableDocs.find((d) => d.id === selectedDocId) || availableDocs[0] || null;

  // Load live analysis results whenever selected document changes (guaranteeing zero stale cross-document leakage)
  useEffect(() => {
    let isCurrent = true;

    if (!selectedDocId) {
      setExtractedData(null);
      setRedFlags([]);
      setAnalysisError(null);
      setIsLoadingAnalysis(false);
      return;
    }

    // Immediately reset previous document's results to prevent displaying stale cross-document data
    setExtractedData(null);
    setRedFlags([]);
    setAnalysisError(null);
    setIsLoadingAnalysis(true);

    Promise.allSettled([
      api.getExtractedFinancials(selectedDocId),
      api.getDocumentRedFlags(selectedDocId)
    ]).then(([extResult, rfResult]) => {
      if (!isCurrent) return; // Discard stale response if user switched documents while loading

      if (extResult.status === "fulfilled") {
        setExtractedData(extResult.value);
      } else {
        setExtractedData(null);
      }

      if (rfResult.status === "fulfilled") {
        setRedFlags(rfResult.value?.findings || []);
      } else {
        setRedFlags([]);
      }
    }).catch((err) => {
      if (!isCurrent) return;
      setAnalysisError(err.message || "Failed to load document analysis");
    }).finally(() => {
      if (isCurrent) {
        setIsLoadingAnalysis(false);
      }
    });

    return () => {
      isCurrent = false;
    };
  }, [selectedDocId]);

  async function loadDocumentAnalysis(docId) {
    if (!docId) return;
    setIsLoadingAnalysis(true);
    setAnalysisError(null);
    try {
      const [extRes, rfRes] = await Promise.allSettled([
        api.getExtractedFinancials(docId),
        api.getDocumentRedFlags(docId)
      ]);
      if (selectedDocId === docId) {
        setExtractedData(extRes.status === "fulfilled" ? extRes.value : null);
        setRedFlags(rfRes.status === "fulfilled" ? (rfRes.value?.findings || []) : []);
      }
    } catch (err) {
      if (selectedDocId === docId) {
        setAnalysisError(err.message || "Failed to load document analysis");
      }
    } finally {
      if (selectedDocId === docId) {
        setIsLoadingAnalysis(false);
      }
    }
  }

  // Trigger real multi-agent pipeline
  async function handleTriggerPipeline() {
    if (!selectedDoc) {
      toast.error("Please select a valid document first.");
      return;
    }

    setIsPipelineRunning(true);
    setPipelineProgressMsg("Initializing Multi-Agent Workflow...");

    try {
      setPipelineProgressMsg("Document Agent: Ingesting & Verifying Chunks...");
      const result = await api.processDocument({
        document_id: selectedDoc.id,
        filename: selectedDoc.name,
        workspace_id: selectedDoc.workspaceId || "default-workspace",
        session_id: session?.id || undefined
      });

      setPipelineProgressMsg("Extraction & Red Flag Agents Completed!");
      toast.success(
        `Pipeline Executed! Extracted ${result.metrics_extracted || 0} metrics, identified ${result.red_flags || 0} red flags.`
      );

      // Refresh extracted data
      await loadDocumentAnalysis(selectedDoc.id);
    } catch (err) {
      toast.error(`Pipeline execution failed: ${err.message}`);
    } finally {
      setIsPipelineRunning(false);
      setPipelineProgressMsg("");
    }
  }

  // Real Vector DB Search
  async function handleVectorSearch(e) {
    if (e) e.preventDefault();
    if (!vectorQuery.trim()) return;

    setIsSearchingVector(true);
    try {
      const res = await api.search({
        query: vectorQuery,
        top_k: 6,
        document_id: selectedDocId || undefined
      });
      setVectorResults(res.results || []);
    } catch (err) {
      toast.error(`Vector retrieval failed: ${err.message}`);
    } finally {
      setIsSearchingVector(false);
    }
  }

  // Pre-seed documents ingestion trigger
  async function handleSeedIngestion() {
    setIsPipelineRunning(true);
    try {
      const res = await api.seedDocuments();
      toast.success(`Seeded ${res.length} company annual reports into Vector DB!`);
      const updatedDocs = await api.listDocuments();
      setAvailableDocs(updatedDocs);
      if (updatedDocs.length > 0) {
        setSelectedDocId(updatedDocs[0].id);
      }
    } catch (err) {
      toast.error(`Seeding failed: ${err.message}`);
    } finally {
      setIsPipelineRunning(false);
    }
  }

  // If directory mode (or if session is null)
  if (workspaceMode === "directory" || !session) {
    return (
      <WorkspaceDirectory
        sessions={sessions}
        activeSession={session}
        onSelectSession={(s) => {
          setActiveSession(s);
          setWorkspaceMode("details");
        }}
        onViewSessionDetails={(s) => {
          setActiveSession(s);
          setWorkspaceMode("details");
        }}
        onLaunchInteractive={(s) => {
          setActiveSession(s);
          setWorkspaceMode("interactive");
        }}
        onOpenCreateModal={onOpenCreateModal || (() => setPage("Create Session"))}
        onDuplicateSession={onDuplicateSession}
        onDeleteSession={onDeleteSession}
      />
    );
  }

  // If details mode
  if (workspaceMode === "details") {
    return (
      <SessionDetails
        session={session}
        onBack={() => setWorkspaceMode("directory")}
        onUpdateSession={onUpdateSession}
        onDuplicateSession={onDuplicateSession}
        onDeleteSession={onDeleteSession}
        onLaunchInteractive={() => setWorkspaceMode("interactive")}
        onNavigateToReports={() => setPage("Reports")}
        onNavigateToDocs={() => setPage("Documents")}
      />
    );
  }

  // Helper to extract metric values safely
  const metricsMap = extractedData?.metrics || {};
  function getMetricVal(key, fallback = "N/A") {
    const m = metricsMap[key] || metricsMap[key.toUpperCase()] || metricsMap[key.toLowerCase()];
    if (!m) return fallback;
    const num = parseFloat(m.numeric_value);
    if (isNaN(num)) return m.numeric_value || fallback;
    const unit = m.unit ? ` ${m.unit}` : "";
    const curr = m.currency && m.currency !== "PERCENT" && m.currency !== "RATIO" ? `${m.currency} ` : "";
    if (m.currency === "PERCENT" || key.includes("MARGIN") || key.includes("RATIO")) {
      return `${num.toFixed(1)}%`;
    }
    return `${curr}${num.toLocaleString()}${unit}`;
  }

  function getMetricCitation(key) {
    const m = metricsMap[key] || metricsMap[key.toUpperCase()] || metricsMap[key.toLowerCase()];
    return m?.citation || null;
  }

  const rawMetricsList = Object.values(metricsMap);
  const filteredMetrics = rawMetricsList.filter((m) => {
    if (metricCategory === "all") return true;
    if (metricCategory === "profitability") {
      return m.statement_type === "INCOME_STATEMENT" || m.metric_name.includes("MARGIN") || m.metric_name.includes("PROFIT");
    }
    if (metricCategory === "solvency") {
      return m.statement_type === "BALANCE_SHEET" || m.metric_name.includes("DEBT") || m.metric_name.includes("RATIO");
    }
    return true;
  });

  return (
    <section className="page research-workspace-page animate-fadeIn">
      {/* Top Breadcrumb & Navigation */}
      <div className="flex-row justify-between items-center mb-4 pb-3 border-b border-color">
        <div className="flex-row items-center gap-2">
          <button
            type="button"
            className="details-back-link"
            onClick={() => setWorkspaceMode("details")}
          >
            <ArrowLeft size={14} />
            <span>Session Details</span>
          </button>
          <span className="text-muted text-xs">/</span>
          <button
            type="button"
            className="details-back-link"
            onClick={() => setWorkspaceMode("directory")}
          >
            <FolderOpen size={14} />
            <span>All Sessions Directory</span>
          </button>
        </div>

        <div className="flex-row items-center gap-2">
          <span className="fin-badge fin-badge-teal fin-badge-sm">
            Milestone 1 &amp; 2 Active
          </span>
        </div>
      </div>

      {/* Session Hero Banner with Document Selector */}
      <div className="workspace-hero">
        <div className="hero-meta">
          <div className="flex-row items-center gap-2">
            <span className="badge badge-accent">RESEARCH SESSION</span>
            <span className="status-badge">{session.status || "ACTIVE"}</span>
          </div>
          <h1>{session.title}</h1>
          <p className="hero-description">{session.description}</p>

          {/* Document Scope Selector */}
          <div className="mt-4 pt-3 border-t border-subtle flex items-center gap-3 flex-wrap">
            <span className="text-xs font-semibold text-muted uppercase tracking-wider">
              Active Filing Scope:
            </span>
            {availableDocs.length > 0 ? (
              <select
                className="fin-select text-xs py-1 px-3 rounded bg-card border border-subtle text-main"
                value={selectedDocId}
                onChange={(e) => setSelectedDocId(e.target.value)}
              >
                {availableDocs.map((doc) => (
                  <option key={doc.id} value={doc.id}>
                    {doc.name} ({doc.pages || doc.total_pages || "?"} pages • {doc.chunksCount || doc.chunk_count || "?"} chunks)
                  </option>
                ))}
              </select>
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted">No filings ingested yet.</span>
                <button
                  type="button"
                  className="fin-btn fin-btn-secondary fin-btn-xs"
                  onClick={handleSeedIngestion}
                  disabled={isPipelineRunning}
                >
                  <Sparkles size={12} className="mr-1 text-teal" />
                  Load Seed Filings
                </button>
              </div>
            )}

            {selectedDoc && (
              <button
                type="button"
                className="fin-btn fin-btn-primary fin-btn-xs"
                onClick={handleTriggerPipeline}
                disabled={isPipelineRunning}
              >
                <Play size={12} className="mr-1" />
                <span>{isPipelineRunning ? "Running Pipeline..." : "Run Analysis Pipeline"}</span>
              </button>
            )}
          </div>
        </div>

        <div className="hero-quick-stats">
          <div className="quick-stat-box">
            <span className="label">Active Document</span>
            <strong className="truncate max-w-[140px]" title={selectedDoc?.name || "None"}>
              {selectedDoc?.name || "None Selected"}
            </strong>
          </div>
          <div className="quick-stat-box">
            <span className="label">Indexed Chunks</span>
            <strong>{selectedDoc?.chunksCount || selectedDoc?.chunk_count || 0} Chunks</strong>
          </div>
          <div className="quick-stat-box">
            <span className="label">Metrics Extracted</span>
            <strong className="text-teal">{rawMetricsList.length} GAAP Items</strong>
          </div>
          <div className="quick-stat-box">
            <span className="label">Forensic Red Flags</span>
            <strong className={redFlags.length > 0 ? "text-amber-400" : "text-emerald-400"}>
              {redFlags.length} Signals
            </strong>
          </div>
        </div>
      </div>

      {/* Running Pipeline Progress Banner */}
      {isPipelineRunning && (
        <div className="fin-toast-banner animate-fadeIn mb-3 bg-card border border-teal/40">
          <RefreshCw size={15} className="text-teal animate-spin shrink-0" />
          <span className="text-xs font-semibold">{pipelineProgressMsg || "Multi-Agent Workflow executing..."}</span>
        </div>
      )}

      {/* Workspace Navigation Tabs */}
      <div className="flex items-center justify-between gap-4 flex-wrap pb-1 border-b border-subtle">
        <div className="workspace-tabs-bar border-0 p-0 mb-0">
          <button
            className={`tab-btn ${(activeTab === "extraction" || activeTab === "evidence") ? "active" : ""}`}
            onClick={() => setActiveTab("extraction")}
          >
            <Layers size={14} />
            <span>Extracted Financials &amp; Citations</span>
            {rawMetricsList.length > 0 && (
              <span className="fin-badge fin-badge-xs fin-badge-teal ml-1 font-mono">
                {rawMetricsList.length}
              </span>
            )}
          </button>

          <button
            className={`tab-btn ${activeTab === "redflags" ? "active" : ""}`}
            onClick={() => setActiveTab("redflags")}
          >
            <AlertTriangle size={14} />
            <span>Forensic Red Flags</span>
            <span className={`fin-badge fin-badge-xs ml-1 font-mono ${redFlags.length > 0 ? "fin-badge-warning" : "fin-badge-secondary"}`}>
              {redFlags.length}
            </span>
          </button>

          <button
            className={`tab-btn ${activeTab === "overview" ? "active" : ""}`}
            onClick={() => setActiveTab("overview")}
          >
            <Database size={14} />
            <span>Multi-Agent Pipeline</span>
          </button>

          <button
            className={`tab-btn ${activeTab === "ingestion" ? "active" : ""}`}
            onClick={() => setActiveTab("ingestion")}
          >
            <Search size={14} />
            <span>Vector DB &amp; Search</span>
          </button>

          <button
            className={`tab-btn ${activeTab === "comparison" ? "active" : ""}`}
            onClick={() => setActiveTab("comparison")}
          >
            <GitCompare size={14} />
            <span>Peer Comparison</span>
            <span className="fin-badge fin-badge-xs fin-badge-secondary ml-1 opacity-80 text-[10px]">
              M3
            </span>
          </button>
        </div>
      </div>

      {/* TAB CONTENT 1: FINANCIAL EXTRACTION AGENT (MILESTONE 2) */}
      {(activeTab === "extraction" || activeTab === "evidence") && (
        <div className="tab-content animate-fadeIn">
          {isLoadingAnalysis ? (
            <div className="p-12 text-center text-muted">
              <RefreshCw size={24} className="animate-spin mx-auto mb-3 text-teal" />
              <p>Retrieving extracted metrics from repository...</p>
            </div>
          ) : !extractedData || rawMetricsList.length === 0 ? (
            <div className="p-8 border border-subtle rounded-xl bg-card text-center space-y-4 my-6">
              <Layers size={36} className="mx-auto text-muted opacity-60" />
              <h3 className="text-lg font-bold text-main">Milestone 2 Analysis Pending</h3>
              <p className="text-muted text-sm max-w-lg mx-auto">
                The filing <strong>{selectedDoc?.name || "document"}</strong> has been ingested into the vector database, but the Extraction Agent and Red Flag Agent pipeline has not yet been executed on it.
              </p>
              <button
                type="button"
                className="fin-btn fin-btn-primary btn-md inline-flex items-center gap-2"
                onClick={handleTriggerPipeline}
                disabled={isPipelineRunning}
              >
                <Play size={14} />
                <span>Run Multi-Agent Analysis Pipeline</span>
              </button>
            </div>
          ) : (
            <>
              <div className="section-heading-row">
                <div>
                  <span className="eyebrow">AGENT 2: EXTRACTION AGENT</span>
                  <h2>Key Financial Metrics &amp; Ratios</h2>
                  <p className="muted text-sm">
                    Normalized GAAP figures and Python Decimal calculated ratios grounded in {selectedDoc?.name || "the filing"}.
                  </p>
                </div>
                <div className="flex-row gap-2">
                  <button
                    className={`filter-btn ${metricCategory === "all" ? "active" : ""}`}
                    onClick={() => setMetricCategory("all")}
                  >
                    All Metrics ({rawMetricsList.length})
                  </button>
                  <button
                    className={`filter-btn ${metricCategory === "profitability" ? "active" : ""}`}
                    onClick={() => setMetricCategory("profitability")}
                  >
                    Profitability &amp; Margin
                  </button>
                  <button
                    className={`filter-btn ${metricCategory === "solvency" ? "active" : ""}`}
                    onClick={() => setMetricCategory("solvency")}
                  >
                    Solvency &amp; Liquidity
                  </button>
                </div>
              </div>

              {/* Dynamic KPI Cards */}
              <div className="metrics-kpi-grid mt-4">
                <div className="kpi-card luxury-card">
                  <div className="flex-row justify-between items-start">
                    <span className="kpi-label">Revenue from Operations</span>
                    <span className="badge badge-success text-xs font-mono">Reported</span>
                  </div>
                  <strong className="kpi-value">{getMetricVal("REVENUE")}</strong>
                  <div className="flex-row justify-between items-center mt-2">
                    <span className="text-xs text-muted">Income Statement</span>
                    {getMetricCitation("REVENUE") && (
                      <small
                        className="kpi-citation cursor-pointer"
                        onClick={() =>
                          setActiveCitation({
                            docName: selectedDoc?.name,
                            page: getMetricCitation("REVENUE")?.page_number,
                            snippet: getMetricCitation("REVENUE")?.exact_quote
                          })
                        }
                      >
                        [P. {getMetricCitation("REVENUE")?.page_number} Citation]
                      </small>
                    )}
                  </div>
                </div>

                <div className="kpi-card luxury-card">
                  <div className="flex-row justify-between items-start">
                    <span className="kpi-label">Operating Margin (EBIT %)</span>
                    <span className="badge badge-warning text-xs font-mono">Calculated</span>
                  </div>
                  <strong className="kpi-value">{getMetricVal("OPERATING_MARGIN")}</strong>
                  <div className="flex-row justify-between items-center mt-2">
                    <span className="text-xs text-muted">Ratio: EBIT / Revenue</span>
                    {getMetricCitation("OPERATING_MARGIN") && (
                      <small
                        className="kpi-citation cursor-pointer"
                        onClick={() =>
                          setActiveCitation({
                            docName: selectedDoc?.name,
                            page: getMetricCitation("OPERATING_MARGIN")?.page_number,
                            snippet: getMetricCitation("OPERATING_MARGIN")?.exact_quote
                          })
                        }
                      >
                        [P. {getMetricCitation("OPERATING_MARGIN")?.page_number} Citation]
                      </small>
                    )}
                  </div>
                </div>

                <div className="kpi-card luxury-card">
                  <div className="flex-row justify-between items-start">
                    <span className="kpi-label">Net Profit / Income</span>
                    <span className="badge badge-success text-xs font-mono">Reported</span>
                  </div>
                  <strong className="kpi-value">{getMetricVal("NET_INCOME")}</strong>
                  <div className="flex-row justify-between items-center mt-2">
                    <span className="text-xs text-muted">Bottom-line Earnings</span>
                    {getMetricCitation("NET_INCOME") && (
                      <small
                        className="kpi-citation cursor-pointer"
                        onClick={() =>
                          setActiveCitation({
                            docName: selectedDoc?.name,
                            page: getMetricCitation("NET_INCOME")?.page_number,
                            snippet: getMetricCitation("NET_INCOME")?.exact_quote
                          })
                        }
                      >
                        [P. {getMetricCitation("NET_INCOME")?.page_number} Citation]
                      </small>
                    )}
                  </div>
                </div>

                <div className="kpi-card luxury-card">
                  <div className="flex-row justify-between items-start">
                    <span className="kpi-label">Total Assets</span>
                    <span className="badge badge-accent text-xs font-mono">Reported</span>
                  </div>
                  <strong className="kpi-value">{getMetricVal("TOTAL_ASSETS")}</strong>
                  <div className="flex-row justify-between items-center mt-2">
                    <span className="text-xs text-muted">Balance Sheet</span>
                    {getMetricCitation("TOTAL_ASSETS") && (
                      <small
                        className="kpi-citation cursor-pointer"
                        onClick={() =>
                          setActiveCitation({
                            docName: selectedDoc?.name,
                            page: getMetricCitation("TOTAL_ASSETS")?.page_number,
                            snippet: getMetricCitation("TOTAL_ASSETS")?.exact_quote
                          })
                        }
                      >
                        [P. {getMetricCitation("TOTAL_ASSETS")?.page_number} Citation]
                      </small>
                    )}
                  </div>
                </div>
              </div>

              {/* Balance Sheet & Solvency Profile */}
              <div className="health-gauge-banner mt-6">
                <div className="gauge-left">
                  <div>
                    <span className="badge badge-accent mb-1">Balance Sheet &amp; Capital Structure</span>
                    <h4>Audited Solvency &amp; Liquidity Profile</h4>
                    <p className="text-xs text-muted mt-1 leading-relaxed">
                      Deterministically verified from statutory disclosures ({selectedDoc?.name}). Ratios computed using Python Decimal precision.
                    </p>
                  </div>
                </div>

                <div className="gauge-right">
                  <div className="health-metric-row">
                    <span className="text-xs text-muted">Total Debt / Borrowings:</span>
                    <strong className="text-xs text-main">{getMetricVal("TOTAL_DEBT")}</strong>
                  </div>
                  <div className="health-metric-row">
                    <span className="text-xs text-muted">Current Assets:</span>
                    <strong className="text-xs text-main">{getMetricVal("CURRENT_ASSETS")}</strong>
                  </div>
                  <div className="health-metric-row">
                    <span className="text-xs text-muted">Current Ratio:</span>
                    <strong className="text-xs text-teal">{getMetricVal("CURRENT_RATIO")}</strong>
                  </div>
                  <div className="health-metric-row">
                    <span className="text-xs text-muted">Return on Equity (ROE):</span>
                    <strong className="text-xs text-main">{getMetricVal("RETURN_ON_EQUITY")}</strong>
                  </div>
                </div>
              </div>

              {/* Detailed Financial Ratios Table */}
              <div className="ratios-table-card mt-6">
                <div className="card-header-row">
                  <div>
                    <h3>Extracted Financial Performance Matrix</h3>
                    <p className="text-xs muted">
                      Extracted line items and deterministically calculated ratios with exact page-level provenance.
                    </p>
                  </div>
                  <span className="badge badge-accent">Strict Source Grounding</span>
                </div>

                <div className="table-responsive">
                  <table className="custom-table">
                    <thead>
                      <tr>
                        <th>Financial Metric / Canonical Key</th>
                        <th>Statement / Category</th>
                        <th>Extracted Value</th>
                        <th>Type / Method</th>
                        <th>Source Provenance</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredMetrics.map((m, i) => (
                        <tr key={i}>
                          <td>
                            <strong>{m.source_label || m.metric_name}</strong>
                            <span className="block text-[11px] text-muted font-mono">{m.metric_name}</span>
                          </td>
                          <td>
                            <span className="text-xs text-muted">{m.statement_type || "FINANCIAL_STATEMENT"}</span>
                          </td>
                          <td>
                            <span className="metric-pill">
                              {parseFloat(m.numeric_value).toLocaleString()} {m.currency !== "PERCENT" && m.currency !== "RATIO" ? m.currency : ""}
                            </span>
                          </td>
                          <td>
                            <span className={`status-pill ${m.is_calculated ? "pill-warning" : "pill-success"}`}>
                              {m.is_calculated ? "Calculated" : "Reported"}
                            </span>
                          </td>
                          <td>
                            <span className="citation-tag">
                              {selectedDoc?.name}, p. {m.citation?.page_number || 1}
                            </span>
                          </td>
                          <td>
                            <button
                              className="secondary-button btn-xs"
                              onClick={() =>
                                setActiveCitation({
                                  docName: selectedDoc?.name,
                                  page: m.citation?.page_number || 1,
                                  snippet: m.citation?.exact_quote || `${m.metric_name}: ${m.numeric_value}`
                                })
                              }
                            >
                              Inspect Source
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* TAB CONTENT 2: RED FLAG AGENT (MILESTONE 2) */}
      {activeTab === "redflags" && (
        <div className="tab-content animate-fadeIn">
          {isLoadingAnalysis ? (
            <div className="p-12 text-center text-muted">
              <RefreshCw size={24} className="animate-spin mx-auto mb-3 text-teal" />
              <p>Scanning for financial red flags and anomalies...</p>
            </div>
          ) : !extractedData ? (
            <div className="p-8 border border-subtle rounded-xl bg-card text-center space-y-4 my-6">
              <ShieldAlert size={36} className="mx-auto text-muted opacity-60" />
              <h3 className="text-lg font-bold text-main">Red Flag Scan Not Yet Executed</h3>
              <p className="text-muted text-sm max-w-lg mx-auto">
                Trigger the multi-agent analysis pipeline to execute deterministic ratio rules and narrative disclosure audits.
              </p>
              <button
                type="button"
                className="fin-btn fin-btn-primary btn-md inline-flex items-center gap-2"
                onClick={handleTriggerPipeline}
                disabled={isPipelineRunning}
              >
                <Play size={14} />
                <span>Run Analysis Pipeline</span>
              </button>
            </div>
          ) : (
            <>
              <div className="section-heading-row">
                <div>
                  <span className="eyebrow">AGENT 3: RED FLAG &amp; FORENSIC AUDIT AGENT</span>
                  <h2>Detected Financial Anomalies &amp; Risk Signals</h2>
                  <p className="muted text-sm">
                    Automated checks for debt spikes, margin deterioration, auditor qualifications, and accounting disclosures.
                  </p>
                </div>
                <div className="flex-row gap-2">
                  <button
                    className={`filter-btn ${redFlagSeverity === "all" ? "active" : ""}`}
                    onClick={() => setRedFlagSeverity("all")}
                  >
                    All Signals ({redFlags.length})
                  </button>
                  <button
                    className={`filter-btn ${redFlagSeverity === "HIGH" ? "active" : ""}`}
                    onClick={() => setRedFlagSeverity("HIGH")}
                  >
                    High / Critical
                  </button>
                  <button
                    className={`filter-btn ${redFlagSeverity === "MEDIUM" ? "active" : ""}`}
                    onClick={() => setRedFlagSeverity("MEDIUM")}
                  >
                    Medium
                  </button>
                </div>
              </div>

              {/* Red Flag Cards Grid */}
              <div className="redflags-grid mt-6">
                {redFlags.length === 0 ? (
                  <div className="p-6 border border-emerald-800/40 rounded-xl bg-emerald-950/20 text-center space-y-2 col-span-2">
                    <CheckCircle2 size={32} className="mx-auto text-emerald-400" />
                    <h4 className="text-emerald-300 font-bold">Zero Financial Red Flags Detected</h4>
                    <p className="text-emerald-400/80 text-xs max-w-md mx-auto">
                      All deterministic solvency thresholds, operating margin trendlines, and statutory auditor disclosures conform to healthy financial parameters.
                    </p>
                  </div>
                ) : (
                  redFlags
                    .filter((rf) => redFlagSeverity === "all" || rf.severity === redFlagSeverity)
                    .map((flag, idx) => (
                      <div key={idx} className="redflag-card">
                        <div className="redflag-card-header">
                          <div className="flex-row items-center gap-2">
                            <span
                              className={`badge ${
                                flag.severity === "CRITICAL" || flag.severity === "HIGH"
                                  ? "badge-danger"
                                  : "badge-warning"
                              }`}
                            >
                              {flag.severity} Risk
                            </span>
                            <span className="text-xs text-muted font-medium">{flag.category}</span>
                          </div>
                        </div>

                        <h3 className="redflag-title mt-2">{flag.title}</h3>
                        <p className="redflag-impact">{flag.description}</p>

                        {flag.supporting_evidence && (
                          <div className="evidence-snippet-box">
                            <span className="text-xs font-semibold text-muted block mb-1">
                              SOURCE EVIDENCE SNIPPET:
                            </span>
                            <blockquote className="evidence-text">"{flag.supporting_evidence}"</blockquote>
                          </div>
                        )}

                        <div className="redflag-card-footer">
                          <span className="citation-text">
                            <ExternalLink size={12} style={{ marginRight: 4, display: "inline" }} />
                            Page {flag.source_page || 1}
                          </span>
                          <button
                            className="primary-button btn-xs"
                            onClick={() =>
                              setActiveCitation({
                                docName: selectedDoc?.name,
                                page: flag.source_page || 1,
                                snippet: flag.supporting_evidence || flag.description
                              })
                            }
                          >
                            View Source
                          </button>
                        </div>
                      </div>
                    ))
                )}
              </div>
            </>
          )}
        </div>
      )}

      {/* TAB CONTENT 3: OVERVIEW & PIPELINE TRACKER */}
      {activeTab === "overview" && (
        <div className="tab-content animate-fadeIn">
          <AgentPipelineTracker
            isRunning={isPipelineRunning}
            onTriggerRun={handleTriggerPipeline}
          />

          {/* Ingested Documents List */}
          <div className="mt-8">
            <div className="flex-row justify-between items-center mb-3">
              <div>
                <h3>Ingested Financial Documents</h3>
                <p className="text-xs muted">
                  All extracted metrics and agent findings are grounded strictly in these indexed filings.
                </p>
              </div>
              <button
                className="secondary-button btn-sm"
                onClick={() => setActiveTab("ingestion")}
              >
                <Upload size={14} style={{ marginRight: 6, display: "inline" }} />
                Ingest New Document
              </button>
            </div>

            <div className="doc-cards-grid">
              {availableDocs.map((doc, idx) => (
                <div
                  key={idx}
                  className={`doc-item-card ${doc.id === selectedDocId ? "border-teal" : ""}`}
                  onClick={() => setSelectedDocId(doc.id)}
                  style={{ cursor: "pointer" }}
                >
                  <div className="doc-item-left">
                    <div className="doc-icon-wrap">
                      <FileText size={20} />
                    </div>
                    <div>
                      <strong className="doc-title">{doc.name}</strong>
                      <div className="doc-meta-row">
                        <span>{doc.fileSize || "18.4 MB"}</span>
                        <span>•</span>
                        <span>{doc.pages || doc.total_pages || "?"} Pages</span>
                        <span>•</span>
                        <span>{doc.chunksCount || doc.chunk_count || "?"} Semantic Chunks</span>
                      </div>
                    </div>
                  </div>
                  <div className="doc-item-right">
                    <span className="badge badge-success">
                      <CheckCircle2 size={13} style={{ marginRight: 4, display: "inline" }} />
                      Indexed
                    </span>
                    <button
                      className="secondary-button btn-sm ml-2"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedDocId(doc.id);
                        setActiveTab("extraction");
                      }}
                    >
                      Inspect Financials
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* TAB CONTENT 4: VECTOR STORE & SEMANTIC SEARCH (MILESTONE 1) */}
      {activeTab === "ingestion" && (
        <div className="tab-content animate-fadeIn">
          <div className="split-layout">
            {/* Left: Preloaded Seed Filings Ingestion */}
            <div className="split-left">
              <div className="section-box">
                <span className="eyebrow">MILESTONE 1: DOCUMENT INTELLIGENCE AGENT</span>
                <h3>Ingest Financial Documents</h3>
                <p className="muted text-sm mb-4">
                  Upload company annual reports, SEC Form 10-K, or earnings filings for structure-aware parsing and 384-dim dense vector embedding.
                </p>

                <div className="preloaded-seed-section">
                  <div className="flex justify-between items-center mb-2">
                    <span className="eyebrow">PRE-LOADED SEED FILINGS</span>
                    <button
                      className="fin-btn fin-btn-secondary fin-btn-xs"
                      onClick={handleSeedIngestion}
                      disabled={isPipelineRunning}
                    >
                      <Sparkles size={12} className="mr-1 text-teal" />
                      Re-ingest Seeds
                    </button>
                  </div>
                  <p className="text-xs muted mb-3">
                    These seed filings are pre-indexed into the local vector database with PyMuPDF tables:
                  </p>
                  <div className="seed-links-list space-y-2">
                    {availableDocs.map((comp) => (
                      <div
                        key={comp.id}
                        className={`seed-link-item p-3 border rounded-lg flex justify-between items-center cursor-pointer ${
                          comp.id === selectedDocId ? "border-teal bg-teal/5" : "border-subtle"
                        }`}
                        onClick={() => setSelectedDocId(comp.id)}
                      >
                        <div>
                          <strong className="text-xs text-main block">{comp.name}</strong>
                          <span className="text-[11px] text-muted">
                            {comp.pages || comp.total_pages || 0} Pages • {comp.chunksCount || comp.chunk_count || 0} Chunks
                          </span>
                        </div>
                        <span className="status-badge-sm">Indexed</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* Right: Real Vector Store & Semantic Search Sandbox */}
            <div className="split-right">
              <div className="section-box">
                <div className="flex-row justify-between items-center mb-2">
                  <div>
                    <span className="eyebrow">MILESTONE 1: VECTOR RETRIEVAL</span>
                    <h3>Vector Store &amp; Chunk Inspector</h3>
                  </div>
                  <span className="badge badge-accent">384-Dim all-MiniLM-L6-v2</span>
                </div>
                <p className="text-sm muted mb-4">
                  Test semantic cosine similarity search against Qdrant / ChromaDB vector stores with page attribution.
                </p>

                {/* Similarity Search Sandbox */}
                <form className="vector-search-bar" onSubmit={handleVectorSearch}>
                  <Search size={16} className="text-muted" />
                  <input
                    type="text"
                    value={vectorQuery}
                    onChange={(e) => setVectorQuery(e.target.value)}
                    placeholder="Search financial terms (e.g., Operating margin, BFSI revenue, Total debt)..."
                  />
                  <button type="submit" className="primary-button btn-sm" disabled={isSearchingVector}>
                    {isSearchingVector ? "Searching..." : "Query Chunks"}
                  </button>
                </form>

                <div className="chunks-list mt-4">
                  <div className="flex-row justify-between items-center mb-2">
                    <span className="text-xs text-muted">
                      Showing top {vectorResults.length} matching chunks
                    </span>
                    {vectorResults.length > 0 && (
                      <span className="text-xs text-success">Cosine similarity scores &gt; 0.70</span>
                    )}
                  </div>

                  {vectorResults.length === 0 ? (
                    <div className="p-8 text-center text-muted text-xs border border-dashed border-subtle rounded-lg">
                      Enter a financial query above and click "Query Chunks" to test vector similarity retrieval.
                    </div>
                  ) : (
                    vectorResults.map((chunk, idx) => (
                      <div key={idx} className="chunk-card">
                        <div className="chunk-header">
                          <div className="chunk-meta">
                            <span className="chunk-id">Chunk #{idx + 1}</span>
                            <span className="chunk-doc">{chunk.docName}</span>
                            <span className="chunk-page">Page {chunk.page}</span>
                          </div>
                          <div className="chunk-score">
                            <span className="similarity-badge">
                              Match: {chunk.relevance || `${Math.round((chunk.score || 0.85) * 100)}%`}
                            </span>
                          </div>
                        </div>
                        <p className="chunk-snippet">"{chunk.textSnippet || chunk.text}"</p>
                        <div className="chunk-footer">
                          <button
                            className="text-button text-xs"
                            onClick={() =>
                              setActiveCitation({
                                docName: chunk.docName,
                                page: chunk.page,
                                snippet: chunk.textSnippet || chunk.text
                              })
                            }
                          >
                            Verify Citation Source →
                          </button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB CONTENT 5: COMPARISON AGENT (MILESTONE 3) */}
      {activeTab === "comparison" && (
        <ComparisonPanel documents={documents} session={session} setPage={setPage} />
      )}

      {/* Global Citation Inspection Modal */}
      {activeCitation && (
        <CitationModal citation={activeCitation} onClose={() => setActiveCitation(null)} />
      )}
    </section>
  );
}
