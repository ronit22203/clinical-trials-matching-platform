import AppShell from "@/components/layout/AppShell";
import TemplatesPage from "@/components/pages/TemplatesPage";

export default function Templates() {
  return (
    <AppShell activePath="/templates">
      <TemplatesPage templates={[]} />
    </AppShell>
  );
}
