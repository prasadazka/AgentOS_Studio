"use client";

import Link from "next/link";
import { Bot, MessageSquare, Trash2 } from "lucide-react";
import type { Agent } from "@/types";

export default function AgentCard({
  agent,
  onDelete,
}: {
  agent: Agent;
  onDelete?: (name: string) => void;
}) {
  return (
    <div className="bg-white rounded-lg border border-[var(--border-light)] p-4 hover:shadow-card transition-shadow">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-lg bg-primary-50 flex items-center justify-center">
            <Bot className="w-5 h-5 text-primary-600" />
          </div>
          <div>
            <h3 className="font-medium text-sm text-gray-900">{agent.name}</h3>
            <p className="text-xs text-gray-500">{agent.model}</p>
          </div>
        </div>
        {agent.is_default && (
          <span className="text-[10px] font-medium px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded">
            DEFAULT
          </span>
        )}
      </div>

      <p className="text-xs text-gray-500 mb-3 line-clamp-2">
        {agent.system_prompt || "No system prompt configured."}
      </p>

      <div className="flex flex-wrap gap-1 mb-3">
        {agent.tools.slice(0, 3).map((tool) => (
          <span
            key={tool}
            className="text-[10px] px-1.5 py-0.5 bg-gray-50 text-gray-600 rounded"
          >
            {tool}
          </span>
        ))}
        {agent.tools.length > 3 && (
          <span className="text-[10px] px-1.5 py-0.5 bg-gray-50 text-gray-500 rounded">
            +{agent.tools.length - 3} more
          </span>
        )}
      </div>

      <div className="flex items-center gap-2 pt-3 border-t border-[var(--border-light)]">
        <Link
          href={`/agents/${agent.name}/chat`}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-primary-600 text-white text-xs font-medium rounded-md hover:bg-primary-700 transition-colors"
        >
          <MessageSquare className="w-3.5 h-3.5" />
          Chat
        </Link>
        <Link
          href={`/agents/${agent.name}`}
          className="px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 rounded-md transition-colors"
        >
          Details
        </Link>
        {!agent.is_default && onDelete && (
          <button
            onClick={() => onDelete(agent.name)}
            className="ml-auto p-1.5 text-gray-400 hover:text-[var(--danger)] rounded-md hover:bg-red-50 transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}