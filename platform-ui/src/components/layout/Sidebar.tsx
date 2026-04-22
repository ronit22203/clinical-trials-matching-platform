"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "./ThemeToggle";
import {
  Users,
  BookOpen,
  BarChart3,
  ClipboardList,
  FileText,
  Settings,
  Plus,
  ChevronLeft,
  ChevronRight,
  FlaskConical,
} from "lucide-react";

const NAV_ITEMS = [
  { label: "Patient Cases", href: "/cases", icon: Users },
  { label: "Evidence", href: "/evidence", icon: BookOpen },
  { label: "Metrics", href: "/metrics", icon: BarChart3 },
  { label: "Audit Trail", href: "/audit", icon: ClipboardList },
  { label: "Templates", href: "/templates", icon: FileText },
  { label: "Config", href: "/config", icon: Settings },
] as const;

interface SidebarProps {
  activePath?: string;
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export default function Sidebar({ activePath, collapsed, onToggleCollapse }: SidebarProps) {
  return (
    <aside
      className={cn(
        "flex flex-col shrink-0 bg-surface-low transition-all duration-200 ease-in-out",
        collapsed ? "w-[60px]" : "w-[240px]"
      )}
    >
      {/* Logo + toggle */}
      <div className="flex items-center justify-between px-4 py-5">
        {!collapsed && (
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg btn-primary-gradient flex items-center justify-center shrink-0">
              <FlaskConical className="w-4 h-4 text-white" />
            </div>
            <span
              className="text-sm font-semibold leading-tight"
              style={{ fontFamily: "var(--font-manrope)", color: "var(--on-surface)" }}
            >
              MARA
            </span>
          </div>
        )}
        {collapsed && (
          <div className="w-7 h-7 rounded-lg btn-primary-gradient flex items-center justify-center mx-auto">
            <FlaskConical className="w-4 h-4 text-white" />
          </div>
        )}
        {!collapsed && (
          <button
            onClick={onToggleCollapse}
            className="p-1 rounded-md text-on-surface-variant hover:bg-surface-container transition-colors"
            aria-label="Collapse sidebar"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* New Case CTA */}
      <div className={cn("px-3 mb-4", collapsed && "px-2")}>
        <Link
          href="/cases/new"
          className={cn(
            "flex items-center gap-2 rounded-xl btn-primary-gradient text-white text-sm font-medium transition-opacity hover:opacity-90",
            collapsed ? "justify-center p-2" : "px-3 py-2"
          )}
        >
          <Plus className="w-4 h-4 shrink-0" />
          {!collapsed && <span>New Case</span>}
        </Link>
      </div>

      {/* Nav items */}
      <nav className="flex-1 px-3 space-y-1">
        {NAV_ITEMS.map(({ label, href, icon: Icon }) => {
          const isActive = activePath?.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 rounded-xl text-sm transition-colors",
                collapsed ? "justify-center p-2" : "px-3 py-2",
                isActive
                  ? "bg-surface-container text-primary font-semibold"
                  : "text-on-surface-variant hover:bg-surface-container hover:text-on-surface"
              )}
              title={collapsed ? label : undefined}
            >
              <Icon className={cn("shrink-0", isActive ? "w-4 h-4 text-primary" : "w-4 h-4")} />
              {!collapsed && <span>{label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Collapse toggle (bottom) */}
      {collapsed && (
        <div className="px-2 pb-2">
          <button
            onClick={onToggleCollapse}
            className="w-full flex justify-center p-2 rounded-xl text-on-surface-variant hover:bg-surface-container transition-colors"
            aria-label="Expand sidebar"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Theme toggle + version badge */}
      <div className={cn("pb-4", collapsed ? "px-2" : "px-3")}>
        <ThemeToggle collapsed={collapsed} />
        {!collapsed && (
          <p className="mt-2 px-1 text-[10px] uppercase tracking-widest text-on-surface-variant opacity-60">
            v1.0 · MIT
          </p>
        )}
      </div>
    </aside>
  );
}
