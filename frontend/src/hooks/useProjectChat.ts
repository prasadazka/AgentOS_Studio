"use client";

import { useState, useCallback, useEffect } from "react";
import { API_URL, api } from "@/lib/api";
import type { ChatMessage, ToolCall, ApprovalRequest } from "@/types";

let msgId = 0;
function nextId() {
  return `msg-${++msgId}-${Date.now()}`;
}

export function useProjectChat(
  projectId: string,
  sessionId: string | null,
  onSessionRenamed?: (sessionId: string, title: string) => void
) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [loaded, setLoaded] = useState(false);

  // Load existing messages when session changes
  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      setLoaded(true);
      return;
    }

    let cancelled = false;
    async function loadMessages() {
      try {
        const data = await api<{
          messages: {
            id: string;
            role: string;
            content: string;
            tool_calls_json: string | null;
            created_at: string;
          }[];
        }>(`/api/projects/${projectId}/sessions/${sessionId}/messages`);

        if (cancelled) return;

        const loaded: ChatMessage[] = data.messages.map((m) => ({
          id: m.id,
          role: m.role as "user" | "assistant",
          content: m.content,
          toolCalls: m.tool_calls_json ? JSON.parse(m.tool_calls_json) : undefined,
          timestamp: new Date(m.created_at),
        }));
        setMessages(loaded);
      } catch (e) {
        console.error("Failed to load messages:", e);
      } finally {
        if (!cancelled) setLoaded(true);
      }
    }

    setLoaded(false);
    loadMessages();
    return () => {
      cancelled = true;
    };
  }, [projectId, sessionId]);

  const sendMessage = useCallback(
    async (content: string) => {
      if (!sessionId) return;

      // Add user message
      const userMsg: ChatMessage = {
        id: nextId(),
        role: "user",
        content,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setIsStreaming(true);

      // Add empty assistant message
      const assistantId = nextId();
      setMessages((prev) => [
        ...prev,
        {
          id: assistantId,
          role: "assistant",
          content: "",
          isStreaming: true,
          toolCalls: [],
          timestamp: new Date(),
        },
      ]);

      let fullContent = "";
      const toolCalls: ToolCall[] = [];
      const streamStart = Date.now();

      try {
        const response = await fetch(
          `${API_URL}/api/projects/${encodeURIComponent(projectId)}/chat`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: content, session_id: sessionId }),
          }
        );

        if (!response.ok) {
          const errText = await response.text().catch(() => "");
          throw new Error(
            `HTTP ${response.status}${errText ? `: ${errText}` : ""}`
          );
        }

        if (!response.body) {
          throw new Error("No response body");
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const raw = line.slice(6).trim();
            if (!raw) continue;

            try {
              const data = JSON.parse(raw);

              switch (data.type) {
                case "token":
                  fullContent = data.content;
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId
                        ? { ...m, content: fullContent, toolCalls: [...toolCalls] }
                        : m
                    )
                  );
                  break;

                case "tool_call": {
                  const tc: ToolCall = {
                    name: data.name,
                    args: data.args,
                    status: "running",
                  };
                  toolCalls.push(tc);
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId
                        ? { ...m, toolCalls: [...toolCalls] }
                        : m
                    )
                  );
                  break;
                }

                case "tool_result": {
                  const lastTc = toolCalls[toolCalls.length - 1];
                  if (lastTc) {
                    lastTc.result = data.content;
                    lastTc.status = "done";
                  }
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId
                        ? { ...m, toolCalls: [...toolCalls] }
                        : m
                    )
                  );
                  break;
                }

                case "error":
                  fullContent = fullContent
                    ? `${fullContent}\n\nError: ${data.message}`
                    : `Error: ${data.message}`;
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId
                        ? { ...m, content: fullContent, isStreaming: false }
                        : m
                    )
                  );
                  break;

                case "approval_required": {
                  const approval: ApprovalRequest = {
                    token: data.token,
                    rowCount: data.row_count,
                    tableCount: data.table_count,
                    status: "pending",
                  };
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId
                        ? { ...m, approvalRequest: approval }
                        : m
                    )
                  );
                  break;
                }

                case "session_renamed":
                  onSessionRenamed?.(data.session_id, data.title);
                  break;

                case "done":
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId
                        ? { ...m, isStreaming: false, latencyMs: Date.now() - streamStart }
                        : m
                    )
                  );
                  break;
              }
            } catch {
              // skip malformed JSON
            }
          }
        }

        // Finalize if stream ended without "done"
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId && m.isStreaming
              ? { ...m, isStreaming: false, latencyMs: m.latencyMs ?? (Date.now() - streamStart) }
              : m
          )
        );
      } catch (e) {
        const errorMsg = e instanceof Error ? e.message : "Connection failed";
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? {
                  ...m,
                  content: fullContent
                    ? `${fullContent}\n\nError: ${errorMsg}`
                    : `Error: ${errorMsg}`,
                  isStreaming: false,
                }
              : m
          )
        );
      } finally {
        setIsStreaming(false);
      }
    },
    [projectId, sessionId, onSessionRenamed]
  );

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  return { messages, setMessages, sendMessage, isStreaming, loaded, clearMessages };
}
