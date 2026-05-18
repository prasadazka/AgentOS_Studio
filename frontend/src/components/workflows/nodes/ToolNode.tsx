"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Wrench } from "lucide-react";
import type { WorkflowNodeData } from "@/types";
import NodeDeleteButton from "./NodeDeleteButton";
import NodeStatusIndicator from "./NodeStatusIndicator";

export default function ToolNode({ id, data, selected }: NodeProps & { data: WorkflowNodeData }) {
  return (
    <div
      className={`group relative min-w-[160px] rounded-lg border-2 bg-white shadow-sm ${
        selected ? "border-purple-500 shadow-md" : "border-purple-200"
      }`}
    >
      <NodeStatusIndicator status={data._runStatus as string | undefined} />
      <NodeDeleteButton nodeId={id} label={data.label || "Tool"} />
      <Handle type="target" position={Position.Left} className="!w-3 !h-3 !bg-purple-500 !border-2 !border-white" />
      <div className="flex items-center gap-2 px-3 py-1.5 bg-purple-50 rounded-t-md border-b border-purple-100">
        <Wrench className="w-3.5 h-3.5 text-purple-600" />
        <span className="text-[10px] font-semibold text-purple-600 uppercase tracking-wide">Tool</span>
      </div>
      <div className="px-3 py-2">
        <span className="text-xs font-medium text-gray-800">{data.label || "Select Tool"}</span>
        {data.toolName && (
          <div className="text-[10px] text-gray-500 mt-0.5">{data.toolName}</div>
        )}
      </div>
      <Handle type="source" position={Position.Right} className="!w-3 !h-3 !bg-purple-500 !border-2 !border-white" />
    </div>
  );
}
