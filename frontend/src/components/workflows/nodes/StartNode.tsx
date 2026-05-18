"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Play, FormInput } from "lucide-react";
import type { WorkflowNodeData } from "@/types";
import NodeDeleteButton from "./NodeDeleteButton";
import NodeStatusIndicator from "./NodeStatusIndicator";

export default function StartNode({ id, data, selected }: NodeProps & { data: WorkflowNodeData }) {
  const fieldCount = (data.inputFields as unknown[])?.length || 0;

  return (
    <div
      className={`group relative rounded-lg border-2 bg-white shadow-sm ${
        selected ? "border-emerald-500 shadow-md" : "border-emerald-300"
      }`}
    >
      <NodeStatusIndicator status={(data._runStatus as string | undefined)} />
      <NodeDeleteButton nodeId={id} label="Start" />

      <div className="flex items-center gap-2 px-4 py-2.5 bg-emerald-50 rounded-t-md border-b border-emerald-100">
        <Play className="w-4 h-4 text-emerald-600" />
        <span className="text-xs font-semibold text-emerald-700">Start</span>
      </div>

      {fieldCount > 0 ? (
        <div className="px-3 py-2 space-y-0.5">
          <div className="flex items-center gap-1 text-[10px] text-emerald-600">
            <FormInput className="w-3 h-3" />
            <span className="font-medium">{fieldCount} input field{fieldCount > 1 ? "s" : ""}</span>
          </div>
          {((data.inputFields as { label: string }[]) || []).slice(0, 3).map((f, i) => (
            <div key={i} className="text-[10px] text-gray-500 truncate max-w-[140px]">
              {f.label}
            </div>
          ))}
          {fieldCount > 3 && (
            <div className="text-[9px] text-gray-400">+{fieldCount - 3} more</div>
          )}
        </div>
      ) : (
        <div className="px-3 py-1.5">
          <div className="text-[10px] text-gray-400 italic">Click to add input fields</div>
        </div>
      )}

      <Handle type="source" position={Position.Right} className="!w-3 !h-3 !bg-emerald-500 !border-2 !border-white" />
    </div>
  );
}
