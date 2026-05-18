"use client";

import { Handle, Position } from "@xyflow/react";
import { Square } from "lucide-react";
import NodeDeleteButton from "./NodeDeleteButton";
import NodeStatusIndicator from "./NodeStatusIndicator";

export default function EndNode({ id, data, selected }: { id: string; data?: Record<string, unknown>; selected?: boolean }) {
  return (
    <div
      className={`group relative flex items-center gap-2 px-4 py-2.5 rounded-full border-2 bg-red-50 ${
        selected ? "border-red-500 shadow-md" : "border-red-300"
      }`}
    >
      <NodeStatusIndicator status={data?._runStatus as string | undefined} />
      <NodeDeleteButton nodeId={id} label="End" />
      <Handle type="target" position={Position.Left} className="!w-3 !h-3 !bg-red-500 !border-2 !border-white" />
      <Square className="w-4 h-4 text-red-600" />
      <span className="text-xs font-semibold text-red-700">End</span>
    </div>
  );
}
