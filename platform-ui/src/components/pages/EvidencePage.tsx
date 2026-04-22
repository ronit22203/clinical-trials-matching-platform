"use client";

import type { Citation } from "@/lib/types/evidence";
import EvidencePanel from "@/components/match/EvidencePanel";
import { Search } from "lucide-react";
import { useState } from "react";

interface EvidencePageProps {
  citations: Citation[];
}

export default function EvidencePage({ citations }: EvidencePageProps) {
  const [query, setQuery] = useState("");

  const filtered = citations.filter(
    (c) =>
      !query ||
      c.title.toLowerCase().includes(query.toLowerCase()) ||
      c.snippet.toLowerCase().includes(query.toLowerCase()) ||
      c.authors.toLowerCase().includes(query.toLowerCase())
  );

  return (
    <div className="p-6 max-w-3xl space-y-5">
      <div>
        <h1
          className="text-xl font-bold text-on-surface mb-1"
          style={{ fontFamily: "var(--font-manrope)" }}
        >
          Evidence / Citations
        </h1>
        <p className="text-sm text-on-surface-variant">
          {citations.length} citations · PubMed · ClinicalTrials.gov · GraphRAG
        </p>
      </div>

      {/* Search */}
      <div className="flex items-center gap-2 bg-surface-lowest rounded-xl px-3 py-2 ambient-shadow">
        <Search className="w-4 h-4 text-on-surface-variant shrink-0" />
        <input
          type="text"
          placeholder="Search citations, authors, snippets…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="flex-1 bg-transparent text-sm text-on-surface placeholder-on-surface-variant/50 outline-none"
        />
      </div>

      <EvidencePanel citations={filtered} />
    </div>
  );
}
