import AppShell from "@/components/layout/AppShell";
import AuditTimeline from "@/components/pages/AuditTimeline";
import { emptyExecutionLog } from "@/lib/empty";

export default function Audit() {
  return (
    <AppShell activePath="/audit">
      <AuditTimeline log={emptyExecutionLog} />
    </AppShell>
  );
}
