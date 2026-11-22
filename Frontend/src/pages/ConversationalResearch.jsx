import React, { useState, useEffect, useRef } from "react";
import {
  Bot,
  ShieldCheck,
  AlertTriangle,
  Trash2,
  FileText,
  X,
  RefreshCw,
  SlidersHorizontal,
  ChevronRight,
  FolderOpen
} from "lucide-react";
import ChatMessageItem from "../components/chat/ChatMessageItem";
import ContextSourcesPanel from "../components/chat/ContextSourcesPanel"; 
import ChatInputBar from "../components/chat/ChatInputBar";
import CitationDetailsModal from "../components/chat/CitationDetailsModal";
import DocumentViewer from "../components/DocumentViewer";
import {
  SUGGESTED_RESEARCH_QUESTIONS,
  getStoredChatHistory,
  saveStoredChatHistory,
  clearStoredChatHistory
} from "../data/researchChatData";
import { INITIAL_DOCUMENTS, getStoredDocuments } from "../data/documentData";
import api from "../services/api";

function mapCitation(citation, index = 0) {
  return {
    id: citation.id || `cite-${citation.document_id || "doc"}-${citation.page_number || 0}-${index}`,
    documentId: citation.document_id || null,
    docName: citation.document_name || citation.filename || "Financial Filing",
    company: citation.company || null,
    page: citation.page_number ?? null,
    section: citation.section || null,
    passage: citation.exact_quote || citation.quote || "",
    metricName: citation.metric_name || null,
    isCalculated: Boolean(citation.is_calculated)
  };
}

function mapAssistantAnswer(response) {
  const citations = (response.citations || []).map(mapCitation);
  const facts = [
    ...(response.direct_facts || []),
    ...(response.calculated_values || []),
    ...(response.analytical_conclusions || [])
  ];
  const unavailable = response.unavailable_information || [];

  return {
    id: response.message_id || `assistant-${Date.now()}`,
    role: "assistant",
    timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    conciseAnswer: response.answer || "No grounded answer was produced.",
    stepByStepExplanation: (response.steps || []).map((s) => ({
      step: s.step,
      title: s.title,
      detail: s.detail
    })),
    supportingEvidence: facts,
    unavailableInformation: unavailable,
    citations,
    sourceExcerpts: citations
      .filter((c) => c.passage)
      .slice(0, 8)
      .map((c) => ({
        docName: c.docName,
        documentId: c.documentId,
        page: c.page,
        section: c.section,
        snippet: c.passage
      }))
  };
}

function mapStoredMessage(message) {
  if (message.role === "user") {
    return {
      id: message.message_id,
      role: "user",
      timestamp: new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      content: message.content
    };
  }
  const metadata = message.metadata || {};
  return {
    id: message.message_id,
    role: "assistant",
    timestamp: new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    conciseAnswer: message.content,
    stepByStepExplanation: metadata.steps || [],
    supportingEvidence: [
      ...(metadata.direct_facts || []),
      ...(metadata.calculated_values || []),
      ...(metadata.analytical_conclusions || [])
    ],
    unavailableInformation: metadata.unavailable_information || [],
    citations: (message.citations || []).map(mapCitation),
    sourceExcerpts: (message.citations || [])
      .filter((c) => c.exact_quote)
      .slice(0, 8)
      .map((c) => ({
        docName: c.document_name,
        documentId: c.document_id,
        page: c.page_number,
        section: c.section,
        snippet: c.exact_quote
      }))
  };
}

