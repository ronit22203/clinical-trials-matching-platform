import AppShell from "@/components/layout/AppShell";
import Link from "next/link";
import { cn, formatTimestamp } from "@/lib/utils";
import type { PatientCase } from "@/lib/types/patient";

const cases: PatientCase[] = [];

const STATUS_CLASS = {
  matching_complete: "bg-[rgba(22,163,74,0.1)] text-status-eligible",
  pending: "bg-[rgba(217,119,6,0.1)] text-status-partial",
  in_review: "bg-[rgba(0,80,80,0.1)] text-primary",
};
const STATUS_LABEL = {
  matching_complete: "Complete",
  pending: "Pending",
  in_review: "In Review",
};

function CaseRow({ c }: { c: PatientCase }) {
  return (
    <Link
      href={`/cases/${c.id}`}
      className="flex items-center justify-between px-5 py-4 rounded-2xl bg-surface-lowest ambient-shadow hover:shadow-[0_8px_24px_rgba(0,80,80,0.09)] transition-shadow"
    >
      <div>
        <p className="text-sm font-semibold text-on-surface" style={{ fontFamily: "var(--font-manrope)" }}>
          {c.name}
        </p>
        <p className="text-xs text-on-surface-variant mt-0.5">{c.condition}</p>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-xs text-on-surface-variant">{formatTimestamp(c.lastRun)}</span>
        <span className={cn("text-[10px] font-semibold px-2 py-0.5 rounded-lg uppercase tracking-wide", STATUS_CLASS[c.status])}>
          {STATUS_LABEL[c.status]}
        </span>
      </div>
    </Link>
  );
}

export default function CasesPage() {
  return (
    <AppShell activePath="/cases">
      <div className="p-6 max-w-3xl space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-on-surface" style={{ fontFamily: "var(--font-manrope)" }}>
              Patient Cases
            </h1>
            <p className="text-sm text-on-surface-variant">{cases.length} cases</p>
          </div>
          <Link
            href="/cases/new"
            className="px-4 py-2 rounded-xl btn-primary-gradient text-white text-sm font-semibold hover:opacity-90 transition-opacity"
          >
            + New Case
          </Link>
        </div>
        {cases.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <p className="text-sm font-medium text-on-surface-variant">No cases yet</p>
            <p className="text-xs text-on-surface-variant mt-1 max-w-xs">
              Create a new case or run the ingestion pipeline to populate patient data.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {cases.map((c) => (
              <CaseRow key={c.id} c={c} />
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
