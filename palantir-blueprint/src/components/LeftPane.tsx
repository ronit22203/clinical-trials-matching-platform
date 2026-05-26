import { useState } from "react";
import { Button, Divider, Intent, Tag } from "@blueprintjs/core";

// ─── Types ────────────────────────────────────────────────────

export interface QueryHistoryItem {
  id: string;
  query: string;
  ts: number;
  hitCount: number;
}

export interface PatientRecord {
  name: string;
  mrn: string;
  dob: string;
  chief: string;
  allergies: string;
  meds: string;
}

interface LeftPaneProps {
  history: QueryHistoryItem[];
  onSelect: (query: string) => void;
  record: PatientRecord;
  onUpdateRecord: (r: PatientRecord) => void;
}

// ─── Helpers ──────────────────────────────────────────────────

function formatTs(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 60_000)       return "just now";
  if (diff < 3_600_000)    return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000)   return `${Math.floor(diff / 3_600_000)}h ago`;
  return new Date(ts).toLocaleDateString();
}

const RECORD_FIELDS: { key: keyof PatientRecord; label: string; placeholder?: string }[] = [
  { key: "name",      label: "NAME" },
  { key: "mrn",       label: "MRN" },
  { key: "dob",       label: "DOB" },
  { key: "chief",     label: "CHIEF COMPLAINT",  placeholder: "Chest pain, dyspnoea…" },
  { key: "allergies", label: "ALLERGIES",         placeholder: "Penicillin, NSAIDS…"  },
  { key: "meds",      label: "CURRENT MEDS",      placeholder: "Heparin, metoprolol…" },
];

// ─── Component ────────────────────────────────────────────────

export default function LeftPane({ history, onSelect, record, onUpdateRecord }: LeftPaneProps) {
  const [editing, setEditing] = useState(false);
  const [draft,   setDraft]   = useState<PatientRecord>(record);

  function saveRecord() {
    onUpdateRecord(draft);
    setEditing(false);
  }

  function startEditing() {
    setDraft(record);
    setEditing(true);
  }

  const hasRecord = !!(record.name || record.mrn || record.chief);

  return (
    <div className="left-pane">

      {/* ── Previous Queries ─────────────────────────────── */}
      <div className="left-pane-section-header">
        <span className="section-label" style={{ margin: 0 }}>PREVIOUS QUERIES</span>
        {history.length > 0 && (
          <Tag minimal style={{ fontSize: 9, padding: "1px 5px" }}>{history.length}</Tag>
        )}
      </div>

      <div className="left-pane-history">
        {history.length === 0 ? (
          <div className="left-pane-empty">
            <span style={{ fontSize: 18, opacity: 0.35 }}>⌕</span>
            <span>No queries yet</span>
          </div>
        ) : (
          [...history].reverse().map((item) => (
            <button
              key={item.id}
              className="history-item"
              onClick={() => onSelect(item.query)}
              title={`Re-run: ${item.query}`}
            >
              <div className="history-item-query">{item.query}</div>
              <div className="history-item-meta">
                <span>{formatTs(item.ts)}</span>
                <Tag minimal style={{ fontSize: 9, padding: "1px 5px" }}>
                  {item.hitCount} hit{item.hitCount !== 1 ? "s" : ""}
                </Tag>
              </div>
            </button>
          ))
        )}
      </div>

      <Divider style={{ margin: 0 }} />

      {/* ── Patient Record ───────────────────────────────── */}
      <div className="left-pane-section-header">
        <span className="section-label" style={{ margin: 0 }}>PATIENT RECORD</span>
        {editing ? (
          <div style={{ display: "flex", gap: 4 }}>
            <Button
              minimal small icon="tick" intent={Intent.SUCCESS}
              onClick={saveRecord}
              style={{ height: 20, minHeight: 20, minWidth: 20, padding: "0 4px" }}
            />
            <Button
              minimal small icon="cross"
              onClick={() => setEditing(false)}
              style={{ height: 20, minHeight: 20, minWidth: 20, padding: "0 4px" }}
            />
          </div>
        ) : (
          <Button
            minimal small icon="edit"
            onClick={startEditing}
            style={{ height: 20, minHeight: 20, minWidth: 20, padding: "0 4px" }}
          />
        )}
      </div>

      <div className="left-pane-record">
        {editing ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            {RECORD_FIELDS.map(({ key, label, placeholder }) => (
              <div key={key}>
                <div className="section-label" style={{ marginBottom: 2, fontSize: 9 }}>{label}</div>
                <input
                  className="record-input"
                  value={draft[key]}
                  placeholder={placeholder ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
                />
              </div>
            ))}
          </div>
        ) : hasRecord ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {record.name && (
              <div>
                <div className="section-label" style={{ marginBottom: 1, fontSize: 9 }}>NAME</div>
                <div className="data-value" style={{ fontSize: 11 }}>{record.name}</div>
              </div>
            )}
            {record.mrn && (
              <div>
                <div className="section-label" style={{ marginBottom: 1, fontSize: 9 }}>MRN</div>
                <div className="data-value" style={{ fontSize: 11, fontFamily: "var(--text-mono)" }}>{record.mrn}</div>
              </div>
            )}
            {record.dob && (
              <div>
                <div className="section-label" style={{ marginBottom: 1, fontSize: 9 }}>DOB</div>
                <div className="data-value" style={{ fontSize: 11, fontFamily: "var(--text-mono)" }}>{record.dob}</div>
              </div>
            )}
            {record.chief && (
              <div>
                <div className="section-label" style={{ marginBottom: 1, fontSize: 9 }}>CHIEF COMPLAINT</div>
                <div className="data-value" style={{ fontSize: 11, lineHeight: 1.4 }}>{record.chief}</div>
              </div>
            )}
            {record.allergies && (
              <div>
                <div className="section-label" style={{ marginBottom: 2, fontSize: 9 }}>ALLERGIES</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                  {record.allergies.split(",").map((a) => a.trim()).filter(Boolean).map((a) => (
                    <Tag key={a} minimal intent={Intent.DANGER} style={{ fontSize: 9 }}>{a}</Tag>
                  ))}
                </div>
              </div>
            )}
            {record.meds && (
              <div>
                <div className="section-label" style={{ marginBottom: 2, fontSize: 9 }}>CURRENT MEDS</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                  {record.meds.split(",").map((m) => m.trim()).filter(Boolean).map((m) => (
                    <Tag key={m} minimal intent={Intent.PRIMARY} style={{ fontSize: 9 }}>{m}</Tag>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="left-pane-empty">
            <span style={{ fontSize: 18, opacity: 0.35 }}>⊕</span>
            <span>No patient on file</span>
            <Button
              minimal small text="Set context"
              onClick={startEditing}
              style={{ fontSize: 10, marginTop: 2 }}
            />
          </div>
        )}
      </div>

    </div>
  );
}
