"use client";

import { useState } from "react";
import Sidebar from "./Sidebar";
import RightPanel from "./RightPanel";
import type { Trial } from "@/lib/types/trial";

interface AppShellProps {
  children: React.ReactNode;
  rightPanel?: React.ReactNode;
  activePath?: string;
  trials?: Trial[];
}

export default function AppShell({ children, rightPanel, activePath }: AppShellProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <div className="flex h-screen overflow-hidden bg-surface">
      {/* Left Sidebar */}
      <Sidebar
        activePath={activePath}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
      />

      {/* Main Content */}
      <main className="flex-1 flex flex-col min-w-0 overflow-y-auto bg-surface">
        {children}
      </main>

      {/* Right Panel */}
      {rightPanel && (
        <aside className="w-[380px] shrink-0 flex flex-col border-l-0 bg-surface-low overflow-y-auto">
          {rightPanel}
        </aside>
      )}
    </div>
  );
}
