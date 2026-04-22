import AppShell from "@/components/layout/AppShell";
import MetricsPanel from "@/components/pages/MetricsPanel";
import { emptyMetrics } from "@/lib/empty";

export default function Metrics() {
  return (
    <AppShell activePath="/metrics">
      <MetricsPanel metrics={emptyMetrics} />
    </AppShell>
  );
}
