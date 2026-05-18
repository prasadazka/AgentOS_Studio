"use client";

import { Wrench } from "lucide-react";
import type { Tool } from "@/types";

const categoryColors: Record<string, string> = {
  research: "bg-blue-50 text-blue-700",
  data: "bg-green-50 text-green-700",
  file: "bg-yellow-50 text-yellow-700",
  web: "bg-orange-50 text-orange-700",
  database: "bg-indigo-50 text-indigo-700",
  git: "bg-red-50 text-red-700",
  security: "bg-pink-50 text-pink-700",
  gcp: "bg-cyan-50 text-cyan-700",
  infrastructure: "bg-teal-50 text-teal-700",
  devops: "bg-slate-50 text-slate-700",
};

export default function ToolCard({ tool }: { tool: Tool }) {
  const colorClass = categoryColors[tool.category] || "bg-gray-50 text-gray-700";

  return (
    <div className="bg-white rounded-lg border border-[var(--border-light)] p-4 hover:shadow-card transition-shadow">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-gray-50 flex items-center justify-center flex-shrink-0">
          <Wrench className="w-4 h-4 text-gray-500" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-sm font-medium text-gray-900 truncate">
              {tool.name}
            </h3>
            <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${colorClass}`}>
              {tool.category}
            </span>
          </div>
          <p className="text-xs text-gray-500 line-clamp-2">
            {tool.description}
          </p>
        </div>
      </div>
    </div>
  );
}