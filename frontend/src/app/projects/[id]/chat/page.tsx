"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, FolderOpen, PanelRightClose, PanelRightOpen } from "lucide-react";
import SessionSidebar from "@/components/projects/SessionSidebar";
import ProjectFilesPanel from "@/components/projects/ProjectFilesPanel";
import MessageBubble from "@/components/chat/MessageBubble";
import ChatInput from "@/components/chat/ChatInput";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useProjectChat } from "@/hooks/useProjectChat";
import { api } from "@/lib/api";
import type { Project, ChatSession } from "@/types";

export default function ProjectChatPage() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [initializing, setInitializing] = useState(true);
  const [filesOpen, setFilesOpen] = useState(true);
  const [deleteSessionTarget, setDeleteSessionTarget] = useState<ChatSession | null>(null);
  const [showClearAll, setShowClearAll] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Update session title when auto-renamed by backend
  const updateSessionTitle = useCallback((sid: string, title: string) => {
    setSessions((prev) =>
      prev.map((s) => (s.id === sid ? { ...s, title } : s))
    );
  }, []);

  const { messages, setMessages, sendMessage, isStreaming, loaded } = useProjectChat(
    id,
    activeSessionId,
    updateSessionTitle
  );

  const handleApprove = useCallback((token: string) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.approvalRequest?.token === token
          ? { ...m, approvalRequest: { ...m.approvalRequest, status: "approved" as const } }
          : m
      )
    );
    sendMessage(`APPROVED: Proceed with the push. Approval token: ${token}`);
  }, [setMessages, sendMessage]);

  const handleDeny = useCallback((token: string) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.approvalRequest?.token === token
          ? { ...m, approvalRequest: { ...m.approvalRequest, status: "denied" as const } }
          : m
      )
    );
    sendMessage("DENIED: Do not proceed with the push. The user has rejected this operation.");
  }, [setMessages, sendMessage]);

  // Load project + sessions on mount
  const loadSessions = useCallback(async () => {
    try {
      const data = await api<{ sessions: ChatSession[] }>(
        `/api/projects/${id}/sessions`
      );
      setSessions(data.sessions);
      return data.sessions;
    } catch (e) {
      console.error("Failed to load sessions:", e);
      return [];
    }
  }, [id]);

  useEffect(() => {
    async function init() {
      try {
        const [proj, sessionsData] = await Promise.all([
          api<Project>(`/api/projects/${id}`),
          loadSessions(),
        ]);
        setProject(proj);

        // Auto-create first session if none
        if (sessionsData.length === 0) {
          const newSession = await api<ChatSession>(
            `/api/projects/${id}/sessions`,
            { method: "POST" }
          );
          setSessions([newSession]);
          setActiveSessionId(newSession.id);
        } else {
          setActiveSessionId(sessionsData[0].id);
        }
      } catch (e) {
        console.error("Failed to init project chat:", e);
      } finally {
        setInitializing(false);
      }
    }
    init();
  }, [id, loadSessions]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleNewSession() {
    try {
      const newSession = await api<ChatSession>(
        `/api/projects/${id}/sessions`,
        { method: "POST" }
      );
      setSessions((prev) => [newSession, ...prev]);
      setActiveSessionId(newSession.id);
    } catch (e) {
      console.error("Failed to create session:", e);
    }
  }

  async function handleRenameSession(sid: string, title: string) {
    try {
      await api(`/api/projects/${id}/sessions/${sid}`, {
        method: "PATCH",
        body: JSON.stringify({ title }),
      });
      setSessions((prev) =>
        prev.map((s) => (s.id === sid ? { ...s, title } : s))
      );
    } catch (e) {
      console.error("Failed to rename session:", e);
    }
  }

  function handleDeleteSession(sid: string) {
    const s = sessions.find((ses) => ses.id === sid);
    if (s) setDeleteSessionTarget(s);
  }

  async function confirmDeleteSession() {
    if (!deleteSessionTarget) return;
    const sid = deleteSessionTarget.id;
    try {
      await api(`/api/projects/${id}/sessions/${sid}`, { method: "DELETE" });
      setSessions((prev) => prev.filter((s) => s.id !== sid));
      if (activeSessionId === sid) {
        const remaining = sessions.filter((s) => s.id !== sid);
        setActiveSessionId(remaining.length > 0 ? remaining[0].id : null);
      }
    } catch (e) {
      console.error("Failed to delete session:", e);
    } finally {
      setDeleteSessionTarget(null);
    }
  }

  async function confirmClearAll() {
    try {
      await api(`/api/projects/${id}/sessions`, { method: "DELETE" });
      setSessions([]);
      setActiveSessionId(null);
      setMessages([]);
    } catch (e) {
      console.error("Failed to clear all sessions:", e);
    } finally {
      setShowClearAll(false);
    }
  }

  if (initializing) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-sm text-gray-400">Loading project...</div>
      </div>
    );
  }

  return (
    <div className="flex h-full">
      {/* Session sidebar */}
      <SessionSidebar
        sessions={sessions}
        activeId={activeSessionId}
        onSelect={setActiveSessionId}
        onCreate={handleNewSession}
        onDelete={handleDeleteSession}
        onRename={handleRenameSession}
        onClearAll={() => setShowClearAll(true)}
      />

      {/* Chat area */}
      <div className="flex-1 flex flex-col h-full min-w-0">
        {/* Header */}
        <div className="h-14 bg-white border-b border-[var(--border-light)] flex items-center px-6 gap-3">
          <Link
            href={`/projects/${id}`}
            className="text-gray-400 hover:text-gray-600"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <FolderOpen className="w-4 h-4 text-blue-600" />
          <span className="font-semibold text-sm text-gray-900">
            {project?.name || "Project"}
          </span>
          <span className="text-xs text-gray-400">
            {project?.agent_name}
          </span>
          <div className="flex-1" />
          <button
            onClick={() => setFilesOpen(!filesOpen)}
            className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-md transition-colors"
            title={filesOpen ? "Hide files" : "Show files"}
          >
            {filesOpen ? (
              <PanelRightClose className="w-4 h-4" />
            ) : (
              <PanelRightOpen className="w-4 h-4" />
            )}
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4 bg-gray-50">
          {!loaded ? (
            <div className="text-center text-sm text-gray-400 py-8">
              Loading messages...
            </div>
          ) : messages.length === 0 ? (
            <div className="text-center text-sm text-gray-400 py-8">
              Upload files in the project details page, then ask questions here.
            </div>
          ) : (
            messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} onApprove={handleApprove} onDeny={handleDeny} />
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <ChatInput onSend={sendMessage} disabled={isStreaming || !activeSessionId} />
      </div>

      {/* Files panel */}
      {filesOpen && <ProjectFilesPanel projectId={id} />}

      <ConfirmDialog
        open={!!deleteSessionTarget}
        title="Delete Chat"
        message={`Are you sure you want to delete "${deleteSessionTarget?.title || "Untitled chat"}"? All messages in this chat will be lost.`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={confirmDeleteSession}
        onCancel={() => setDeleteSessionTarget(null)}
      />

      <ConfirmDialog
        open={showClearAll}
        title="Clear All Chat History"
        message={`This will permanently delete all ${sessions.length} chat session${sessions.length !== 1 ? "s" : ""} and their messages. This cannot be undone.`}
        confirmLabel="Clear All"
        variant="danger"
        onConfirm={confirmClearAll}
        onCancel={() => setShowClearAll(false)}
      />
    </div>
  );
}
