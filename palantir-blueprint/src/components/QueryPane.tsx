import { useState } from "react";
import {
  Button,
  Callout,
  Card,
  Classes,
  Divider,
  Elevation,
  Icon,
  InputGroup,
  Intent,
  NonIdealState,
  Pre,
  Tab,
  Tabs,
  Tag,
} from "@blueprintjs/core";
import KnowledgeGraph from "./KnowledgeGraph";
import { useQueryPoll } from "../lib/useQueryPoll";
import type { TrialResult, ProvenanceSource } from "../lib/adapters";

// ─── Types ────────────────────────────────────────────────────



const FILTER_OPTIONS = {
  phase:    ["Phase 2", "Phase 3", "N/A"],
  status:   ["Recruiting", "Active, not recruiting", "Completed"],
  strategy: ["BM25 + Dense", "Dense", "BM25"],
};

// ─── Helpers ──────────────────────────────────────────────────

function scoreIntent(score: number): Intent {
  if (score >= 0.9) return Intent.SUCCESS;
  if (score >= 0.8) return Intent.WARNING;
  return Intent.DANGER;
}

function enrollmentIntent(status: string): Intent {
  if (status === "Recruiting") return Intent.SUCCESS;
  if (status === "Completed")  return Intent.NONE;
  return Intent.WARNING;
}

function confHighlightStyle(conf: number): React.CSSProperties {
  if (conf >= 0.9) return { background: "rgba(42,161,152,0.14)",  borderBottom: "1px solid rgba(42,161,152,0.5)",  paddingBottom: 1 };
  if (conf >= 0.8) return { background: "rgba(181,137,0,0.13)",   borderBottom: "1px solid rgba(181,137,0,0.45)",  paddingBottom: 1 };
  return              { background: "rgba(203,75,22,0.10)",    borderBottom: "1px solid rgba(203,75,22,0.40)",  paddingBottom: 1 };
}

// ─── Sub-components ───────────────────────────────────────────

function SkeletonCard() {
  return (
    <Card elevation={Elevation.ONE} style={{ padding: "10px 14px" }}>
      <div style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "center" }}>
        <div className={Classes.SKELETON} style={{ width: 90, height: 14, borderRadius: 2 }} />
        <div className={Classes.SKELETON} style={{ width: 220, height: 14, borderRadius: 2 }} />
        <div className={Classes.SKELETON} style={{ marginLeft: "auto", width: 36, height: 14, borderRadius: 2 }} />
      </div>
      <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
        <div className={Classes.SKELETON} style={{ width: 60, height: 12, borderRadius: 2 }} />
        <div className={Classes.SKELETON} style={{ width: 140, height: 12, borderRadius: 2 }} />
        <div className={Classes.SKELETON} style={{ width: 50, height: 12, borderRadius: 2 }} />
      </div>
      <div className={Classes.SKELETON} style={{ width: "100%", height: 12, marginBottom: 4, borderRadius: 2 }} />
      <div className={Classes.SKELETON} style={{ width: "80%", height: 12, borderRadius: 2 }} />
    </Card>
  );
}

