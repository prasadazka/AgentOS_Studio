"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { CheckCircle2, XCircle, Loader2, Clock, ChevronDown, ChevronRight, Copy, Check } from "lucide-react";
import type { RunNodeState } from "@/types";

const STATUS_CONFIG: Record<string, { icon: typeof Clock; color: string; bg: string; label: string; animate?: boolean }> = {
  pending: { icon: Clock, color: "text-gray-400", bg: "bg-gray-50", label: "Pending" },
  running: { icon: Loader2, color: "text-blue-500", bg: "bg-blue-50", label: "Running", animate: true },
  completed: { icon: CheckCircle2, color: "text-emerald-500", bg: "bg-emerald-50", label: "Completed" },
  error: { icon: XCircle, color: "text-red-500", bg: "bg-red-50", label: "Error" },
};

interface RunOverlayProps {
  nodeStatuses: Record<string, RunNodeState>;
  runStatus: string;
  output: string;
  error?: string;
  onClose: () => void;
}

function NodeOutputCard({ nodeId, state }: { nodeId: string; state: RunNodeState }) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const config = STATUS_CONFIG[state.status] || STATUS_CONFIG.pending;
  const Icon = config.icon;
  const hasOutput = !!state.output && state.output.trim().length > 0;

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (state.output) {
      navigator.clipboard.writeText(state.output);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <div className={`rounded-lg border border-[var(--border-light)] overflow-hidden ${config.bg}`}>
      {/* Header - always visible */}
      <button
        type="button"
        onClick={() => hasOutput && setExpanded(!expanded)}
        className={`w-full flex items-center gap-2 px-3 py-2 text-left ${hasOutput ? "cursor-pointer hover:bg-white/50" : "cursor-default"}`}
      >
        {hasOutput ? (
          expanded ? <ChevronDown className="w-3 h-3 text-gray-400 flex-shrink-0" /> : <ChevronRight className="w-3 h-3 text-gray-400 flex-shrink-0" />
        ) : (
          <span className="w-3 h-3 flex-shrink-0" />
        )}
        <Icon className={`w-3.5 h-3.5 flex-shrink-0 ${config.color} ${config.animate ? "animate-spin" : ""}`} />
        <span className="text-xs font-medium text-gray-700 flex-1">{nodeId}</span>
        <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${config.color}`}>
          {config.label}
        </span>
      </button>

      {/* Output - expandable */}
      {expanded && hasOutput && (
        <div className="border-t border-[var(--border-light)] bg-white px-3 py-2 relative group">
          <button
            type="button"
            onClick={handleCopy}
            className="absolute top-2 right-2 p-1 rounded hover:bg-gray-100 opacity-0 group-hover:opacity-100 transition-opacity"
            title="Copy output"
          >
            {copied ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3 text-gray-400" />}
          </button>
          <div className="text-[11px] text-gray-700 max-h-52 overflow-y-auto leading-relaxed pr-6 prose prose-xs max-w-none prose-headings:text-xs prose-strong:text-gray-900 prose-li:my-0.5">
            <ReactMarkdown>{state.output || ""}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}

export default function RunOverlay({ nodeStatuses, runStatus, output, error, onClose }: RunOverlayProps) {
  const entries = Object.entries(nodeStatuses);
  const isFinished = runStatus === "completed" || runStatus === "error";
  const completedCount = entries.filter(([, s]) => s.status === "completed").length;
  const totalCount = entries.length;

  return (
    <div className="absolute bottom-0 left-0 right-0 bg-white border-t border-[var(--border-light)] shadow-lg max-h-[60%] overflow-y-auto z-20">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--border-light)] bg-gray-50 sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold text-gray-700">Execution Log</span>
          <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${
            runStatus === "completed" ? "bg-emerald-100 text-emerald-600" :
            runStatus === "error" ? "bg-red-100 text-red-600" :
            runStatus === "paused" ? "bg-orange-100 text-orange-600" :
            "bg-blue-100 text-blue-600"
          }`}>
            {runStatus}
          </span>
          {totalCount > 0 && (
            <span className="text-[10px] text-gray-400">
              {completedCount}/{totalCount} nodes
            </span>
          )}
        </div>
        {isFinished && (
          <button type="button" onClick={onClose} className="text-[10px] text-gray-500 hover:text-gray-700 font-medium px-2 py-1 rounded hover:bg-gray-100">
            Close
          </button>
        )}
      </div>

      {/* Node status cards */}
      <div className="p-3 space-y-2">
        {entries.length === 0 && (
          <div className="flex items-center gap-2 text-xs text-gray-400 py-2">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            Starting workflow...
          </div>
        )}

        {entries.map(([nodeId, state]) => (
          <NodeOutputCard key={nodeId} nodeId={nodeId} state={state} />
        ))}

        {/* Final output */}
        {output && isFinished && (
          <div className="mt-3 p-3 bg-emerald-50 rounded-lg border border-emerald-200">
            <div className="text-[10px] font-semibold text-emerald-600 mb-1.5">FINAL OUTPUT</div>
            <div className="text-xs text-gray-800 leading-relaxed overflow-y-auto prose prose-xs max-w-none prose-emerald prose-headings:text-emerald-800 prose-headings:text-sm prose-strong:text-gray-900 prose-li:my-0.5">
              <ReactMarkdown>{output}</ReactMarkdown>
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="mt-2 p-3 bg-red-50 rounded-lg border border-red-200">
            <div className="text-[10px] font-semibold text-red-600 mb-1.5">ERROR</div>
            <div className="text-xs text-red-700 font-mono">{error}</div>
          </div>
        )}
      </div>
    </div>
  );
}
