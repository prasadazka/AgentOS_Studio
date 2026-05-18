"use client";

import { useState, useRef, useEffect } from "react";
import { useReactFlow } from "@xyflow/react";
import { X } from "lucide-react";

interface NodeDeleteButtonProps {
  nodeId: string;
  label?: string;
}

export default function NodeDeleteButton({ nodeId, label }: NodeDeleteButtonProps) {
  const { deleteElements } = useReactFlow();
  const [showConfirm, setShowConfirm] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on click outside
  useEffect(() => {
    if (!showConfirm) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setShowConfirm(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showConfirm]);

  return (
    <div ref={ref} className="absolute -top-2.5 -right-2.5 z-10">
      {/* X button */}
      <button
        type="button"
        title="Delete node"
        onClick={(e) => { e.stopPropagation(); setShowConfirm(true); }}
        className="w-5 h-5 bg-red-500 hover:bg-red-600 text-white rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity shadow-sm"
      >
        <X className="w-3 h-3" />
      </button>

      {/* Confirmation popover */}
      {showConfirm && (
        <div className="absolute top-7 right-0 bg-white rounded-lg shadow-lg border border-[var(--border-light)] p-3 min-w-[180px]">
          <p className="text-xs text-gray-700 mb-2">
            Delete <strong>{label || "this node"}</strong>?
          </p>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                deleteElements({ nodes: [{ id: nodeId }] });
                setShowConfirm(false);
              }}
              className="flex-1 px-2 py-1.5 text-[11px] font-medium text-white bg-red-500 hover:bg-red-600 rounded-md transition-colors"
            >
              Delete
            </button>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); setShowConfirm(false); }}
              className="flex-1 px-2 py-1.5 text-[11px] font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 rounded-md transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
