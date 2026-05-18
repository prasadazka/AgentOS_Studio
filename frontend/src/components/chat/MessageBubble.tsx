"use client";

import { Bot, User, Wrench, ChevronDown, ChevronRight, Clock, Copy, Check, XCircle, ShieldCheck } from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import dynamic from "next/dynamic";
import type { ChatMessage } from "@/types";

const ChartRenderer = dynamic(() => import("./ChartRenderer"), { ssr: false });

interface MessageBubbleProps {
  message: ChatMessage;
  onApprove?: (token: string) => void;
  onDeny?: (token: string) => void;
}

export default function MessageBubble({ message, onApprove, onDeny }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const [copied, setCopied] = useState(false);
  const [hovered, setHovered] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(message.content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && (
        <div className="w-8 h-8 rounded-lg bg-primary-50 flex items-center justify-center flex-shrink-0 mt-0.5">
          <Bot className="w-4 h-4 text-primary-600" />
        </div>
      )}

      <div
        className={`max-w-[70%] ${isUser ? "order-first" : ""}`}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {/* Tool calls */}
        {!isUser && message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mb-2 space-y-1">
            {message.toolCalls.map((tc, i) => (
              <ToolCallBadge key={i} name={tc.name} args={tc.args} result={tc.result} status={tc.status} />
            ))}
          </div>
        )}

        {/* Thinking indicator */}
        {!isUser && message.isStreaming && !message.content && (
          <div className="rounded-2xl px-4 py-2.5 text-sm bg-white border border-[var(--border-light)] text-gray-400 rounded-tl-md flex items-center gap-1.5">
            <span className="flex gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "0ms" }} />
              <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "150ms" }} />
              <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "300ms" }} />
            </span>
            <span className="text-xs">Thinking...</span>
          </div>
        )}

        {/* Message content */}
        {message.content && (
          <div className="relative group">
            <div
              className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed overflow-hidden ${
                isUser
                  ? "bg-primary-600 text-white rounded-tr-md"
                  : "bg-white border border-[var(--border-light)] text-gray-800 rounded-tl-md"
              }`}
            >
              {isUser ? (
                <div className="whitespace-pre-wrap">{message.content}</div>
              ) : (
                <div className="prose prose-sm prose-gray max-w-none prose-headings:text-gray-900 prose-headings:font-semibold prose-h1:text-base prose-h2:text-sm prose-h3:text-sm prose-p:text-gray-700 prose-p:leading-relaxed prose-strong:text-gray-900 prose-strong:font-semibold prose-code:text-primary-700 prose-code:bg-primary-50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-xs prose-code:before:content-none prose-code:after:content-none prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-pre:rounded-lg prose-pre:text-xs prose-table:text-xs prose-th:bg-gray-50 prose-th:px-3 prose-th:py-1.5 prose-th:text-left prose-th:font-semibold prose-th:text-gray-700 prose-td:px-3 prose-td:py-1.5 prose-td:border-t prose-td:border-gray-100 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-hr:my-3 prose-a:text-primary-600 prose-a:no-underline hover:prose-a:underline prose-blockquote:border-primary-300 prose-blockquote:text-gray-600">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      table({ children }) {
                        return (
                          <div className="overflow-x-auto -mx-1 my-2">
                            <table>{children}</table>
                          </div>
                        );
                      },
                      code({ className, children, ...props }) {
                        const match = /language-(\w+)/.exec(className || "");
                        if (match && match[1] === "chart") {
                          return <ChartRenderer json={String(children).trim()} />;
                        }
                        // Regular code block
                        if (match) {
                          return (
                            <code className={className} {...props}>
                              {children}
                            </code>
                          );
                        }
                        // Inline code
                        return <code className={className} {...props}>{children}</code>;
                      },
                    }}
                  >
                    {message.content}
                  </ReactMarkdown>
                </div>
              )}
              {message.isStreaming && (
                <span className="inline-block w-1.5 h-4 bg-primary-500 ml-0.5 animate-pulse rounded-sm" />
              )}
            </div>

            {/* Copy button — appears on hover, assistant messages only */}
            {!isUser && !message.isStreaming && hovered && (
              <button
                onClick={handleCopy}
                className="absolute top-2 right-2 p-1 rounded-md bg-gray-100 hover:bg-gray-200 text-gray-500 hover:text-gray-700 transition-colors"
                title="Copy response"
              >
                {copied ? (
                  <Check className="w-3.5 h-3.5 text-emerald-600" />
                ) : (
                  <Copy className="w-3.5 h-3.5" />
                )}
              </button>
            )}
          </div>
        )}

        {/* HITL Approval Buttons */}
        {!isUser && message.approvalRequest && (
          <ApprovalButtons
            approval={message.approvalRequest}
            onApprove={() => onApprove?.(message.approvalRequest!.token)}
            onDeny={() => onDeny?.(message.approvalRequest!.token)}
          />
        )}

        {/* Latency */}
        {!isUser && !message.isStreaming && message.latencyMs != null && (
          <div className="flex items-center gap-1 mt-1 ml-1 text-[10px] text-gray-400">
            <Clock className="w-3 h-3" />
            {(message.latencyMs / 1000).toFixed(1)}s
          </div>
        )}
      </div>

      {isUser && (
        <div className="w-8 h-8 rounded-lg bg-gray-100 flex items-center justify-center flex-shrink-0 mt-0.5">
          <User className="w-4 h-4 text-gray-600" />
        </div>
      )}
    </div>
  );
}

/* ─── Inline HITL Approval Buttons ─── */

function ApprovalButtons({
  approval,
  onApprove,
  onDeny,
}: {
  approval: { token: string; rowCount: string; tableCount: string; status: string };
  onApprove: () => void;
  onDeny: () => void;
}) {
  if (approval.status === "approved") {
    return (
      <div className="mt-2 flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-50 border border-emerald-200">
        <Check className="w-4 h-4 text-emerald-600" />
        <span className="text-xs font-medium text-emerald-700">Approved — push in progress</span>
      </div>
    );
  }

  if (approval.status === "denied") {
    return (
      <div className="mt-2 flex items-center gap-2 px-3 py-2 rounded-lg bg-red-50 border border-red-200">
        <XCircle className="w-4 h-4 text-red-600" />
        <span className="text-xs font-medium text-red-700">Denied — push cancelled</span>
      </div>
    );
  }

  return (
    <div className="mt-2 rounded-lg border border-[var(--border-light)] bg-white overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 bg-amber-50 border-b border-amber-100">
        <ShieldCheck className="w-4 h-4 text-amber-600" />
        <span className="text-xs font-semibold text-amber-800">Approval Required</span>
        <span className="text-[10px] text-amber-600 ml-auto">
          {approval.tableCount} tables &middot; {approval.rowCount} rows
        </span>
      </div>
      <div className="flex items-center justify-end gap-2 px-3 py-2">
        <button
          onClick={onDeny}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-red-600 bg-white border border-red-200 rounded-lg hover:bg-red-50 transition-colors"
        >
          <XCircle className="w-3.5 h-3.5" />
          Deny
        </button>
        <button
          onClick={onApprove}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 transition-colors"
        >
          <Check className="w-3.5 h-3.5" />
          Approve
        </button>
      </div>
    </div>
  );
}

/* ─── Tool Call Badge ─── */

function ToolCallBadge({
  name,
  args,
  result,
  status,
}: {
  name: string;
  args: Record<string, unknown>;
  result?: string;
  status: string;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border border-[var(--border-light)] rounded-lg bg-gray-50 text-xs overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full px-3 py-1.5 hover:bg-gray-100 transition-colors"
      >
        <Wrench className="w-3 h-3 text-gray-500" />
        <span className="font-medium text-gray-700">{name}</span>
        {status === "running" && (
          <span className="ml-auto flex items-center gap-1 text-primary-600">
            <div className="w-2 h-2 rounded-full bg-primary-500 animate-pulse" />
            running
          </span>
        )}
        {status === "done" && (
          <span className="ml-auto text-[var(--success)]">done</span>
        )}
        {expanded ? (
          <ChevronDown className="w-3 h-3 text-gray-400" />
        ) : (
          <ChevronRight className="w-3 h-3 text-gray-400" />
        )}
      </button>

      {expanded && (
        <div className="px-3 py-2 border-t border-[var(--border-light)] space-y-1">
          <div>
            <span className="text-gray-500">Args: </span>
            <code className="text-gray-700">
              {JSON.stringify(args, null, 2)}
            </code>
          </div>
          {result && (
            <div>
              <span className="text-gray-500">Result: </span>
              <span className="text-gray-700">{result}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
