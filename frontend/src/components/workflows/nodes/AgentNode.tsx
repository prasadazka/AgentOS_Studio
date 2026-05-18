"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Bot } from "lucide-react";
import type { WorkflowNodeData } from "@/types";
import NodeDeleteButton from "./NodeDeleteButton";
import NodeStatusIndicator from "./NodeStatusIndicator";

export default function AgentNode({ id, data, selected }: NodeProps & { data: WorkflowNodeData }) {
  return (
    <div
      className={`group relative min-w-[160px] rounded-lg border-2 bg-white shadow-sm ${
        selected ? "border-blue-500 shadow-md" : "border-blue-200"
      }`}
    >
      <NodeStatusIndicator status={data._runStatus as string | undefined} />
      <NodeDeleteButton nodeId={id} label={data.label || "Agent"} />
      <Handle type="target" position={Position.Left} className="!w-3 !h-3 !bg-blue-500 !border-2 !border-white" />
      <div className="flex items-center gap-2 px-3 py-1.5 bg-blue-50 rounded-t-md border-b border-blue-100">
        <Bot className="w-3.5 h-3.5 text-blue-600" />
        <span className="text-[10px] font-semibold text-blue-600 uppercase tracking-wide">Agent</span>
      </div>
      <div className="px-3 py-2">
        <span className="text-xs font-medium text-gray-800">{data.label || "Select Agent"}</span>
        {data.agentName && (
          <div className="text-[10px] text-gray-500 mt-0.5">{data.agentName}</div>
        )}
      </div>
      <Handle type="source" position={Position.Right} className="!w-3 !h-3 !bg-blue-500 !border-2 !border-white" />
    </div>
  );
}
