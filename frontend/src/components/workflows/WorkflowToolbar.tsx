"use client";

import { useState } from "react";
import { Save, Play, Loader2, ArrowLeft, ToggleLeft, ToggleRight, CheckCircle2, CloudOff } from "lucide-react";
import Link from "next/link";

const STATUS_BADGES: Record<string, string> = {
  draft: "bg-gray-100 text-gray-600",
  ready: "bg-blue-100 text-blue-600",
  running: "bg-amber-100 text-amber-600",
  paused: "bg-orange-100 text-orange-600",
  completed: "bg-emerald-100 text-emerald-600",
  error: "bg-red-100 text-red-600",
};

interface WorkflowToolbarProps {
  name: string;
  status: string;
  onNameChange: (name: string) => void;
  onSave: () => Promise<void>;
  onRun: () => void;
  isSaving: boolean;
  isRunning: boolean;
  autoSave: boolean;
  onAutoSaveToggle: () => void;
  saveToast: "saved" | "off" | null;
}

export default function WorkflowToolbar({
  name,
  status,
  onNameChange,
  onSave,
  onRun,
  isSaving,
  isRunning,
  autoSave,
  onAutoSaveToggle,
  saveToast,
}: WorkflowToolbarProps) {
  const [editing, setEditing] = useState(false);
  const badgeClass = STATUS_BADGES[status] || STATUS_BADGES.draft;

  return (
    <div className="h-12 flex items-center justify-between px-3 border-b border-[var(--border-light)] bg-white flex-shrink-0 relative">
      <div className="flex items-center gap-3">
        <Link href="/workflows" className="p-1.5 text-gray-400 hover:text-gray-600 rounded transition-colors">
          <ArrowLeft className="w-4 h-4" />
        </Link>

        {editing ? (
          <input
            type="text"
            value={name}
            onChange={(e) => onNameChange(e.target.value)}
            onBlur={() => setEditing(false)}
            onKeyDown={(e) => e.key === "Enter" && setEditing(false)}
            autoFocus
            className="text-sm font-semibold text-gray-900 px-2 py-1 border border-primary-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 w-60"
          />
        ) : (
          <button type="button" onClick={() => setEditing(true)} className="text-sm font-semibold text-gray-900 hover:text-primary-600 transition-colors">
            {name || "Untitled Workflow"}
          </button>
        )}

        <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${badgeClass}`}>
          {status}
        </span>
      </div>

      {/* Save toast — centered */}
      {saveToast && (
        <div
          className={`absolute left-1/2 -translate-x-1/2 flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] font-medium shadow-sm border animate-fade-in-down ${
            saveToast === "saved"
              ? "bg-emerald-50 border-emerald-200 text-emerald-700"
              : "bg-gray-50 border-gray-200 text-gray-500"
          }`}
        >
          {saveToast === "saved" ? (
            <><CheckCircle2 className="w-3 h-3" /> Saved</>
          ) : (
            <><CloudOff className="w-3 h-3" /> Auto-save off</>
          )}
        </div>
      )}

      <div className="flex items-center gap-2">
        {/* Auto-save toggle */}
        <button
          type="button"
          onClick={onAutoSaveToggle}
          title={autoSave ? "Auto-save on — click to disable" : "Auto-save off — click to enable"}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
            autoSave
              ? "text-emerald-700 bg-emerald-50 border-emerald-200 hover:bg-emerald-100"
              : "text-gray-500 bg-gray-50 border-gray-200 hover:bg-gray-100"
          }`}
        >
          {autoSave ? (
            <ToggleRight className="w-4 h-4" />
          ) : (
            <ToggleLeft className="w-4 h-4" />
          )}
          <span className="hidden sm:inline">Auto-save</span>
        </button>

        <button
          type="button"
          onClick={onSave}
          disabled={isSaving}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-[var(--border-light)] rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
        >
          {isSaving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
          Save
        </button>
        <button
          type="button"
          onClick={onRun}
          disabled={isRunning}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700 transition-colors disabled:opacity-50"
        >
          {isRunning ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
          Run
        </button>
      </div>
    </div>
  );
}
