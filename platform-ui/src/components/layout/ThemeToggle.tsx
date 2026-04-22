"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Sun, Moon, Monitor } from "lucide-react";
import { cn } from "@/lib/utils";

export function ThemeToggle({ collapsed }: { collapsed?: boolean }) {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // Avoid hydration mismatch — render nothing until mounted on client
  useEffect(() => setMounted(true), []);
  if (!mounted) return null;

  const cycles: Array<{ value: string; icon: typeof Sun; label: string }> = [
    { value: "light", icon: Sun, label: "Light" },
    { value: "dark", icon: Moon, label: "Dark" },
    { value: "system", icon: Monitor, label: "System" },
  ];

  const current = cycles.find((c) => c.value === theme) ?? cycles[2];
  const next = cycles[(cycles.indexOf(current) + 1) % cycles.length];
  const Icon = current.icon;

  return (
    <button
      onClick={() => setTheme(next.value)}
      className={cn(
        "flex items-center gap-2 rounded-xl text-xs text-on-surface-variant hover:bg-surface-container hover:text-on-surface transition-colors",
        collapsed ? "justify-center p-2" : "px-3 py-2 w-full"
      )}
      title={`Theme: ${current.label} (click for ${next.label})`}
    >
      <Icon className="w-4 h-4 shrink-0" />
      {!collapsed && <span>{current.label}</span>}
    </button>
  );
}
