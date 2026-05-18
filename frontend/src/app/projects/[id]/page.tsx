"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  MessageSquare,
  Bot,
  Wrench,
  Cpu,
  Thermometer,
  Repeat,
  Pencil,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import Header from "@/components/layout/Header";
import FileUpload from "@/components/projects/FileUpload";
import { api } from "@/lib/api";
import type { Project, ProjectFile, Agent } from "@/types";

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [agent, setAgent] = useState<Agent | null>(null);
  const [loading, setLoading] = useState(true);
  const [promptExpanded, setPromptExpanded] = useState(false);

  const loadData = useCallback(async () => {
    try {
      const [proj, filesData] = await Promise.all([
        api<Project>(`/api/projects/${id}`),
        api<{ files: ProjectFile[] }>(`/api/projects/${id}/files`),
      ]);
      setProject(proj);
      setFiles(filesData.files);

      // Load agent details
      try {
        const agentData = await api<Agent>(`/api/agents/${proj.agent_name}`);
        setAgent(agentData);
      } catch {
        setAgent(null);
      }
    } catch (e) {
      console.error("Failed to load project:", e);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Project" />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-sm text-gray-400">Loading...</div>
        </div>
      </div>
    );
  }

  if (!project) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Project" />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-sm text-gray-500">Project not found</div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <Header title={project.name} />

      <div className="flex-1 p-6 overflow-y-auto">
        <Link
          href="/projects"
          className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Projects
        </Link>

        <div className="max-w-2xl space-y-6">
          {/* Project info */}
          <div className="bg-white border border-[var(--border-light)] rounded-lg p-5">
            <h2 className="text-lg font-semibold text-gray-900 mb-1">
              {project.name}
            </h2>
            {project.description && (
              <p className="text-sm text-gray-500 mb-3">
                {project.description}
              </p>
            )}
          </div>

          {/* Agent details */}
          <div className="bg-white border border-[var(--border-light)] rounded-lg overflow-hidden">
            <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border-light)]">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-primary-50 flex items-center justify-center">
                  <Bot className="w-5 h-5 text-primary-600" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-gray-900">{project.agent_name}</h3>
                  <span className="text-[11px] text-gray-500">Project Agent</span>
                </div>
              </div>
              <Link
                href={`/agents/${project.agent_name}`}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-600 bg-white border border-[var(--border-light)] rounded-lg hover:bg-gray-50 transition-colors"
              >
                <Pencil className="w-3 h-3" />
                Edit Agent
              </Link>
            </div>

            {agent ? (
              <div className="px-5 py-4 space-y-4">
                {/* Model / Temp / Iterations row */}
                <div className="grid grid-cols-3 gap-3">
                  <div className="flex items-center gap-2 px-3 py-2.5 bg-gray-50 rounded-lg">
                    <Cpu className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                    <div>
                      <div className="text-[10px] text-gray-400 font-medium">Model</div>
                      <div className="text-xs font-medium text-gray-900 truncate">{agent.model}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 px-3 py-2.5 bg-gray-50 rounded-lg">
                    <Thermometer className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                    <div>
                      <div className="text-[10px] text-gray-400 font-medium">Temperature</div>
                      <div className="text-xs font-medium text-gray-900">{agent.temperature}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 px-3 py-2.5 bg-gray-50 rounded-lg">
                    <Repeat className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                    <div>
                      <div className="text-[10px] text-gray-400 font-medium">Max Iterations</div>
                      <div className="text-xs font-medium text-gray-900">{agent.max_iterations ?? 15}</div>
                    </div>
                  </div>
                </div>

                {/* Tools */}
                <div>
                  <div className="flex items-center gap-1.5 mb-2">
                    <Wrench className="w-3.5 h-3.5 text-gray-400" />
                    <span className="text-[11px] font-medium text-gray-500">
                      Tools ({agent.tools.length})
                    </span>
                  </div>
                  {agent.tools.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {agent.tools.map((tool) => (
                        <span
                          key={tool}
                          className="text-[11px] px-2 py-0.5 bg-blue-50 text-blue-700 rounded-md border border-blue-100"
                        >
                          {tool}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <span className="text-xs text-gray-400">No tools configured</span>
                  )}
                </div>

                {/* System Prompt (collapsible) */}
                {agent.system_prompt && (
                  <div>
                    <button
                      type="button"
                      onClick={() => setPromptExpanded(!promptExpanded)}
                      className="flex items-center gap-1.5 text-[11px] font-medium text-gray-500 hover:text-gray-700 transition-colors"
                    >
                      {promptExpanded ? (
                        <ChevronDown className="w-3 h-3" />
                      ) : (
                        <ChevronRight className="w-3 h-3" />
                      )}
                      System Prompt
                    </button>
                    {promptExpanded && (
                      <pre className="mt-2 text-[11px] text-gray-600 bg-gray-50 rounded-lg p-3 whitespace-pre-wrap max-h-48 overflow-y-auto border border-[var(--border-light)]">
                        {agent.system_prompt}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="px-5 py-4 text-xs text-gray-400">
                Could not load agent details.
              </div>
            )}
          </div>

          {/* Files */}
          <div>
            <h3 className="text-sm font-semibold text-gray-900 mb-3">
              Files ({files.length})
            </h3>
            <FileUpload
              projectId={id}
              files={files}
              onFilesChange={loadData}
            />
          </div>

          {/* Start chatting */}
          <Link
            href={`/projects/${id}/chat`}
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-primary-600 text-white text-sm font-medium rounded-lg hover:bg-primary-700 transition-colors"
          >
            <MessageSquare className="w-4 h-4" />
            Start Chatting
          </Link>
        </div>
      </div>
    </div>
  );
}