function ProvenanceChunk({ prov, clinicianMode }: { prov: ProvenanceSource; clinicianMode: boolean }) {
  const borderColor = prov.conf >= 0.9 ? "rgba(106,158,196,0.6)" : prov.conf >= 0.8 ? "rgba(196,130,90,0.55)" : "rgba(201,123,110,0.5)";
  const metaFields = clinicianMode
    ? ([["SOURCE", prov.source], ["PAGE", prov.page]] as [string, string][])
    : ([["SOURCE", prov.source], ["BYTES", prov.byteRange], ["PAGE", prov.page], ["CONF", prov.conf.toFixed(2)]] as [string, string][]);
  return (
    <div
      style={{
        padding: "10px 12px",
        background: "var(--surface-2)",
        border: "1px solid var(--border)",
        borderLeft: `2px solid ${borderColor}`,
        borderRadius: 2,
      }}
    >
      <div style={{ display: "flex", gap: 14, marginBottom: 8, flexWrap: "wrap" }}>
        {metaFields.map(([label, val]) => (
          <div key={label}>
            <div className="section-label" style={{ marginBottom: 1 }}>{label}</div>
            <div className="data-value" style={{ fontSize: 11 }}>{val}</div>
          </div>
        ))}
      </div>
      <Pre style={{ margin: 0, fontSize: 11, lineHeight: 1.75, whiteSpace: "pre-wrap" }}>
        {prov.preText}
        {prov.spans.map((s, i) => (
          <span key={i}>
            <span style={confHighlightStyle(s.highlight.conf)}>{s.highlight.text}</span>
            {s.after}
          </span>
        ))}
      </Pre>
      <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
        {!clinicianMode && <Tag minimal intent={scoreIntent(prov.conf)}>conf {prov.conf.toFixed(2)}</Tag>}
        <Tag minimal>{(prov.source.split(".").pop() ?? "file").toUpperCase()}</Tag>
        <Tag minimal intent={prov.conf >= 0.9 ? Intent.PRIMARY : prov.conf >= 0.8 ? Intent.WARNING : Intent.DANGER}>
          {prov.conf >= 0.9 ? "high confidence" : prov.conf >= 0.8 ? "medium confidence" : "low confidence"}
        </Tag>
      </div>
    </div>
  );
}

