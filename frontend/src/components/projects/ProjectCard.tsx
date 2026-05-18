"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { FolderOpen, MessageSquare, Trash2, Bot, FileText, Wrench, Cpu } from "lucide-react";
import { api } from "@/lib/api";
import type { Project, Agent } from "@/types";

export default function ProjectCard({
  project,
  onDelete,
}: {
  project: Project;
  onDelete?: (id: string) => void;
}) {
  const [agent, setAgent] = useState<Agent | null>(null);

  useEffect(() => {
    api<Agent>(`/api/agents/${project.agent_name}`)
      .then(setAgent)
      .catch(() => {});
  }, [project.agent_name]);

  return (
    <div className="bg-white rounded-lg border border-[var(--border-light)] p-4 hover:shadow-card transition-shadow">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center">
            <FolderOpen className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <h3 className="font-medium text-sm text-gray-900">{project.name}</h3>
            <div className="flex items-center gap-1 text-xs text-gray-500">
              <Bot className="w-3 h-3" />
              {project.agent_name}
            </div>
          </div>
        </div>
      </div>

      {project.description && (
        <p className="text-xs text-gray-500 mb-3 line-clamp-2">
          {project.description}
        </p>
      )}

      {/* Agent details */}
      {agent && (
        <div className="flex items-center gap-3 text-[11px] text-gray-500 mb-3 px-2.5 py-2 bg-gray-50 rounded-md">
          <span className="flex items-center gap-1" title="Model">
            <Cpu className="w-3 h-3 text-gray-400" />
            {agent.model}
          </span>
          <span className="flex items-center gap-1" title="Tools">
            <Wrench className="w-3 h-3 text-gray-400" />
            {agent.tools.length}
          </span>
        </div>
      )}

      <div className="flex items-center gap-3 text-xs text-gray-500 mb-3">
        <span className="flex items-center gap-1">
          <FileText className="w-3 h-3" />
          {project.file_count ?? 0} files
        </span>
        <span className="flex items-center gap-1">
          <MessageSquare className="w-3 h-3" />
          {project.session_count ?? 0} chats
        </span>
      </div>

      <div className="flex items-center gap-2 pt-3 border-t border-[var(--border-light)]">
        <Link
          href={`/projects/${project.id}/chat`}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-primary-600 text-white text-xs font-medium rounded-md hover:bg-primary-700 transition-colors"
        >
          <MessageSquare className="w-3.5 h-3.5" />
          Chat
        </Link>
        <Link
          href={`/projects/${project.id}`}
          className="px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 rounded-md transition-colors"
        >
          Details
        </Link>
        {onDelete && (
          <button
            type="button"
            onClick={() => onDelete(project.id)}
            className="ml-auto p-1.5 text-gray-400 hover:text-[var(--danger)] rounded-md hover:bg-red-50 transition-colors"
            title="Delete project"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}
