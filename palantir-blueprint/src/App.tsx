import { useState, useRef, useEffect, useCallback } from "react";
import clsx from "clsx";

import Navigation from "./components/Navigation";
import LeftPane from "./components/LeftPane";
import type { QueryHistoryItem, PatientRecord } from "./components/LeftPane";
import QueryPane from "./components/QueryPane";
import IngestionPane from "./components/IngestionPane";

const PANE_MIN = 160;
const PANE_MAX = 520;
const PANE_DEFAULT = 290;
const THEME_STORAGE_KEY = "clinical-search-theme";

type ThemeMode = "solarized" | "slate";

function getInitialTheme(): ThemeMode {
  return window.localStorage.getItem(THEME_STORAGE_KEY) === "slate" ? "slate" : "solarized";
}

export default function App() {
  const [clinicianMode, setClinicalMode] = useState(true);
  const [theme, setTheme]               = useState<ThemeMode>(getInitialTheme);
  const [paneWidth, setPaneWidth]       = useState(PANE_DEFAULT);
  const [collapsed, setCollapsed]       = useState(false);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [dragging, setDragging]         = useState(false);
  // Session history + patient context
  const [history, setHistory]           = useState<QueryHistoryItem[]>([]);
  const [patientRecord, setRecord]      = useState<PatientRecord>({ name: "", mrn: "", dob: "", chief: "", allergies: "", meds: "" });
  const [externalFill, setExternalFill] = useState<string | undefined>(undefined);
  const dragStartX  = useRef(0);
  const dragStartW  = useRef(0);

  const onDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragStartX.current = e.clientX;
    dragStartW.current = paneWidth;
    setDragging(true);
  }, [paneWidth]);

  useEffect(() => {
    if (!dragging) return;
    function onMove(e: MouseEvent) {
      const delta = dragStartX.current - e.clientX;
      const next  = Math.min(PANE_MAX, Math.max(PANE_MIN, dragStartW.current + delta));
      setPaneWidth(next);
    }
    function onUp() { setDragging(false); }
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [dragging]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  function handleQueryComplete(query: string, hitCount: number) {
    setHistory((prev) => [
      ...prev,
      { id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, query, ts: Date.now(), hitCount },
    ]);
  }

  function handleSelectHistory(q: string) {
    setExternalFill(q);
  }

  return (
    <div
      className={clsx("app-root")}
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        overflow: "hidden",
        background: "var(--surface-0)",
        userSelect: dragging ? "none" : undefined,
        cursor: dragging ? "col-resize" : undefined,
      }}
    >
      <Navigation
        clinicianMode={clinicianMode}
        theme={theme}
        onModeToggle={() => setClinicalMode((v) => !v)}
        onThemeToggle={() => setTheme((current) => current === "solarized" ? "slate" : "solarized")}
      />
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* LeftPane with animated width */}
        <div
          style={{
            width: leftCollapsed ? 0 : 200,
            flexShrink: 0,
            overflow: "hidden",
            transition: "width 0.22s cubic-bezier(0.4,0,0.2,1)",
          }}
        >
          <LeftPane
            history={history}
            onSelect={handleSelectHistory}
            onClearHistory={() => setHistory([])}
            record={patientRecord}
            onUpdateRecord={setRecord}
          />
        </div>

        {/* Left pane collapse / expand handle */}
        <div
          style={{
            width: 8,
            flexShrink: 0,
            position: "relative",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 10,
          }}
        >
          <div
            style={{
              position: "absolute",
              inset: 0,
              width: 1,
              left: "50%",
              transform: "translateX(-50%)",
              background: "var(--border)",
            }}
          />
          <button
            onClick={() => setLeftCollapsed((v) => !v)}
            style={{
              position: "relative",
              zIndex: 2,
              width: 18,
              height: 36,
              borderRadius: 9,
              border: "1px solid var(--control-border)",
              background: "var(--surface-2)",
              color: "var(--text-dim)",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: 0,
              fontSize: 10,
              transition: "all 0.15s ease",
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = "var(--surface-3)";
              (e.currentTarget as HTMLButtonElement).style.color = "var(--accent-primary)";
              (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--accent-primary)";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = "var(--surface-2)";
              (e.currentTarget as HTMLButtonElement).style.color = "var(--text-dim)";
              (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--control-border)";
            }}
            title={leftCollapsed ? "Expand panel" : "Collapse panel"}
          >
            {leftCollapsed ? "›" : "‹"}
          </button>
        </div>

        <QueryPane
          clinicianMode={clinicianMode}
          externalFill={externalFill}
          onQueryComplete={handleQueryComplete}
        />

        {/* Drag handle + collapse toggle for right pane */}
        <div
          style={{
            width: 8,
            flexShrink: 0,
            position: "relative",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: collapsed ? "default" : "col-resize",
            background: dragging ? "var(--accent-primary-dim)" : "transparent",
            transition: "background 0.15s",
            zIndex: 10,
          }}
          onMouseDown={collapsed ? undefined : onDragStart}
        >
          {/* Visible divider line */}
          <div
            style={{
              position: "absolute",
              inset: 0,
              width: 1,
              left: "50%",
              transform: "translateX(-50%)",
              background: dragging ? "var(--accent-primary)" : "var(--border)",
              transition: "background 0.15s",
            }}
          />
          {/* Collapse / expand button */}
          <button
            onClick={() => setCollapsed((v) => !v)}
            style={{
              position: "relative",
              zIndex: 2,
              width: 18,
              height: 36,
              borderRadius: 9,
              border: "1px solid var(--control-border)",
              background: "var(--surface-2)",
              color: "var(--text-dim)",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: 0,
              fontSize: 10,
              transition: "all 0.15s ease",
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = "var(--surface-3)";
              (e.currentTarget as HTMLButtonElement).style.color = "var(--accent-primary)";
              (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--accent-primary)";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = "var(--surface-2)";
              (e.currentTarget as HTMLButtonElement).style.color = "var(--text-dim)";
              (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--control-border)";
            }}
            title={collapsed ? "Expand panel" : "Collapse panel"}
          >
            {collapsed ? "›" : "‹"}
          </button>
        </div>

        {/* IngestionPane with animated width */}
        <div
          style={{
            width: collapsed ? 0 : paneWidth,
            flexShrink: 0,
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
            transition: dragging ? "none" : "width 0.22s cubic-bezier(0.4,0,0.2,1)",
          }}
        >
          <IngestionPane clinicianMode={clinicianMode} />
        </div>
      </div>
    </div>
  );
}
