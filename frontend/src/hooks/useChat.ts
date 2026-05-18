"use client";

import { useState, useCallback } from "react";
import { API_URL } from "@/lib/api";
import type { ChatMessage, ToolCall, ApprovalRequest } from "@/types";

let msgId = 0;
function nextId() {
  return `msg-${++msgId}-${Date.now()}`;
}

export function useChat(agentName: string) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentToolCall, setCurrentToolCall] = useState<ToolCall | null>(null);

  const sendMessage = useCallback(
    async (content: string) => {
      // Add user message
      const userMsg: ChatMessage = {
        id: nextId(),
        role: "user",
        content,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setIsStreaming(true);
      setCurrentToolCall(null);

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

      try {
        const response = await fetch(
          `${API_URL}/api/agents/${encodeURIComponent(agentName)}/chat`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: content }),
          }
        );

        if (!response.ok) {
          const errText = await response.text().catch(() => "");
          throw new Error(
            `HTTP ${response.status}${errText ? `: ${errText}` : ""}`
          );
        }

        if (!response.body) {
          throw new Error("No response body - streaming not supported");
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
                  // Replace content (backend sends full AI response each time)
                  fullContent = data.content;
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId
                        ? {
                            ...m,
                            content: fullContent,
                            toolCalls: [...toolCalls],
                          }
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
                  setCurrentToolCall(tc);
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
                  setCurrentToolCall(null);
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId
                        ? { ...m, toolCalls: [...toolCalls] }
                        : m
                    )
                  );
                  break;
                }

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

                case "error":
                  fullContent =
                    fullContent
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

                case "done":
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId
                        ? { ...m, isStreaming: false }
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

        // If stream ended without a "done" event, finalize
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId && m.isStreaming
              ? { ...m, isStreaming: false }
              : m
          )
        );
      } catch (e) {
        const errorMsg =
          e instanceof Error ? e.message : "Connection failed";
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
        setCurrentToolCall(null);
      }
    },
    [agentName]
  );

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  return { messages, setMessages, sendMessage, isStreaming, currentToolCall, clearMessages };
}