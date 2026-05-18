"use client";

import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import Header from "@/components/layout/Header";
import ToolCard from "@/components/tools/ToolCard";
import { api } from "@/lib/api";
import type { Tool } from "@/types";

export default function ToolsPage() {
  const [tools, setTools] = useState<Tool[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [activeCategory, setActiveCategory] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [toolsData, catsData] = await Promise.all([
          api<{ tools: Tool[] }>("/api/tools"),
          api<{ categories: string[] }>("/api/tools/categories"),
        ]);
        setTools(toolsData.tools);
        setCategories(catsData.categories);
      } catch (e) {
        console.error("Failed to load tools:", e);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const filtered = tools.filter((t) => {
    const matchesCategory =
      activeCategory === "all" || t.category === activeCategory;
    const matchesSearch =
      !search ||
      t.name.toLowerCase().includes(search.toLowerCase()) ||
      t.description.toLowerCase().includes(search.toLowerCase());
    return matchesCategory && matchesSearch;
  });

  return (
    <div className="flex flex-col h-full">
      <Header title="Tools" />

      <div className="flex-1 p-6">
        {/* Search + Categories */}
        <div className="mb-5 space-y-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="Search tools..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 pr-4 py-2 text-sm bg-white border border-[var(--border-light)] rounded-lg w-72 focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500"
            />
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setActiveCategory("all")}
              className={`px-3 py-1.5 text-xs font-medium rounded-full transition-colors ${
                activeCategory === "all"
                  ? "bg-primary-600 text-white"
                  : "bg-white text-gray-600 border border-[var(--border-light)] hover:bg-gray-50"
              }`}
            >
              All ({tools.length})
            </button>
            {categories.map((cat) => {
              const count = tools.filter((t) => t.category === cat).length;
              return (
                <button
                  key={cat}
                  onClick={() => setActiveCategory(cat)}
                  className={`px-3 py-1.5 text-xs font-medium rounded-full transition-colors capitalize ${
                    activeCategory === cat
                      ? "bg-primary-600 text-white"
                      : "bg-white text-gray-600 border border-[var(--border-light)] hover:bg-gray-50"
                  }`}
                >
                  {cat} ({count})
                </button>
              );
            })}
          </div>
        </div>

        {/* Tools Grid */}
        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div
                key={i}
                className="h-24 bg-white rounded-lg border border-[var(--border-light)] animate-pulse"
              />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-12 text-gray-500 text-sm">
            No tools found.
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {filtered.map((tool) => (
              <ToolCard key={tool.name} tool={tool} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}