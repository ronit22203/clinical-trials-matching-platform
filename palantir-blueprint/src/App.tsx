import { useState, useRef, useEffect, useCallback } from "react";
import clsx from "clsx";

import Navigation from "./components/Navigation";
import QueryPane from "./components/QueryPane";
import IngestionPane from "./components/IngestionPane";

const PANE_MIN = 160;
const PANE_MAX = 520;
const PANE_DEFAULT = 290;

export default function App() {
  const [clinicianMode, setClinicalMode] = useState(true);
  const [paneWidth, setPaneWidth]       = useState(PANE_DEFAULT);
  const [collapsed, setCollapsed]       = useState(false);
  const [dragging, setDragging]         = useState(false);
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
      <Navigation clinicianMode={clinicianMode} onModeToggle={() => setClinicalMode((v) => !v)} />
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <QueryPane clinicianMode={clinicianMode} />

        {/* Drag handle + collapse toggle */}
        <div
          style={{
            width: 8,
            flexShrink: 0,
            position: "relative",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: collapsed ? "default" : "col-resize",
            background: dragging ? "rgba(126,200,164,0.08)" : "transparent",
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
              border: "1px solid var(--border)",
              background: "var(--surface-2)",
              color: "var(--text-dim)",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: 0,
              fontSize: 10,
              transition: "all 0.15s ease",
              backdropFilter: "blur(8px)",
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = "var(--surface-3)";
              (e.currentTarget as HTMLButtonElement).style.color = "var(--accent-primary)";
              (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--accent-primary)";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = "var(--surface-2)";
              (e.currentTarget as HTMLButtonElement).style.color = "var(--text-dim)";
              (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--border)";
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
