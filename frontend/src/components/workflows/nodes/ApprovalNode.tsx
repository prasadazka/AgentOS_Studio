"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { ShieldCheck, ShieldOff } from "lucide-react";
import type { WorkflowNodeData } from "@/types";
import NodeDeleteButton from "./NodeDeleteButton";
import NodeStatusIndicator from "./NodeStatusIndicator";

export default function ApprovalNode({ id, data, selected }: NodeProps & { data: WorkflowNodeData }) {
  const autoApprove = !!data.autoApprove;

  return (
    <div
      className={`group relative min-w-[160px] rounded-lg border-2 bg-white shadow-sm ${
        selected ? "border-teal-500 shadow-md" : "border-teal-200"
      }`}
    >
      <NodeStatusIndicator status={data._runStatus as string | undefined} />
      <NodeDeleteButton nodeId={id} label={data.label || "Approval"} />
      <Handle type="target" position={Position.Left} className="!w-3 !h-3 !bg-teal-500 !border-2 !border-white" />
      <div className="flex items-center gap-2 px-3 py-1.5 bg-teal-50 rounded-t-md border-b border-teal-100">
        {autoApprove ? (
          <ShieldOff className="w-3.5 h-3.5 text-teal-400" />
        ) : (
          <ShieldCheck className="w-3.5 h-3.5 text-teal-600" />
        )}
        <span className="text-[10px] font-semibold text-teal-600 uppercase tracking-wide">Approval</span>
        {autoApprove && (
          <span className="text-[8px] px-1 py-0.5 bg-teal-500 text-white rounded font-bold uppercase">Auto</span>
        )}
      </div>
      <div className="px-3 py-2">
        <span className="text-xs font-medium text-gray-800">{data.label || "Human Approval"}</span>
        {data.approvalPrompt && (
          <div className="text-[10px] text-gray-500 mt-0.5 truncate max-w-[140px]">{data.approvalPrompt}</div>
        )}
      </div>
      <Handle type="source" position={Position.Right} className="!w-3 !h-3 !bg-teal-500 !border-2 !border-white" />
    </div>
  );
}