function ResultCard({
  result,
  expanded,
  highlighted,
  clinicianMode,
  onToggle,
}: {
  result: TrialResult;
  expanded: boolean;
  highlighted: boolean;
  clinicianMode: boolean;
  onToggle: () => void;
}) {
  return (
    <Card
      elevation={expanded ? Elevation.TWO : Elevation.ONE}
      style={{
        padding: "10px 14px",
        outline: highlighted ? "1px solid rgba(42,161,152,0.55)" : "none",
        transition: "outline 0.15s",
      }}
    >
      {/* Header — clickable to expand */}
      <div
        style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8, marginBottom: 6, cursor: "pointer" }}
        onClick={onToggle}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4, flexWrap: "wrap" }}>
            <Tag minimal intent={Intent.PRIMARY} style={{ fontFamily: "var(--text-mono)", fontSize: 10 }}>
              {result.nct}
            </Tag>
            <span style={{ fontSize: 12, fontWeight: 500, color: "var(--text-primary)" }}>{result.title}</span>
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <Tag minimal>{result.phase}</Tag>
            <Tag minimal intent={enrollmentIntent(result.enrollmentStatus)}>{result.enrollmentStatus}</Tag>
            <span style={{ fontFamily: "var(--text-mono)", fontSize: 10, color: "var(--text-dim)" }}>{result.sponsor}</span>
          </div>
        </div>
        <div style={{ display: "flex", gap: 5, alignItems: "center", flexShrink: 0 }}>
          {!clinicianMode && <Tag minimal>{result.strategy}</Tag>}
          <Tag minimal intent={scoreIntent(result.matchScore)}>{result.matchScore.toFixed(2)}</Tag>
          <Icon icon={expanded ? "chevron-up" : "chevron-down"} size={12} color="var(--text-dim)" />
        </div>
      </div>

      {/* Matched criteria */}
      <div style={{ display: "flex", gap: 5, marginBottom: 7, flexWrap: "wrap", alignItems: "center" }}>
        <span style={{ fontFamily: "var(--text-mono)", fontSize: 9, color: "var(--text-dim)" }}>MATCHED:</span>
        {result.matchedCriteria.map((c) => (
          <Tag key={c} minimal intent={Intent.PRIMARY} style={{ fontSize: 10 }}>{c}</Tag>
        ))}
      </div>

      {/* Snippet */}
      <p style={{ margin: 0, fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.6 }}>{result.snippet}</p>
      <div style={{ marginTop: 5, fontFamily: "var(--text-mono)", fontSize: 10, color: "var(--text-dim)" }}>
        {result.source}
        {!clinicianMode && ` · ${result.location}`}
      </div>

      {/* Inline provenance */}
      {expanded && (
        <div style={{ marginTop: 12 }}>
          <Divider style={{ margin: "0 0 10px" }} />
          <div className="section-label" style={{ marginBottom: 8 }}>
            {clinicianMode ? "SOURCE" : "BYTE-LEVEL PROVENANCE"} — {result.provenances.length} source{result.provenances.length > 1 ? "s" : ""}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {result.provenances.map((prov, i) => (
              <ProvenanceChunk key={i} prov={prov} clinicianMode={clinicianMode} />
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

// ─── Main component ───────────────────────────────────────────

export default function QueryPane({ clinicianMode }: { clinicianMode: boolean }) {
  const [query, setQuery]               = useState("");
  const [expandedResult, setExpanded]   = useState<string | number | null>(null);
  const [displayCount, setDisplayCount] = useState(3);
  const [showFilters, setShowFilters]   = useState(false);
  const [activeFilters, setActiveFilters] = useState<{ phase: string[]; status: string[]; strategy: string[] }>({
    phase: [], status: [], strategy: [],
  });
  const [activeTab, setActiveTab]       = useState<string>("results");
  const [highlightedNct, setHighlighted] = useState<string | null>(null);

  // Live API state via polling hook
  const {
    queryState,
    results: liveResults,
    graph: liveGraph,
    meta: liveMeta,
    errorMsg: liveErrorMsg,
    runQuery: apiRunQuery,
    resetQuery,
  } = useQueryPoll();

  function runQuery() {
    const q = query.trim();
    if (!q) return;
    setExpanded(null);
    setDisplayCount(3);
    setHighlighted(null);
    apiRunQuery(q, { topK: 10 });
  }

  function toggleFilter(category: keyof typeof activeFilters, value: string) {
    setActiveFilters((prev) => {
      const cur = prev[category];
      return { ...prev, [category]: cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value] };
    });
  }

  function filteredResults(): TrialResult[] {
    const source = liveResults;
    return source.filter((r) => {
      if (activeFilters.phase.length    > 0 && !activeFilters.phase.includes(r.phase))              return false;
      if (activeFilters.status.length   > 0 && !activeFilters.status.includes(r.enrollmentStatus))  return false;
      if (activeFilters.strategy.length > 0 && !activeFilters.strategy.includes(r.strategy))        return false;
      return true;
    });
  }

  function handleGraphTrialClick(nctId: string) {
    setActiveTab("results");
    setHighlighted(nctId);
  }

  const results        = filteredResults();
  const visibleResults = results.slice(0, displayCount);
  const hasMore        = displayCount < results.length;
  const anyFilterActive = Object.values(activeFilters).some((a) => a.length > 0);
  const selectedForProvenance = results.find((r) => r.id === expandedResult) ?? results[0];

  // ── Panels ────────────────────────────────────────────────

  function ResultsPanel() {
    if (queryState === "idle") {
      return (
        <NonIdealState
          icon="search"
          title="Enter a query"
          description={
            clinicianMode
              ? 'Search across the clinical knowledge base. Try "heparin renal impairment".'
              : 'Natural language search across the clinical knowledge base. Try "heparin renal impairment" — or type "error" / "empty" to preview those states.'
          }
        />
      );
    }
    if (queryState === "loading") {
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, paddingTop: 8 }}>
          {[1, 2, 3].map((i) => <SkeletonCard key={i} />)}
        </div>
      );
    }
    if (queryState === "error") {
      return (
        <div style={{ paddingTop: 8 }}>
          <Callout intent={Intent.DANGER} icon="error" title={clinicianMode ? "Search unavailable" : "Retrieval failed"}>
            <p style={{ margin: "6px 0 10px", fontSize: 12 }}>
              {clinicianMode
                ? "The search service is temporarily unavailable. Please try again in a moment."
                : (liveErrorMsg ?? "The retrieval pipeline returned an error.")}
            </p>
            <Button small intent={Intent.DANGER} text="Retry" onClick={runQuery} />
          </Callout>
        </div>
      );
    }
    if (queryState === "empty") {
      return (
        <NonIdealState
          icon="search-template"
          title="No results"
          description={
            clinicianMode
              ? "No matching records found. Try different terms or remove any active filters."
              : "No matches above the confidence threshold (0.70). Try broader terms or clear the active filters."
          }
        />
      );
    }
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>

        {/* ── Synthesis card — no backend endpoint yet ─────────── */}
        <Card
          elevation={Elevation.TWO}
          style={{ padding: "14px 16px", borderRadius: 10 }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <span className="section-label" style={{ margin: 0 }}>
              {clinicianMode ? "CLINICAL SUMMARY" : "AI SYNTHESIS"}
            </span>
            <Tag minimal style={{ fontSize: 9 }}>pending</Tag>
          </div>
          <p style={{ margin: 0, fontSize: 12, color: "var(--text-dim)", fontStyle: "italic" }}>
            {clinicianMode
              ? "AI-generated clinical summary not yet available for this query."
              : "Synthesis endpoint not yet wired — enable POST /api/synthesize to populate this card."}
          </p>
        </Card>

        {/* ── Meta row ─────────────────────────────────────────── */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 2 }}>
          <span style={{ fontFamily: "var(--text-mono)", fontSize: 10, color: "var(--text-dim)" }}>
            {results.length} source{results.length !== 1 ? "s" : ""} · showing {Math.min(displayCount, results.length)}
          </span>
          {anyFilterActive && (
            <Tag
              minimal
              intent={Intent.WARNING}
              onRemove={() => setActiveFilters({ phase: [], status: [], strategy: [] })}
            >
              filters active
            </Tag>
          )}
        </div>
        {visibleResults.map((result) => (
          <ResultCard
            key={result.id}
            result={result}
            expanded={expandedResult === result.id}
            highlighted={highlightedNct === result.nct}
            clinicianMode={clinicianMode}
            onToggle={() => {
              const next = expandedResult === result.id ? null : result.id;
              setExpanded(next);
              if (next) setHighlighted(null);
            }}
          />
        ))}
        {hasMore && (
          <Button
            minimal fill
            icon="plus"
            text={`Load ${Math.min(2, results.length - displayCount)} more`}
            onClick={() => setDisplayCount((c) => c + 2)}
            style={{ fontFamily: "var(--text-mono)", fontSize: 11 }}
          />
        )}
      </div>
    );
  }

  function ProvenancePanel() {
    if (!selectedForProvenance) {
      return (
        <NonIdealState
          icon="search-template"
          title="No results yet"
          description="Run a query to load provenance data."
        />
      );
    }
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {expandedResult === null && (
          <Callout intent={Intent.NONE} icon="info-sign">
            <span style={{ fontSize: 12 }}>Expand a result card to load its full provenance here.</span>
          </Callout>
        )}
        <div>
          <div className="section-label" style={{ marginBottom: 4 }}>
            {selectedForProvenance.nct} — {selectedForProvenance.title}
          </div>
          <div style={{ display: "flex", gap: 5, marginBottom: 10, flexWrap: "wrap" }}>
            {selectedForProvenance.matchedCriteria.map((c) => (
              <Tag key={c} minimal intent={Intent.PRIMARY} style={{ fontSize: 10 }}>{c}</Tag>
            ))}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {selectedForProvenance.provenances.map((p, i) => (
              <ProvenanceChunk key={i} prov={p} clinicianMode={clinicianMode} />
            ))}
          </div>
        </div>
      </div>
    );
  }

  function GraphPanel() {
    return (
      <KnowledgeGraph
        onTrialClick={handleGraphTrialClick}
        highlightedNct={highlightedNct}
        nodes={liveGraph?.nodes}
        edges={liveGraph?.edges}
      />
    );
  }

  const resultCount = queryState === "results" ? results.length : 0;

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>

      {/* Search bar */}
      <div
        style={{
          padding: "10px 14px",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <InputGroup
            placeholder="e.g. heparin dosing renal impairment STEMI..."
            leftIcon="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runQuery()}
            fill
            style={{ fontFamily: "var(--text-mono)" }}
            rightElement={
              query ? (
                <Button minimal icon="cross" onClick={() => { setQuery(""); resetQuery(); }} />
              ) : undefined
            }
          />
          <Button
            minimal
            icon="filter"
            active={showFilters}
            onClick={() => setShowFilters((v) => !v)}
            title="Advanced filters"
            style={{ flexShrink: 0 }}
          />
          <Button
            intent={Intent.SUCCESS}
            text="RUN"
            loading={queryState === "loading"}
            onClick={runQuery}
            style={{ flexShrink: 0, fontFamily: "var(--text-mono)", letterSpacing: "0.08em" }}
          />
        </div>

        {/* Filter row */}
        {showFilters && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {(Object.entries(FILTER_OPTIONS) as [keyof typeof FILTER_OPTIONS, string[]][]).map(([cat, options]) => (
              <div key={cat} style={{ display: "flex", gap: 5, alignItems: "center", flexWrap: "wrap" }}>
                <span style={{ fontFamily: "var(--text-mono)", fontSize: 9, color: "var(--text-dim)", width: 52 }}>
                  {cat.toUpperCase()}
                </span>
                {options.map((opt) => {
                  const active = activeFilters[cat].includes(opt);
                  return (
                    <Tag
                      key={opt}
                      minimal={!active}
                      intent={active ? Intent.PRIMARY : Intent.NONE}
                      interactive
                      onClick={() => toggleFilter(cat, opt)}
                      style={{ fontSize: 10, cursor: "pointer" }}
                    >
                      {opt}
                    </Tag>
                  );
                })}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Tab content — bento container */}
      <div style={{ flex: 1, overflow: "auto", padding: "10px 14px 14px" }}>
        <div style={{
          border: "1px solid var(--border)",
          borderRadius: 12,
          overflow: "hidden",
          minHeight: "100%",
          background: "var(--surface-1)",
        }}>
        <Tabs
          id="result-tabs"
          selectedTabId={activeTab}
          onChange={(id) => setActiveTab(id as string)}
          renderActiveTabPanelOnly
        >
          <Tab
            id="results"
            title={resultCount > 0 ? `RESULTS (${resultCount})` : "RESULTS"}
            panel={<ResultsPanel />}
          />
          <Tab id="provenance" title="PROVENANCE" panel={<ProvenancePanel />} />
          <Tab id="kg"         title="ENTITY GRAPH" panel={<GraphPanel />} />
        </Tabs>
        </div>
      </div>

      {/* Status bar */}
      <div
        style={{
          borderTop: "1px solid var(--border)",
          padding: "5px 14px",
          display: "flex",
          gap: 16,
          alignItems: "center",
        }}
      >
        {clinicianMode ? (
          <>
            <span style={{ fontFamily: "var(--text-mono)", fontSize: 10, color: "var(--text-dim)" }}>
              RESULTS: <span style={{ color: "var(--text-secondary)" }}>{queryState === "results" ? String(results.length) : "—"}</span>
            </span>
            <Divider />
            <Tag minimal intent={Intent.SUCCESS}>Search ready</Tag>
          </>
        ) : (
          <>
            {[
              ["RESULTS",  queryState === "results" ? String(liveMeta?.totalHits ?? results.length) : "—"],
              ["LATENCY",  queryState === "results" ? (liveMeta ? `${liveMeta.latencyMs}ms` : "—") : "—"],
              ["INDEX",    liveMeta?.indexVersion ?? "—"],
              ["STRATEGY", liveMeta?.strategy ?? "—"],
            ].map(([k, v]) => (
              <span key={k} style={{ fontFamily: "var(--text-mono)", fontSize: 10, color: "var(--text-dim)" }}>
                {k}: <span style={{ color: "var(--text-secondary)" }}>{v}</span>
              </span>
            ))}
            <Divider />
            <Tag minimal intent={Intent.SUCCESS}>INDEX ONLINE</Tag>
          </>
        )}
      </div>
    </div>
  );
}
