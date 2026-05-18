"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Header from "@/components/layout/Header";
import { api } from "@/lib/api";
import type { WorkflowTemplate } from "@/types";
import {
  Merge,
  FileSpreadsheet,
  Workflow,
  ArrowRight,
  Loader2,
} from "lucide-react";

// Icon map for template categories
const TEMPLATE_ICONS: Record<string, typeof Merge> = {
  merge: Merge,
  data: FileSpreadsheet,
};

// Default graph with Start and End nodes pre-placed
const DEFAULT_GRAPH = {
  nodes: [
    {
      id: "start_1",
      type: "start",
      position: { x: 100, y: 250 },
      data: { type: "start", label: "Start" },
    },
    {
      id: "end_1",
      type: "end",
      position: { x: 700, y: 250 },
      data: { type: "end", label: "End" },
    },
  ],
  edges: [],
};

function TemplateCard({
  template,
  onClick,
  loading,
}: {
  template: WorkflowTemplate;
  onClick: () => void;
  loading: boolean;
}) {
  const Icon = TEMPLATE_ICONS[template.icon] || Workflow;

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={loading}
      className="text-left bg-white rounded-lg border border-[var(--border-light)] hover:border-primary-300 hover:shadow-md transition-all p-5 group relative"
    >
      {loading && (
        <div className="absolute inset-0 bg-white/80 rounded-lg flex items-center justify-center z-10">
          <Loader2 className="w-5 h-5 text-primary-600 animate-spin" />
        </div>
      )}

      {/* Category badge */}
      <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-blue-50 text-blue-600 uppercase tracking-wider">
        {template.category}
      </span>

      {/* Icon + Name */}
      <div className="flex items-center gap-3 mt-3 mb-2">
        <div className="w-10 h-10 rounded-lg bg-primary-50 flex items-center justify-center flex-shrink-0">
          <Icon className="w-5 h-5 text-primary-600" />
        </div>
        <h3 className="text-sm font-semibold text-gray-900">{template.name}</h3>
      </div>

      {/* Description */}
      <p className="text-xs text-gray-500 leading-relaxed mb-3 line-clamp-2">
        {template.description}
      </p>

      {/* Footer: node count + tags */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-gray-400">
            {template.node_count} nodes
          </span>
          <span className="text-gray-200">|</span>
          {template.tags.slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="text-[10px] px-1.5 py-0.5 rounded bg-gray-50 text-gray-400"
            >
              {tag}
            </span>
          ))}
        </div>
        <ArrowRight className="w-4 h-4 text-gray-300 group-hover:text-primary-500 transition-colors" />
      </div>
    </button>
  );
}

export default function NewWorkflowPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(true);
  const [creatingTemplate, setCreatingTemplate] = useState<string | null>(null);

  useEffect(() => {
    api<{ templates: WorkflowTemplate[] }>("/api/workflow-templates")
      .then((data) => setTemplates(data.templates))
      .catch(() => {})
      .finally(() => setLoadingTemplates(false));
  }, []);

  async function handleTemplateSelect(template: WorkflowTemplate) {
    setCreatingTemplate(template.id);
    try {
      const wf = await api<{ id: string }>("/api/workflows", {
        method: "POST",
        body: JSON.stringify({
          name: template.name,
          description: template.description,
          template_id: template.id,
        }),
      });
      router.push(`/workflows/${wf.id}`);
    } catch (err) {
      alert(`Failed to create from template: ${err}`);
      setCreatingTemplate(null);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try {
      const wf = await api<{ id: string }>("/api/workflows", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          description,
          graph_json: DEFAULT_GRAPH,
        }),
      });
      router.push(`/workflows/${wf.id}`);
    } catch (err) {
      alert(`Failed to create: ${err}`);
      setCreating(false);
    }
  }

  return (
    <div className="flex flex-col h-full">
      <Header title="New Workflow" />

      <div className="flex-1 p-6 overflow-y-auto">
        <div className="max-w-3xl mx-auto space-y-8">
          {/* Section 1: Templates */}
          {!loadingTemplates && templates.length > 0 && (
            <section>
              <h2 className="text-sm font-semibold text-gray-700 mb-1">
                Start from a Template
              </h2>
              <p className="text-xs text-gray-400 mb-4">
                Pre-built workflows you can customize in the visual editor
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {templates.map((t) => (
                  <TemplateCard
                    key={t.id}
                    template={t}
                    onClick={() => handleTemplateSelect(t)}
                    loading={creatingTemplate === t.id}
                  />
                ))}
              </div>
            </section>
          )}

          {/* Divider */}
          {!loadingTemplates && templates.length > 0 && (
            <div className="flex items-center gap-4">
              <div className="flex-1 h-px bg-gray-200" />
              <span className="text-xs text-gray-400 font-medium">
                or start from scratch
              </span>
              <div className="flex-1 h-px bg-gray-200" />
            </div>
          )}

          {/* Section 2: Blank workflow form (existing) */}
          <section className="flex justify-center">
            <form
              onSubmit={handleCreate}
              className="w-full max-w-lg bg-white rounded-lg border border-[var(--border-light)] p-6 space-y-4"
            >
              <div>
                <label className="text-xs font-semibold text-gray-700">
                  Workflow Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Data Pipeline, Support Triage..."
                  className="mt-1 w-full px-3 py-2.5 text-sm border border-[var(--border-light)] rounded-lg focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500"
                  autoFocus
                  required
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-700">
                  Description (optional)
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="What does this workflow do?"
                  className="mt-1 w-full px-3 py-2.5 text-sm border border-[var(--border-light)] rounded-lg focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500 h-20 resize-none"
                />
              </div>

              {/* Quick preview */}
              <div className="bg-gray-50 rounded-lg p-3 border border-[var(--border-light)]">
                <div className="text-[10px] font-medium text-gray-500 mb-2">
                  YOUR WORKFLOW WILL START WITH:
                </div>
                <div className="flex items-center gap-3 text-xs text-gray-600">
                  <span className="flex items-center gap-1.5 px-2.5 py-1 bg-emerald-50 border border-emerald-200 rounded-full text-emerald-700 font-medium">
                    Start
                  </span>
                  <span className="text-gray-300">- - - - -</span>
                  <span className="text-gray-400 italic">drag nodes here</span>
                  <span className="text-gray-300">- - - - -</span>
                  <span className="flex items-center gap-1.5 px-2.5 py-1 bg-red-50 border border-red-200 rounded-full text-red-700 font-medium">
                    End
                  </span>
                </div>
              </div>

              <button
                type="submit"
                disabled={creating || !name.trim()}
                className="w-full py-2.5 text-sm font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700 transition-colors disabled:opacity-50"
              >
                {creating ? "Creating..." : "Create & Open Editor"}
              </button>
            </form>
          </section>
        </div>
      </div>
    </div>
  );
}