export default function ConversationalResearch({
  documents: initialDocumentsProp,
  session,
  sessions = [],
  setActiveSession,
  setPage
}) {
  // Session determination
  const activeSession = session || sessions[0];
  const sessionId = activeSession?.id || "default";

  // Documents available in system library
  const [availableDocs, setAvailableDocs] = useState(() => {
    if (Array.isArray(initialDocumentsProp)) {
      return initialDocumentsProp;
    }
    return getStoredDocuments();
  });

  // Sync availableDocs if parent documents update
  useEffect(() => {
    if (Array.isArray(initialDocumentsProp)) {
      setAvailableDocs(initialDocumentsProp);
    }
  }, [initialDocumentsProp]);

  // Active documents in research scope for this session
  const [sessionScopeDocs, setSessionScopeDocs] = useState(() => {
    const relevant = availableDocs.filter((d) => {
      if (!activeSession?.companyIds || activeSession.companyIds.length === 0) return true;
      return activeSession.companyIds.includes(d.ticker);
    });
    return relevant.length > 0 ? relevant : availableDocs.slice(0, 4);
  });

  // Selected document IDs in active research scope
  const [selectedDocIds, setSelectedDocIds] = useState(() =>
    sessionScopeDocs.map((d) => d.id)
  );

  // Consolidated Right Panel State: isOpen and activeTab ('context' | 'sources' | 'citations')
  const [isPanelOpen, setIsPanelOpen] = useState(true);
  const [panelTab, setPanelTab] = useState("sources");

  // Chat message stream state
  const [messages, setMessages] = useState(() => getStoredChatHistory(sessionId));
  const [inputValue, setInputValue] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [typingStage, setTypingStage] = useState("");
  const [errorState, setErrorState] = useState(null);

  // Track previous session ID to cleanly handle session switching
  const prevSessionIdRef = useRef(sessionId);

  // Update scope documents and selected documents when session or availableDocs change
  useEffect(() => {
    const relevant = availableDocs.filter((d) => {
      if (!activeSession?.companyIds || activeSession.companyIds.length === 0) return true;
      return activeSession.companyIds.includes(d.ticker);
    });
    const updatedScope = relevant.length > 0 ? relevant : availableDocs.slice(0, 4);
    setSessionScopeDocs(updatedScope);
    setSelectedDocIds(updatedScope.map((d) => d.id));
  }, [activeSession?.id, availableDocs]);

  // Load persisted research-session context from the backend. Falls back to
  // the local cache only when the API is unreachable; never fabricates turns.
  useEffect(() => {
    let cancelled = false;
    prevSessionIdRef.current = sessionId;
    setErrorState(null);
    setIsTyping(false);
    setTypingStage("");

    const backendSessionId = activeSession?.id;
    if (!backendSessionId) {
      setMessages(getStoredChatHistory(sessionId));
      return undefined;
    }

    (async () => {
      try {
        const stored = await api.getResearchMessages(backendSessionId);
        if (cancelled) return;
        const mapped = Array.isArray(stored) ? stored.map(mapStoredMessage) : [];
        setMessages(mapped);
        const initialCite = mapped.find((m) => m.citations && m.citations.length > 0)?.citations?.[0];
        setActiveCitation(initialCite || null);
      } catch (err) {
        if (cancelled) return;
        setMessages(getStoredChatHistory(sessionId));
        if (err?.status && err.status !== 404) {
          setErrorState({
            title: "Research History Unavailable",
            message: err.message || "Could not load conversation history from the research backend."
          });
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [sessionId, activeSession?.id]);

  // Save messages to localStorage for current session
  useEffect(() => {
    if (prevSessionIdRef.current === sessionId) {
      saveStoredChatHistory(sessionId, messages);
    }
  }, [sessionId, messages]);

  // Citation modal & inspector state
  const [activeCitation, setActiveCitation] = useState(() => {
    const initialCite = messages.find((m) => m.citations && m.citations.length > 0)?.citations?.[0];
    return initialCite || null;
  });
  const [citationModalOpen, setCitationModalOpen] = useState(false);

  // Document Viewer inline/overlay state
  const [viewerDoc, setViewerDoc] = useState(null); // { doc: Object, page: number }

  // Auto-scroll ref
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping, errorState]);

  // Document Selection & Scope Handlers
  function handleToggleDocSelection(docId) {
    setSelectedDocIds((prev) =>
      prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId]
    );
  }

  function handleSelectAllDocs() {
    setSelectedDocIds(sessionScopeDocs.map((d) => d.id));
  }

  function handleDeselectAllDocs() {
    setSelectedDocIds([]);
  }

  // Handle User Sending a Message
  function handleSendMessage(e) {
    if (e) e.preventDefault();
    if (!inputValue.trim() || isTyping) return;

    if (selectedDocIds.length === 0) {
      setErrorState({
        title: "No Documents Selected",
        message: "Please select at least one source filing in the Context & Sources panel to ground your query."
      });
      return;
    }

    const queryText = inputValue.trim();
    setInputValue("");
    setErrorState(null);

    // 1. Add User Message
    const userMsg = {
      id: `user-${Date.now()}`,
      role: "user",
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      content: queryText
    };

    setMessages((prev) => [...prev, userMsg]);
    setIsTyping(true);

    // 2. Grounded multi-step research request to the Research Agent
    setTypingStage("Decomposing question & retrieving source passages...");

    (async () => {
      try {
        const response = await api.askResearch(activeSession?.id || null, {
          question: queryText,
          document_ids: selectedDocIds,
          top_k: 6
        });

        const assistantMsg = mapAssistantAnswer(response);
        setMessages((prev) => [...prev, assistantMsg]);
        setIsTyping(false);
        setTypingStage("");

        if (assistantMsg.citations && assistantMsg.citations.length > 0) {
          setActiveCitation(assistantMsg.citations[0]);
        }
      } catch (err) {
        setIsTyping(false);
        setTypingStage("");
        setErrorState({
          title: "Research Agent Error",
          message:
            err?.message ||
            "The Research Agent could not complete this query. No answer was generated, so no unsupported information is shown."
        });
      }
    })();
  }

  // Handle Clicking a Suggested Question (populates composer without auto-submitting)
  function handleSelectSuggestedQuestion(questionText) {
    setInputValue(questionText);
  }

  // Handle Citation Click: opens panel and navigates directly to citation details tab
  function handleCitationClick(citation) {
    setActiveCitation(citation);
    setIsPanelOpen(true);
    setPanelTab("citations");
  }

  // Handle Launch Document Viewer
  function handleViewDocument(docName, page, documentId = null) {
    const targetDoc =
      (documentId && availableDocs.find((d) => d.id === documentId || d.documentId === documentId)) ||
      availableDocs.find((d) => d.name === docName) ||
      sessionScopeDocs.find((d) => d.name === docName) ||
      availableDocs.find((d) => d.company === activeSession?.company) ||
      availableDocs[0];

    if (targetDoc) {
      setViewerDoc({
        doc: targetDoc,
        initialPage: page || 112
      });
    } else {
      setErrorState({
        title: "Document Unavailable",
        message: `Document "${docName}" is not loaded in current library.`
      });
    }
  }

  async function handleClearChat() {
    if (!window.confirm("Clear conversation history for this research session?")) return;
    setMessages([]);
    clearStoredChatHistory(sessionId);
    setErrorState(null);
    setActiveCitation(null);
    if (activeSession?.id) {
      try {
        await api.clearResearchMessages(activeSession.id);
      } catch (err) {
        setErrorState({
          title: "Could Not Clear Session Context",
          message: err?.message || "The local conversation was cleared, but the backend session context could not be cleared."
        });
      }
    }
  }

  // Collect all citations across current thread for quick reference
  const allCitations = messages
    .filter((m) => m.citations && Array.isArray(m.citations))
    .flatMap((m) => m.citations);

  return (
    <div className="fin-research-page animate-fadeIn">
      {/* =========================================================================
          COMPACT TOOLBAR: Research Session, Grounding Scope & Context Toggle
         ========================================================================= */}
      <div className="fin-research-toolbar">
        <div className="fin-toolbar-left">
          {/* Research Session Selector */}
          <div className="fin-session-picker">
            <span className="fin-toolbar-label">Session:</span>
            <select
              aria-label="Active research session"
              className="fin-toolbar-select"
              value={activeSession?.id || (sessions[0] && sessions[0].id) || ""}
              onChange={(e) => {
                const s = sessions.find((item) => item.id === e.target.value);
                if (s && setActiveSession) {
                  setActiveSession(s);
                }
              }}
            >
              {sessions.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.title} ({s.company || "General"})
                </option>
              ))}
            </select>
          </div>

          {/* Factual Scope Indicator */}
          <div className="fin-scope-pill" title={`${selectedDocIds.length} filings active in research scope`}>
            <ShieldCheck size={13} className="text-teal" />
            <span>
              {selectedDocIds.length} {selectedDocIds.length === 1 ? "source" : "sources"} active
            </span>
          </div>
        </div>

        <div className="fin-toolbar-right">
          {/* Toggle Context & Sources Panel */}
          <button
            type="button"
            className={`fin-btn fin-btn-xs fin-toolbar-panel-btn ${
              isPanelOpen ? "active" : ""
            }`}
            onClick={() => setIsPanelOpen(!isPanelOpen)}
            title={isPanelOpen ? "Hide Context & Sources panel" : "Show Context & Sources panel"}
            aria-expanded={isPanelOpen}
          >
            <SlidersHorizontal size={13} className="text-teal" />
            <span className="hidden sm:inline">Context & Sources</span>
            <span className="fin-badge fin-badge-xs fin-badge-teal font-mono">
              {selectedDocIds.length}
            </span>
          </button>

          {/* Minimal Action: Clear Chat */}
          {messages.length > 0 && (
            <button
              type="button"
              className="fin-btn fin-btn-secondary fin-btn-xs text-muted hover:text-danger hover:border-danger/40 transition-colors"
              onClick={handleClearChat}
              title="Clear conversation history"
            >
              <Trash2 size={13} />
              <span className="hidden md:inline ml-1">Clear</span>
            </button>
          )}
        </div>
      </div>

      {/* =========================================================================
          WORKSPACE: CONVERSATION (PRIMARY) + COLLAPSIBLE CONTEXT & SOURCES PANEL
         ========================================================================= */}
      <div className={`fin-research-workspace ${!isPanelOpen ? "panel-collapsed" : ""}`}>
        {/* Main Conversation Column */}
        <main className="fin-conversation-column" role="region" aria-label="Conversation area">
          <div className="fin-conversation-stream">
            <div className="fin-messages-max-container">
              {/* Empty State */}
              {messages.length === 0 && (
                <div className="fin-chat-empty-state animate-fadeIn">
                  {selectedDocIds.length === 0 ? (
                    <div className="fin-empty-no-sources text-center py-8 px-4">
                      <div className="fin-empty-icon-box mb-3 text-warning">
                        <AlertTriangle size={24} />
                      </div>
                      <h2 className="text-base font-semibold text-main">
                        No financial documents selected
                      </h2>
                      <p className="text-xs text-muted max-w-md mx-auto mt-1 leading-relaxed">
                        Select indexed filings in the Sources panel or visit the Document Library to enable grounded financial research.
                      </p>
                      <div className="flex items-center justify-center gap-2 mt-4">
                        <button
                          type="button"
                          className="fin-btn fin-btn-primary fin-btn-xs"
                          onClick={() => {
                            setIsPanelOpen(true);
                            setPanelTab("sources");
                          }}
                        >
                          <FileText size={13} className="mr-1" />
                          <span>Select Filings</span>
                        </button>
                        {setPage && (
                          <button
                            type="button"
                            className="fin-btn fin-btn-secondary fin-btn-xs"
                            onClick={() => setPage("Documents")}
                          >
                            <FolderOpen size={13} className="mr-1" />
                            <span>Document Library</span>
                          </button>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div className="fin-empty-inquiry-box py-6">
                      <div className="text-center mb-5">
                        <h2 className="text-base sm:text-lg font-semibold text-main">
                          What would you like to investigate?
                        </h2>
                        <p className="text-xs text-muted mt-1 max-w-md mx-auto leading-relaxed">
                          Select a suggested research question below or type your inquiry to retrieve evidence-backed disclosures from active filings.
                        </p>
                      </div>

                      <div className="fin-empty-suggestions-list">
                        {SUGGESTED_RESEARCH_QUESTIONS.map((sq) => (
                          <button
                            key={sq.id}
                            type="button"
                            className="fin-empty-suggestion-row"
                            onClick={() => handleSelectSuggestedQuestion(sq.question)}
                          >
                            <span className="fin-suggestion-text">{sq.question}</span>
                            <ChevronRight size={14} className="fin-suggestion-arrow shrink-0 text-muted" />
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Render Chat Messages */}
              {messages.map((msg) => (
                <ChatMessageItem
                  key={msg.id}
                  message={msg}
                  onCitationClick={handleCitationClick}
                  onViewDocument={handleViewDocument}
                />
              ))}

              {/* Error State Banner */}
              {errorState && (
                <div className="fin-chat-error-card animate-fadeIn">
                  <div className="flex items-center gap-2">
                    <AlertTriangle size={16} className="text-danger shrink-0" />
                    <strong className="text-xs font-semibold text-danger">
                      {errorState.title || "Research Query Error"}
                    </strong>
                  </div>
                  <p className="text-xs text-muted mt-1 leading-relaxed">
                    {errorState.message}
                  </p>
                  <div className="mt-3 flex items-center gap-2">
                    <button
                      type="button"
                      className="fin-btn fin-btn-secondary fin-btn-xs"
                      onClick={() => setErrorState(null)}
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              )}

              {/* Factual Typing / Retrieval Indicator */}
              {isTyping && (
                <div className="fin-chat-typing-indicator-row animate-fadeIn">
                  <div className="typing-avatar">
                    <Bot size={15} className="text-teal" />
                  </div>
                  <div className="typing-bubble">
                    <div className="typing-dots-wave">
                      <span className="dot dot-1" />
                      <span className="dot dot-2" />
                      <span className="dot dot-3" />
                    </div>
                    <span className="typing-stage-text">{typingStage}</span>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          </div>

          {/* Bottom Message Composer (Centered and Anchored) */}
          <div className="fin-composer-anchor">
            <div className="fin-messages-max-container">
              <ChatInputBar
                inputValue={inputValue}
                onInputChange={setInputValue}
                onSubmit={handleSendMessage}
                isLoading={isTyping}
                selectedDocCount={selectedDocIds.length}
                onOpenSources={() => {
                  setIsPanelOpen(true);
                  setPanelTab("sources");
                }}
              />
            </div>
          </div>
        </main>

        {/* =========================================================================
            CONSOLIDATED CONTEXT & SOURCES PANEL (COLLAPSIBLE)
           ========================================================================= */}
        <ContextSourcesPanel
          isOpen={isPanelOpen}
          onClose={() => setIsPanelOpen(false)}
          activeTab={panelTab}
          onTabChange={setPanelTab}
          activeSession={activeSession}
          sessions={sessions}
          onSelectSession={setActiveSession}
          availableDocuments={sessionScopeDocs}
          selectedDocIds={selectedDocIds}
          onToggleDocSelection={handleToggleDocSelection}
          onSelectAllDocs={handleSelectAllDocs}
          onDeselectAllDocs={handleDeselectAllDocs}
          onOpenDocumentLibrary={() => setPage && setPage("Documents")}
          onViewDocument={handleViewDocument}
          activeCitation={activeCitation}
          allCitations={allCitations}
          onCitationClick={handleCitationClick}
        />
      </div>

      {/* Citation Details Modal (Secondary popup if triggered from inline document viewer) */}
      {citationModalOpen && activeCitation && (
        <CitationDetailsModal
          citation={activeCitation}
          onClose={() => setCitationModalOpen(false)}
          onViewDocument={handleViewDocument}
        />
      )}

      {/* Full-Screen Document Viewer Overlay when View Document is triggered */}
      {viewerDoc && (
        <div className="fin-modal-overlay" onClick={() => setViewerDoc(null)}>
          <div className="fin-doc-viewer-modal" onClick={(e) => e.stopPropagation()}>
            <div className="viewer-modal-header">
              <div className="flex items-center gap-2">
                <FileText size={18} className="text-teal" />
                <div>
                  <h3 className="text-sm font-bold text-main">
                    Filing Viewer: {viewerDoc.doc.name}
                  </h3>
                  <span className="text-xs text-muted">
                    Navigated to cited Page {viewerDoc.initialPage}
                  </span>
                </div>
              </div>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setViewerDoc(null)}
                aria-label="Close viewer"
              >
                <X size={18} />
              </button>
            </div>

            <div className="viewer-modal-body">
              <DocumentViewer
                document={viewerDoc.doc}
                initialPage={viewerDoc.initialPage}
                onCitationClick={(cite) => {
                  setActiveCitation(cite);
                  setIsPanelOpen(true);
                  setPanelTab("citations");
                }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
