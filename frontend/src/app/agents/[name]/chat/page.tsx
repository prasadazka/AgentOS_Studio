"use client";

import { useParams } from "next/navigation";
import { useRef, useEffect, useCallback } from "react";
import Link from "next/link";
import { ArrowLeft, Bot, Trash2 } from "lucide-react";
import MessageBubble from "@/components/chat/MessageBubble";
import ChatInput from "@/components/chat/ChatInput";
import { useChat } from "@/hooks/useChat";

export default function ChatPage() {
  const params = useParams();
  const name = params.name as string;
  const { messages, setMessages, sendMessage, isStreaming, clearMessages } = useChat(name);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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

  return (
    <div className="flex flex-col h-full">
      {/* Chat Header */}
      <div className="h-14 bg-white border-b border-[var(--border-light)] flex items-center justify-between px-4">
        <div className="flex items-center gap-3">
          <Link
            href={`/agents/${name}`}
            className="p-1.5 rounded-lg hover:bg-gray-50 text-gray-500 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div className="w-8 h-8 rounded-lg bg-primary-50 flex items-center justify-center">
            <Bot className="w-4 h-4 text-primary-600" />
          </div>
          <div>
            <h1 className="text-sm font-semibold text-gray-900">{name}</h1>
            <p className="text-xs text-gray-500">
              {isStreaming ? "Thinking..." : "Online"}
            </p>
          </div>
        </div>

        <button
          onClick={clearMessages}
          className="p-2 rounded-lg hover:bg-gray-50 text-gray-400 hover:text-gray-600 transition-colors"
          title="Clear chat"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto bg-[var(--bg-secondary)]">
        <div className="max-w-3xl mx-auto py-6 px-4 space-y-4">
          {messages.length === 0 && (
            <div className="text-center py-20">
              <div className="w-16 h-16 rounded-2xl bg-primary-50 flex items-center justify-center mx-auto mb-4">
                <Bot className="w-8 h-8 text-primary-600" />
              </div>
              <h2 className="text-lg font-semibold text-gray-900 mb-1">
                Chat with {name}
              </h2>
              <p className="text-sm text-gray-500">
                Send a message to start the conversation.
              </p>
            </div>
          )}

          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} onApprove={handleApprove} onDeny={handleDeny} />
          ))}

          <div ref={bottomRef} />
        </div>
      </div>

      {/* Input */}
      <ChatInput onSend={sendMessage} disabled={isStreaming} />
    </div>
  );
}