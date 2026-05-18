"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  MessageSquare,
  Bot,
  Wrench,
  Save,
  Pencil,
  X,
  Search,
  Check,
  Loader2,
} from "lucide-react";
import Header from "@/components/layout/Header";
import { api, updateAgent } from "@/lib/api";
import { MODELS, MODEL_IDS } from "@/lib/models";
import type { Agent, Tool } from "@/types";

const MODEL_GROUPS = MODELS.reduce<Record<string, typeof MODELS>>((acc, m) => {
  (acc[m.provider] ??= []).push(m);
  return acc;
}, {});

export default function AgentDetailPage() {
  const params = useParams();
  const name = params.name as string;

  const [agent, setAgent] = useState<Agent | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  // Editable fields
  const [model, setModel] = useState("");
  const [temperature, setTemperature] = useState(0);
  const [maxIterations, setMaxIterations] = useState(15);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [selectedTools, setSelectedTools] = useState<string[]>([]);

  // Tools list
  const [allTools, setAllTools] = useState<Tool[]>([]);
  const [toolSearch, setToolSearch] = useState("");

  const loadAgent = useCallback(async () => {
    try {
      const data = await api<Agent>(`/api/agents/${name}`);
      setAgent(data);
      setModel(data.model);
      setTemperature(data.temperature);
      setMaxIterations(data.max_iterations ?? 15);
      setSystemPrompt(data.system_prompt || "");
      setSelectedTools(data.tools || []);
    } catch {
      setAgent(null);
    } finally {
      setLoading(false);
    }
  }, [name]);

  useEffect(() => {
    loadAgent();
  }, [loadAgent]);

  useEffect(() => {
    if (editing && allTools.length === 0) {
      api<{ tools: Tool[] }>("/api/tools").then((d) => setAllTools(d.tools)).catch(() => {});
    }
  }, [editing, allTools.length]);

  function startEditing() {
    if (!agent) return;
    setModel(agent.model);
    setTemperature(agent.temperature);
    setMaxIterations(agent.max_iterations ?? 15);
    setSystemPrompt(agent.system_prompt || "");
    setSelectedTools(agent.tools || []);
    setEditing(true);
    setSaveMsg(null);
  }

  function cancelEditing() {
    setEditing(false);
    setSaveMsg(null);
  }

  async function handleSave() {
    setSaving(true);
    setSaveMsg(null);
    try {
      const result = await updateAgent(name, {
        model,
        temperature,
        max_iterations: maxIterations,
        system_prompt: systemPrompt,
        tools: selectedTools,
      });
      setAgent(result as unknown as Agent);
      setEditing(false);
      setSaveMsg("Saved");
      setTimeout(() => setSaveMsg(null), 2000);
    } catch (e) {
      setSaveMsg(`Error: ${e}`);
    } finally {
      setSaving(false);
    }
  }

  function toggleTool(toolName: string) {
    setSelectedTools((prev) =>
      prev.includes(toolName) ? prev.filter((t) => t !== toolName) : [...prev, toolName]
    );
  }

  const filteredTools = allTools.filter(
    (t) =>
      t.name.toLowerCase().includes(toolSearch.toLowerCase()) ||
      t.category.toLowerCase().includes(toolSearch.toLowerCase())
  );

  // Group tools by category
  const toolsByCategory = filteredTools.reduce<Record<string, Tool[]>>((acc, t) => {
    (acc[t.category] ??= []).push(t);
    return acc;
  }, {});

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Agent Details" />
        <div className="flex-1 flex items-center justify-center">
          <div className="w-8 h-8 border-2 border-primary-600 border-t-transparent rounded-full animate-spin" />
        </div>
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Agent Not Found" />
        <div className="flex-1 flex items-center justify-center text-gray-500">
          Agent &quot;{name}&quot; not found.
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <Header title={agent.name} />

      <div className="flex-1 overflow-y-auto p-6 max-w-3xl">
        <Link
          href="/agents"
          className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 mb-5"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Agents
        </Link>

        <div className="bg-white rounded-lg border border-[var(--border-light)] p-6">
          {/* Header */}
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-xl bg-primary-50 flex items-center justify-center">
                <Bot className="w-6 h-6 text-primary-600" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-gray-900">{agent.name}</h2>
                <p className="text-sm text-gray-500">{agent.model}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {saveMsg && (
                <span className={`text-xs font-medium ${saveMsg.startsWith("Error") ? "text-red-600" : "text-emerald-600"}`}>
                  {saveMsg.startsWith("Error") ? saveMsg : <span className="flex items-center gap-1"><Check className="w-3 h-3" /> {saveMsg}</span>}
                </span>
              )}
              {editing ? (
                <>
                  <button
                    onClick={cancelEditing}
                    className="flex items-center gap-1.5 px-3 py-2 text-sm text-gray-600 bg-white border border-[var(--border-light)] rounded-lg hover:bg-gray-50 transition-colors"
                  >
                    <X className="w-3.5 h-3.5" />
                    Cancel
                  </button>
                  <button
                    onClick={handleSave}
                    disabled={saving}
                    className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700 transition-colors disabled:opacity-50"
                  >
                    {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                    {saving ? "Saving..." : "Save"}
                  </button>
                </>
              ) : (
                <>
                  <button
                    onClick={startEditing}
                    className="flex items-center gap-1.5 px-3 py-2 text-sm text-gray-600 bg-white border border-[var(--border-light)] rounded-lg hover:bg-gray-50 transition-colors"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                    Edit
                  </button>
                  <Link
                    href={`/agents/${name}/chat`}
                    className="flex items-center gap-2 px-4 py-2.5 bg-primary-600 text-white text-sm font-medium rounded-lg hover:bg-primary-700 transition-colors"
                  >
                    <MessageSquare className="w-4 h-4" />
                    Chat
                  </Link>
                </>
              )}
            </div>
          </div>

          {/* Config */}
          <div className="space-y-5">
            {/* Model + Temperature + Max Iterations */}
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">Model</label>
                {editing ? (
                  <select
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    className="w-full px-2.5 py-2 text-sm border border-[var(--border-light)] rounded-lg focus:outline-none focus:border-primary-500 bg-white"
                  >
                    {Object.entries(MODEL_GROUPS).map(([provider, models]) => (
                      <optgroup key={provider} label={provider}>
                        {models.map((m) => (
                          <option key={m.id} value={m.id}>{m.label} ({m.context})</option>
                        ))}
                      </optgroup>
                    ))}
                    {!MODEL_IDS.includes(model) && model && (
                      <option value={model}>{model}</option>
                    )}
                  </select>
                ) : (
                  <div className="px-3 py-2 text-sm bg-gray-50 rounded-lg text-gray-900">{agent.model}</div>
                )}
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">Temperature</label>
                {editing ? (
                  <input
                    type="number"
                    min={0}
                    max={2}
                    step={0.1}
                    value={temperature}
                    onChange={(e) => setTemperature(parseFloat(e.target.value) || 0)}
                    className="w-full px-2.5 py-2 text-sm border border-[var(--border-light)] rounded-lg focus:outline-none focus:border-primary-500 bg-white"
                  />
                ) : (
                  <div className="px-3 py-2 text-sm bg-gray-50 rounded-lg text-gray-900">{agent.temperature}</div>
                )}
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">Max Iterations</label>
                {editing ? (
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={maxIterations}
                    onChange={(e) => setMaxIterations(parseInt(e.target.value) || 15)}
                    className="w-full px-2.5 py-2 text-sm border border-[var(--border-light)] rounded-lg focus:outline-none focus:border-primary-500 bg-white"
                  />
                ) : (
                  <div className="px-3 py-2 text-sm bg-gray-50 rounded-lg text-gray-900">{agent.max_iterations ?? 15}</div>
                )}
              </div>
            </div>

            {/* Tools */}
            <div>
              <h3 className="text-sm font-medium text-gray-700 mb-2 flex items-center gap-1.5">
                <Wrench className="w-4 h-4" />
                Tools
                {editing && (
                  <span className="text-[10px] text-gray-400 font-normal ml-1">
                    ({selectedTools.length} selected)
                  </span>
                )}
              </h3>
              {editing ? (
                <div className="border border-[var(--border-light)] rounded-lg">
                  {/* Search */}
                  <div className="relative border-b border-[var(--border-light)]">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                    <input
                      type="text"
                      placeholder="Search tools..."
                      value={toolSearch}
                      onChange={(e) => setToolSearch(e.target.value)}
                      className="w-full pl-8 pr-3 py-2 text-xs bg-transparent focus:outline-none"
                    />
                  </div>
                  {/* Tool list */}
                  <div className="max-h-56 overflow-y-auto p-1.5 space-y-2">
                    {Object.entries(toolsByCategory).map(([cat, tools]) => (
                      <div key={cat}>
                        <div className="text-[9px] font-semibold text-gray-400 uppercase tracking-wider px-1.5 py-1">{cat}</div>
                        <div className="space-y-0.5">
                          {tools.map((t) => (
                            <label
                              key={t.name}
                              className={`flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer text-xs transition-colors ${
                                selectedTools.includes(t.name) ? "bg-primary-50 text-primary-700" : "hover:bg-gray-50 text-gray-700"
                              }`}
                            >
                              <input
                                type="checkbox"
                                checked={selectedTools.includes(t.name)}
                                onChange={() => toggleTool(t.name)}
                                className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                              />
                              <span className="font-medium">{t.name}</span>
                              <span className="text-[10px] text-gray-400 truncate">{t.description.slice(0, 50)}</span>
                            </label>
                          ))}
                        </div>
                      </div>
                    ))}
                    {filteredTools.length === 0 && (
                      <div className="text-xs text-gray-400 text-center py-4">No tools match &quot;{toolSearch}&quot;</div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {agent.tools.map((tool) => (
                    <span
                      key={tool}
                      className="text-xs px-2 py-1 bg-gray-50 text-gray-600 rounded-md border border-[var(--border-light)]"
                    >
                      {tool}
                    </span>
                  ))}
                  {agent.tools.length === 0 && (
                    <span className="text-xs text-gray-400">No tools configured</span>
                  )}
                </div>
              )}
            </div>

            {/* System Prompt */}
            <div>
              <h3 className="text-sm font-medium text-gray-700 mb-2">System Prompt</h3>
              {editing ? (
                <textarea
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  rows={14}
                  className="w-full px-3 py-2.5 text-xs font-mono border border-[var(--border-light)] rounded-lg focus:outline-none focus:border-primary-500 bg-white resize-y"
                  placeholder="Enter system prompt..."
                />
              ) : (
                <pre className="text-xs text-gray-600 bg-gray-50 rounded-lg p-4 whitespace-pre-wrap max-h-64 overflow-y-auto border border-[var(--border-light)]">
                  {agent.system_prompt || "No system prompt configured."}
                </pre>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
