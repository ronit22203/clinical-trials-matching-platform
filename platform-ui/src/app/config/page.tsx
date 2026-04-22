"use client";

import AppShell from "@/components/layout/AppShell";
import ConfigPanel from "@/components/pages/ConfigPanel";
import { defaultAgentConfig } from "@/lib/empty";

export default function Config() {
  return (
    <AppShell activePath="/config">
      <ConfigPanel config={defaultAgentConfig} />
    </AppShell>
  );
}
