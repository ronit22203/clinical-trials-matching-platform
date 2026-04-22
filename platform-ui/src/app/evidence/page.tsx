import AppShell from "@/components/layout/AppShell";
import EvidencePage from "@/components/pages/EvidencePage";

export default function Evidence() {
  return (
    <AppShell activePath="/evidence">
      <EvidencePage citations={[]} />
    </AppShell>
  );
}
