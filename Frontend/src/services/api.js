/**
 * FinResearch AI - Centralized Production API Client
 * Strictly connects to FastAPI backend at /api (proxied to http://localhost:8000).
 * Never fabricates mock analysis, fake uploads, simulated agent results, or synthetic metadata.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

export class ApiError extends Error {
  constructor(message, status = 500, detail = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

let isBackendOnline = false;
let lastKnownHealth = null;

export function getBackendStatus() {
  return isBackendOnline ? "live" : "offline";
}

export function getLastKnownHealth() {
  return lastKnownHealth;
}

export function formatFileSize(bytes) {
  if (bytes === null || bytes === undefined) return null;
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + (sizes[i] || "B");
}

async function request(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const timeoutMs = options.timeout || (endpoint.includes("/upload") || endpoint.includes("/process") ? 60000 : 20000);
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  const headers = {
    Accept: "application/json",
    ...(options.headers || {})
  };

  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  let response;
  try {
    response = await fetch(url, {
      ...options,
      headers,
      signal: options.signal || controller.signal
    });
  } catch (netErr) {
    clearTimeout(timeoutId);
    if (netErr.name === "AbortError") {
      throw new ApiError(
        `Request to ${endpoint} timed out after ${timeoutMs / 1000}s.`,
        408,
        netErr
      );
    }
    isBackendOnline = false;
    throw new ApiError(
      `Cannot connect to FastAPI backend at ${url}. Please verify that the backend server is running on port 8000.`,
      0,
      netErr
    );
  } finally {
    clearTimeout(timeoutId);
  }

  let responseData = null;
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      responseData = await response.json();
    } catch {
      responseData = null;
    }
  } else {
    try {
      responseData = await response.text();
    } catch {
      responseData = null;
    }
  }

  if (!response.ok) {
    isBackendOnline = true; // Server is reachable but returned an HTTP error code
    let errorDetail = responseData?.detail || responseData?.message || response.statusText;
    if (Array.isArray(errorDetail)) {
      errorDetail = errorDetail.map((e) => `${e.loc ? e.loc.join(".") : "field"}: ${e.msg}`).join("; ");
    } else if (typeof errorDetail !== "string") {
      errorDetail = JSON.stringify(errorDetail);
    }
    throw new ApiError(
      errorDetail,
      response.status,
      responseData
    );
  }

  isBackendOnline = true;
  return responseData;
}

export function adaptDocument(doc) {
  if (!doc) return null;
  const meta = doc.metadata || {};

  // Compute actual file size or null (never fabricate "18.4 MB")
  const bytes = meta.file_size_bytes ?? doc.fileSizeBytes ?? null;
  let fileSize = meta.file_size_formatted || doc.fileSize || null;
  if (!fileSize && bytes !== null && bytes !== undefined) {
    fileSize = formatFileSize(bytes);
  }

  // Compute actual upload date or null (never fabricate "Recent")
  let uploadDate = null;
  if (doc.created_at) {
    try {
      uploadDate = new Date(doc.created_at).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric"
      });
    } catch {
      uploadDate = null;
    }
  } else if (doc.uploadDate && doc.uploadDate !== "Recent") {
    uploadDate = doc.uploadDate;
  }

  const uploadedTimestamp = doc.created_at || (doc.uploadedTimestamp && !doc.uploadedTimestamp.includes("2024-05-24") ? doc.uploadedTimestamp : null);

  // Compute actual checksum or null (never fabricate "sha256:verified")
  let checksum = null;
  if (doc.sha256) {
    checksum = `sha256:${doc.sha256.substring(0, 16)}...`;
  } else if (doc.checksum && doc.checksum !== "sha256:verified") {
    checksum = doc.checksum;
  }

  // Dynamic embedding info from document metadata or live health check (never fabricate static string)
  let embeddingModel = meta.embedding_model || doc.embeddingModel || null;
  const embeddingDim = meta.embedding_dimension || lastKnownHealth?.embedding_engine?.dimension || null;
  if (!embeddingModel && lastKnownHealth?.embedding_engine?.model) {
    embeddingModel = lastKnownHealth.embedding_engine.model;
  }
  if (embeddingModel && embeddingDim && !embeddingModel.includes("-dim")) {
    embeddingModel = `${embeddingModel} (${embeddingDim}-dim)`;
  }

  // Actual OCR engine or null (never fabricate "PyMuPDF High-Fidelity Table Extraction")
  const ocrEngine = meta.ocr_engine || doc.ocrEngine || null;

  // Actual workspace ID or null (never fabricate "default-workspace")
  const workspaceId = doc.workspace_id || doc.workspaceId || null;

  return {
    id: doc.document_id || doc.id,
    documentId: doc.document_id || doc.id,
    name: doc.filename || doc.name || "Untitled Document",
    company: meta.company_name || doc.company || (doc.filename ? doc.filename.replace(/\.pdf$/i, "").replace(/[-_]/g, " ") : "Unknown Entity"),
    ticker: meta.ticker || doc.ticker || "",
    docType: meta.doc_type || doc.docType || "Financial Filing",
    fileSize,
    fileSizeBytes: bytes,
    uploadDate,
    uploadedTimestamp,
    status: doc.indexed || doc.status === "Ready" ? "Ready" : (doc.status || "Uploaded"),
    isSeed: Boolean(meta.is_seed || doc.isSeed),
    pages: doc.total_pages || doc.pages || 0,
    chunksCount: doc.chunk_count || doc.chunksCount || 0,
    embeddingModel,
    ocrEngine,
    checksum,
    workspaceId,
    metadata: meta
  };
}

export function adaptSearchResult(item) {
  if (!item) return null;
  const meta = item.metadata || {};

  // Real distance and score (never fabricate 0.15)
  const distance = typeof item.distance === "number" ? item.distance : null;
  let score = null;
  if (typeof item.score === "number") {
    score = item.score;
  } else if (distance !== null) {
    score = Math.max(0, 1 - distance);
  }

  // Real page number (never fabricate 1)
  const page = meta.page_number ?? item.page ?? null;

  // Real relevance string (never fabricate percentage)
  const relevance = score !== null ? `${Math.round(score * 100)}% match` : null;

  // Real document ID and file name
  const documentId = meta.document_id || item.documentId || null;
  const docName = meta.filename || item.docName || null;

  return {
    id: item.chunk_id || item.id,
    chunkId: item.chunk_id || item.id,
    documentId,
    docName,
    page,
    text: item.text || item.textSnippet || "",
    textSnippet: item.text || item.textSnippet || "",
    distance,
    score,
    hasTable: Boolean(meta.is_table || meta.has_table || item.hasTable),
    tableMarkdown: meta.table_markdown || item.tableMarkdown || null,
    relevance,
    section: meta.section || null,
    tokenCount: meta.token_count || null,
    metadata: meta
  };
}

export const api = {
  adaptDocument,
  adaptSearchResult,

  async getHealth() {
    try {
      const res = await request("/health", { method: "GET", timeout: 8000 });
      isBackendOnline = true;
      lastKnownHealth = res;
      const isHealthy = res.status === "healthy";
      return {
        online: true,
        reachable: true,
        healthy: isHealthy,
        degraded: res.status === "degraded",
        ...res,
        database_provider: res.database?.provider || null,
        storage_healthy: res.storage?.healthy ?? null,
        vector_store_healthy: res.vector_store?.healthy ?? null,
        storage: res.storage || null,
        vector_store: res.vector_store || null,
        database: res.database || null,
        embedding_engine: res.embedding_engine || null,
        llm_engine: res.llm_engine || null
      };
    } catch (err) {
      if (err.status === 0) {
        // Backend completely unreachable (server offline or network issue)
        isBackendOnline = false;
        return {
          online: false,
          reachable: false,
          healthy: false,
          degraded: false,
          status: "unreachable",
          message: err.message || "Cannot connect to backend server.",
          database: null,
          storage: null,
          vector_store: null,
          embedding_engine: null,
          llm_engine: null
        };
      }
      // Backend is reachable, but returned HTTP error (e.g. 500 or 503)
      isBackendOnline = true;
      return {
        online: true,
        reachable: true,
        healthy: false,
        degraded: true,
        status: "degraded",
        httpStatus: err.status,
        message: err.message || `Backend returned HTTP ${err.status}`,
        database: err.detail?.database || null,
        storage: err.detail?.storage || null,
        vector_store: err.detail?.vector_store || null,
        embedding_engine: err.detail?.embedding_engine || null,
        llm_engine: err.detail?.llm_engine || null
      };
    }
  },

  async listWorkspaces() {
    const res = await request("/workspaces", { method: "GET" });
    return res || [];
  },

  async getWorkspace(workspaceId) {
    return await request(`/workspaces/${encodeURIComponent(workspaceId)}`, { method: "GET" });
  },

  async createWorkspace(payload) {
    return await request("/workspaces", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },

  async listWorkspaceSessions(workspaceId) {
    return await request(`/workspaces/${encodeURIComponent(workspaceId)}/sessions`, { method: "GET" });
  },

  async createSession(workspaceId, payload) {
    return await request(`/workspaces/${encodeURIComponent(workspaceId)}/sessions`, {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },

  async getSession(sessionId) {
    return await request(`/sessions/${encodeURIComponent(sessionId)}`, { method: "GET" });
  },

  async listDocuments(workspaceId = null) {
    const query = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
    const docs = await request(`/documents${query}`, { method: "GET" });
    return (docs || []).map(adaptDocument);
  },

  async getDocument(documentId) {
    const doc = await request(`/documents/${encodeURIComponent(documentId)}`, { method: "GET" });
    return adaptDocument(doc);
  },

  async uploadDocument(file, workspaceId = null, sessionId = null) {
    const formData = new FormData();
    formData.append("file", file);
    const params = new URLSearchParams();
    if (workspaceId) params.append("workspace_id", workspaceId);
    if (sessionId) params.append("session_id", sessionId);

    const queryStr = params.toString() ? `?${params.toString()}` : "";
    return await request(`/documents/upload${queryStr}`, {
      method: "POST",
      body: formData,
      timeout: 120000
    });
  },

  async seedDocuments() {
    return await request("/documents/seed", { method: "POST", timeout: 180000 });
  },

  async search({ query, top_k = 5, document_id = null, session_id = null, filter_tables_only = false }) {
    const payload = {
      query,
      top_k,
      document_id: document_id || undefined,
      session_id: session_id || undefined,
      filter_tables_only
    };
    const res = await request("/search", {
      method: "POST",
      body: JSON.stringify(payload)
    });
    return {
      query: res.query,
      resultCount: res.result_count,
      retrieverUsed: res.retriever_used,
      results: (res.results || []).map(adaptSearchResult)
    };
  },

  async processDocument({ document_id, filename, workspace_id, session_id }) {
    return await request("/documents/process", {
      method: "POST",
      body: JSON.stringify({ document_id, filename, workspace_id, session_id }),
      timeout: 180000
    });
  },

  async getDocumentStatus(documentId) {
    return await request(`/documents/${encodeURIComponent(documentId)}/status`, { method: "GET" });
  },

  async getExtractedFinancials(documentId) {
    return await request(`/documents/${encodeURIComponent(documentId)}/extraction`, { method: "GET" });
  },

  async getDocumentRedFlags(documentId) {
    return await request(`/documents/${encodeURIComponent(documentId)}/red-flags`, { method: "GET" });
  },

  async askResearch(sessionId, { question, document_ids = null, top_k = 6 }) {
    const endpoint = sessionId
      ? `/research/sessions/${encodeURIComponent(sessionId)}/query`
      : "/research/query";
    return await request(endpoint, {
      method: "POST",
      body: JSON.stringify({ question, document_ids, top_k }),
      timeout: 120000
    });
  },

  async getResearchMessages(sessionId) {
    return await request(`/research/sessions/${encodeURIComponent(sessionId)}/messages`, { method: "GET" });
  },

  async clearResearchMessages(sessionId) {
    return await request(`/research/sessions/${encodeURIComponent(sessionId)}/messages`, { method: "DELETE" });
  },

  async compareCompanies({ document_ids, metrics = null }) {
    return await request("/comparison", {
      method: "POST",
      body: JSON.stringify({ document_ids, metrics }),
      timeout: 120000
    });
  },

  async generateReport(documentId) {
    return await request("/reports/generate", {
      method: "POST",
      body: JSON.stringify({ document_id: documentId }),
      timeout: 120000
    });
  },

  async getWorkflowRunStatus(runId) {
    return await request(`/workflows/${encodeURIComponent(runId)}/status`, { method: "GET" });
  },

  getDocumentFileUrl(documentId) {
    return `${API_BASE}/documents/${encodeURIComponent(documentId)}/file`;
  },

  async deleteDocument(documentId) {
    return await request(`/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" });
  }
};

export default api;
