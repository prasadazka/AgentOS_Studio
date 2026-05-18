"use client";

import { Play, Square, Bot, Wrench, GitBranch, ShieldCheck, GripVertical } from "lucide-react";
import type { Node } from "@xyflow/react";
import type { WorkflowNodeType } from "@/types";

const MAX_NODES = 25;

const NODE_TYPES: { type: WorkflowNodeType; label: string; icon: typeof Play; color: string; description: string }[] = [
  { type: "start", label: "Start", icon: Play, color: "emerald", description: "Entry point" },
  { type: "end", label: "End", icon: Square, color: "red", description: "Exit point" },
  { type: "agent", label: "Agent", icon: Bot, color: "blue", description: "Run an AI agent" },
  { type: "tool", label: "Tool", icon: Wrench, color: "purple", description: "Execute a tool" },
  { type: "condition", label: "Condition", icon: GitBranch, color: "amber", description: "Branch logic" },
  { type: "approval", label: "Approval", icon: ShieldCheck, color: "teal", description: "Human approval" },
];

const COLOR_MAP: Record<string, string> = {
  emerald: "bg-emerald-50 border-emerald-200 text-emerald-700 hover:border-emerald-400",
  red: "bg-red-50 border-red-200 text-red-700 hover:border-red-400",
  blue: "bg-blue-50 border-blue-200 text-blue-700 hover:border-blue-400",
  purple: "bg-purple-50 border-purple-200 text-purple-700 hover:border-purple-400",
  amber: "bg-amber-50 border-amber-200 text-amber-700 hover:border-amber-400",
  teal: "bg-teal-50 border-teal-200 text-teal-700 hover:border-teal-400",
};

const DISABLED_CLASS = "opacity-40 cursor-not-allowed border-gray-200 bg-gray-50 text-gray-400 hover:border-gray-200";

interface NodePaletteProps {
  nodes?: Node[];
}

export default function NodePalette({ nodes = [] }: NodePaletteProps) {
  const nodeCount = nodes.length;
  const atLimit = nodeCount >= MAX_NODES;
  const hasStart = nodes.some((n) => n.data?.type === "start" || n.type === "start");
  const hasEnd = nodes.some((n) => n.data?.type === "end" || n.type === "end");

  function isDisabled(type: WorkflowNodeType): boolean {
    if (atLimit) return true;
    if (type === "start" && hasStart) return true;
    if (type === "end" && hasEnd) return true;
    return false;
  }

  function disabledReason(type: WorkflowNodeType): string | null {
    if (atLimit) return `Limit reached (${MAX_NODES})`;
    if (type === "start" && hasStart) return "Already added";
    if (type === "end" && hasEnd) return "Already added";
    return null;
  }

  function onDragStart(e: React.DragEvent, nodeType: WorkflowNodeType) {
    if (isDisabled(nodeType)) {
      e.preventDefault();
      return;
    }
    e.dataTransfer.setData("application/workflow-node", nodeType);
    e.dataTransfer.effectAllowed = "move";
  }

  return (
    <div className="w-52 border-r border-[var(--border-light)] bg-white flex flex-col h-full flex-shrink-0">
      <div className="px-3 py-3 border-b border-[var(--border-light)] flex items-center justify-between">
        <span className="text-xs font-semibold text-gray-700">Node Palette</span>
        <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${atLimit ? "bg-red-100 text-red-600" : "bg-gray-100 text-gray-500"}`}>
          {nodeCount} / {MAX_NODES}
        </span>
      </div>

      {/* How-to hint */}
      <div className="px-3 py-2 bg-blue-50 border-b border-blue-100">
        <div className="text-[10px] text-blue-600 leading-relaxed">
          <strong>How to build:</strong>
          <ol className="mt-1 space-y-0.5 list-decimal list-inside">
            <li>Drag nodes onto canvas</li>
            <li>Connect handles (dots) between nodes</li>
            <li>Click a node to configure it</li>
            <li>Save, then Run</li>
          </ol>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
        {NODE_TYPES.map((node) => {
          const disabled = isDisabled(node.type);
          const reason = disabledReason(node.type);

          return (
            <div
              key={node.type}
              draggable={!disabled}
              onDragStart={(e) => onDragStart(e, node.type)}
              title={reason || node.description}
              className={`flex items-center gap-2 px-3 py-2.5 rounded-lg border transition-colors ${
                disabled
                  ? DISABLED_CLASS
                  : `cursor-grab active:cursor-grabbing ${COLOR_MAP[node.color]}`
              }`}
            >
              <GripVertical className="w-3 h-3 opacity-40 flex-shrink-0" />
              <node.icon className="w-4 h-4 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium flex items-center gap-1">
                  {node.label}
                  {reason && <span className="text-[9px] font-normal opacity-60">({reason})</span>}
                </div>
                <div className="text-[10px] opacity-70">{node.description}</div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Keyboard shortcuts */}
      <div className="px-3 py-2 border-t border-[var(--border-light)] text-[10px] text-gray-400 space-y-0.5">
        <div><kbd className="px-1 py-0.5 bg-gray-100 rounded text-[9px]">Backspace</kbd> Delete selected</div>
        <div><kbd className="px-1 py-0.5 bg-gray-100 rounded text-[9px]">Ctrl+S</kbd> Save workflow</div>
      </div>
    </div>
  );
}
