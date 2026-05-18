"use client";

import Link from "next/link";
import { Workflow, Trash2, Clock, Play } from "lucide-react";
import type { Workflow as WorkflowType } from "@/types";

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-gray-100 text-gray-600",
  ready: "bg-blue-100 text-blue-600",
  running: "bg-amber-100 text-amber-600",
  completed: "bg-emerald-100 text-emerald-600",
  error: "bg-red-100 text-red-600",
};

export default function WorkflowCard({
  workflow,
  onDelete,
}: {
  workflow: WorkflowType;
  onDelete: (id: string) => void;
}) {
  const nodeCount = workflow.graph_json?.nodes?.length || 0;
  const edgeCount = workflow.graph_json?.edges?.length || 0;
  const statusClass = STATUS_COLORS[workflow.status] || STATUS_COLORS.draft;

  return (
    <Link
      href={`/workflows/${workflow.id}`}
      className="block bg-white rounded-lg border border-[var(--border-light)] hover:border-primary-200 hover:shadow-sm transition-all group"
    >
      <div className="p-4">
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg bg-primary-50 flex items-center justify-center">
              <Workflow className="w-5 h-5 text-primary-600" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-gray-900">{workflow.name}</h3>
              <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${statusClass}`}>
                {workflow.status}
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); onDelete(workflow.id); }}
            className="opacity-0 group-hover:opacity-100 p-1.5 text-gray-400 hover:text-red-500 rounded transition-all"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>

        {workflow.description && (
          <p className="text-xs text-gray-500 mb-3 line-clamp-2">{workflow.description}</p>
        )}

        <div className="flex items-center gap-4 text-[10px] text-gray-400">
          <span className="flex items-center gap-1">
            <Play className="w-3 h-3" /> {nodeCount} nodes
          </span>
          <span>{edgeCount} edges</span>
          <span className="flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {new Date(workflow.updated_at).toLocaleDateString()}
          </span>
        </div>
      </div>
    </Link>
  );
}
