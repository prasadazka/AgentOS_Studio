"use client";

import { useState, useRef, useEffect } from "react";
import { Plus, MessageSquare, Trash2, Pencil, Check, X } from "lucide-react";
import type { ChatSession } from "@/types";
import { cn } from "@/lib/utils";

export default function SessionSidebar({
  sessions,
  activeId,
  onSelect,
  onCreate,
  onDelete,
  onRename,
  onClearAll,
}: {
  sessions: ChatSession[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onClearAll?: () => void;
}) {
  return (
    <div className="w-60 border-r border-[var(--border-light)] bg-white flex flex-col h-full">
      <div className="p-3 border-b border-[var(--border-light)] space-y-2">
        <button
          onClick={onCreate}
          className="flex items-center gap-2 w-full px-3 py-2 text-sm font-medium text-gray-700 bg-gray-50 hover:bg-gray-100 rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Chat
        </button>
        {onClearAll && sessions.length > 0 && (
          <button
            type="button"
            onClick={onClearAll}
            className="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
          >
            <Trash2 className="w-3 h-3" />
            Clear All History
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto py-2 px-2">
        {sessions.length === 0 ? (
          <p className="text-xs text-gray-400 text-center py-4">
            No chat sessions yet
          </p>
        ) : (
          sessions.map((s) => (
            <SessionItem
              key={s.id}
              session={s}
              isActive={activeId === s.id}
              onSelect={onSelect}
              onDelete={onDelete}
              onRename={onRename}
            />
          ))
        )}
      </div>
    </div>
  );
}

function SessionItem({
  session,
  isActive,
  onSelect,
  onDelete,
  onRename,
}: {
  session: ChatSession;
  isActive: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(session.title);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  function handleSave() {
    const trimmed = draft.trim();
    if (trimmed && trimmed !== session.title) {
      onRename(session.id, trimmed);
    }
    setEditing(false);
  }

  function handleCancel() {
    setDraft(session.title);
    setEditing(false);
  }

  if (editing) {
    return (
      <div className="flex items-center gap-1 px-2 py-1.5 mb-0.5 rounded-lg bg-primary-50">
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSave();
            if (e.key === "Escape") handleCancel();
          }}
          className="flex-1 min-w-0 text-sm bg-white border border-primary-200 rounded px-2 py-1 outline-none focus:border-primary-400"
        />
        <button onClick={handleSave} className="p-0.5 text-green-600 hover:text-green-700">
          <Check className="w-3.5 h-3.5" />
        </button>
        <button onClick={handleCancel} className="p-0.5 text-gray-400 hover:text-gray-600">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer text-sm mb-0.5 transition-colors",
        isActive
          ? "bg-primary-50 text-primary-700"
          : "text-gray-700 hover:bg-gray-50"
      )}
      onClick={() => onSelect(session.id)}
    >
      <MessageSquare className="w-3.5 h-3.5 flex-shrink-0" />
      <span className="flex-1 truncate">{session.title}</span>
      <div className="hidden group-hover:flex items-center gap-0.5">
        <button
          onClick={(e) => {
            e.stopPropagation();
            setDraft(session.title);
            setEditing(true);
          }}
          className="p-0.5 text-gray-400 hover:text-primary-600"
          title="Rename"
        >
          <Pencil className="w-3 h-3" />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete(session.id);
          }}
          className="p-0.5 text-gray-400 hover:text-red-500"
          title="Delete"
        >
          <Trash2 className="w-3 h-3" />
        </button>
      </div>
    </div>
  );
}
