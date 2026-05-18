"use client";

import { Loader2, Check, X, Clock } from "lucide-react";

interface NodeStatusIndicatorProps {
  status?: string; // "running" | "completed" | "error" | "pending"
}

export default function NodeStatusIndicator({ status }: NodeStatusIndicatorProps) {
  if (!status) return null;

  return (
    <>
      {/* Full-node overlay tint */}
      {status === "running" && (
        <div className="absolute inset-0 rounded-lg pointer-events-none z-10 border-2 border-blue-400 border-dashed animate-pulse bg-blue-50/40" />
      )}
      {status === "completed" && (
        <div className="absolute inset-0 rounded-lg pointer-events-none z-10 border-2 border-emerald-500 bg-emerald-50/30" />
      )}
      {status === "error" && (
        <div className="absolute inset-0 rounded-lg pointer-events-none z-10 border-2 border-red-500 bg-red-50/30" />
      )}

      {/* Large status badge — top-right */}
      <div className={`absolute -top-3 -right-3 z-20 flex items-center justify-center rounded-full shadow-lg border-2 border-white ${
        status === "running" ? "w-7 h-7 bg-blue-500" :
        status === "completed" ? "w-7 h-7 bg-emerald-500" :
        status === "error" ? "w-7 h-7 bg-red-500" :
        "w-6 h-6 bg-gray-400"
      }`}>
        {status === "running" && (
          <Loader2 className="w-4 h-4 text-white animate-spin" />
        )}
        {status === "completed" && (
          <Check className="w-4.5 h-4.5 text-white" strokeWidth={3} />
        )}
        {status === "error" && (
          <X className="w-4.5 h-4.5 text-white" strokeWidth={3} />
        )}
        {status === "pending" && (
          <Clock className="w-3.5 h-3.5 text-white" />
        )}
      </div>

      {/* Status label below node */}
      <div className={`absolute -bottom-6 left-1/2 -translate-x-1/2 z-20 px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider whitespace-nowrap shadow-sm ${
        status === "running" ? "bg-blue-500 text-white" :
        status === "completed" ? "bg-emerald-500 text-white" :
        status === "error" ? "bg-red-500 text-white" :
        "bg-gray-400 text-white"
      }`}>
        {status === "running" && (
          <span className="flex items-center gap-1">
            <span className="inline-block w-1 h-1 rounded-full bg-white animate-pulse" />
            Running
          </span>
        )}
        {status === "completed" && "Done"}
        {status === "error" && "Failed"}
        {status === "pending" && "Waiting"}
      </div>
    </>
  );
}
