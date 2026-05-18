"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { GitBranch } from "lucide-react";
import type { WorkflowNodeData } from "@/types";
import NodeDeleteButton from "./NodeDeleteButton";
import NodeStatusIndicator from "./NodeStatusIndicator";

export default function ConditionNode({ id, data, selected }: NodeProps & { data: WorkflowNodeData }) {
  return (
    <div
      className={`group relative min-w-[160px] rounded-lg border-2 bg-white shadow-sm ${
        selected ? "border-amber-500 shadow-md" : "border-amber-200"
      }`}
    >
      <NodeStatusIndicator status={data._runStatus as string | undefined} />
      <NodeDeleteButton nodeId={id} label={data.label || "Condition"} />
      <Handle type="target" position={Position.Left} className="!w-3 !h-3 !bg-amber-500 !border-2 !border-white" />
      <div className="flex items-center gap-2 px-3 py-1.5 bg-amber-50 rounded-t-md border-b border-amber-100">
        <GitBranch className="w-3.5 h-3.5 text-amber-600" />
        <span className="text-[10px] font-semibold text-amber-600 uppercase tracking-wide">Condition</span>
      </div>
      <div className="px-3 py-2">
        <span className="text-xs font-medium text-gray-800">{data.label || "Condition"}</span>
        {data.expression && (
          <div className="text-[10px] text-gray-500 mt-0.5 font-mono">{data.expression}</div>
        )}
      </div>
      <Handle type="source" position={Position.Right} id="true" style={{ top: "35%" }} className="!w-3 !h-3 !bg-emerald-500 !border-2 !border-white" />
      <Handle type="source" position={Position.Right} id="false" style={{ top: "65%" }} className="!w-3 !h-3 !bg-red-500 !border-2 !border-white" />
      {/* Labels for handles */}
      <div className="absolute right-[-30px] text-[9px] font-medium text-emerald-600" style={{ top: "28%" }}>True</div>
      <div className="absolute right-[-32px] text-[9px] font-medium text-red-600" style={{ top: "60%" }}>False</div>
    </div>
  );
}
