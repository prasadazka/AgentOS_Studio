"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  Sparkles,
  Plus,
  X,
  Loader2,
  Check,
  Pencil,
} from "lucide-react";
import Link from "next/link";
import Header from "@/components/layout/Header";
import { api } from "@/lib/api";
import { MODELS, MODEL_IDS } from "@/lib/models";
import type { Agent, Tool } from "@/types";

// Group models by provider
const MODEL_GROUPS = MODELS.reduce<Record<string, typeof MODELS>>((acc, m) => {
  (acc[m.provider] ??= []).push(m);
  return acc;
}, {});

type Step = "describe" | "review" | "manual";

export default function CreateAgentPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("describe");
  const [tools, setTools] = useState<Tool[]>([]);

  // Step 1: Description
  const [description, setDescription] = useState("");
  const [generating, setGenerating] = useState(false);

  // Step 2: Generated / editable config
  const [name, setName] = useState("");
  const [model, setModel] = useState("gpt-4o-mini");
  const [temperature, setTemperature] = useState(0);
  const [maxIterations, setMaxIterations] = useState(15);
  const [selectedTools, setSelectedTools] = useState<string[]>([]);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [toolSearch, setToolSearch] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api<{ tools: Tool[] }>("/api/tools").then((data) => setTools(data.tools));
  }, []);

  // Track the name that was saved on the backend (from generate)
  const [savedName, setSavedName] = useState("");

  // --- Smart Generate ---
  async function handleGenerate() {
    if (!description.trim()) return;
    setGenerating(true);
    try {
      const result = await api<Agent>("/api/agents/generate", {
        method: "POST",
        body: JSON.stringify({ description: description.trim() }),
      });

      // Fill form with AI-generated config
      setName(result.name || "");
      setSavedName(result.name || "");
      setSelectedTools(result.tools || []);
      setSystemPrompt(result.system_prompt || "");
      setTemperature(result.temperature ?? 0);
      setMaxIterations(result.max_iterations ?? 15);
      setModel(result.model || "gpt-4o-mini");
      setStep("review");
    } catch (e) {
      alert(`Generation failed: ${e}`);
    } finally {
      setGenerating(false);
    }
  }

  // --- Save and Chat (from review step) ---
  async function handleSaveAndChat() {
    if (!name.trim()) return alert("Agent name is required");
    setSaving(true);
    try {
      // If user changed the name or config, re-save
      const needsResave =
        name.trim() !== savedName ||
        true; // always save to pick up edits to tools/prompt/etc.

      if (needsResave) {
        // Delete the old generated agent if name changed
        if (savedName && savedName !== name.trim()) {
          try {
            await api(`/api/agents/${encodeURIComponent(savedName)}`, {
              method: "DELETE",
            });
          } catch {
            // ignore if delete fails (might not exist)
          }
        }

        await api("/api/agents", {
          method: "POST",
          body: JSON.stringify({
            name: name.trim(),
            tools: selectedTools,
            model,
            temperature,
            system_prompt: systemPrompt || null,
            max_iterations: maxIterations,
          }),
        });
      }

      router.push(`/agents/${encodeURIComponent(name.trim())}/chat`);
    } catch (e) {
      alert(`Failed to save agent: ${e}`);
    } finally {
      setSaving(false);
    }
  }

  // --- Manual Create ---
  async function handleCreate() {
    if (!name.trim()) return alert("Agent name is required");
    setSaving(true);
    try {
      await api("/api/agents", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          tools: selectedTools,
          model,
          temperature,
          system_prompt: systemPrompt || null,
          max_iterations: maxIterations,
        }),
      });
      router.push("/agents");
    } catch (e) {
      alert(`Failed to create agent: ${e}`);
    } finally {
      setSaving(false);
    }
  }

  function toggleTool(toolName: string) {
    setSelectedTools((prev) =>
      prev.includes(toolName)
        ? prev.filter((t) => t !== toolName)
        : [...prev, toolName]
    );
  }

  const filteredTools = tools.filter(
    (t) =>
      t.name.toLowerCase().includes(toolSearch.toLowerCase()) ||
      t.category.toLowerCase().includes(toolSearch.toLowerCase())
  );

  return (
    <div className="flex flex-col h-full">
      <Header title="Create Agent" />

      <div className="flex-1 p-6 max-w-3xl">
        <Link
          href="/agents"
          className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 mb-5"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Agents
        </Link>

        {/* ========== STEP 1: Describe ========== */}
        {step === "describe" && (
          <div className="space-y-5">
            {/* AI Generation Card */}
            <div className="bg-white rounded-lg border border-primary-200 p-6">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-8 h-8 rounded-lg bg-primary-50 flex items-center justify-center">
                  <Sparkles className="w-4 h-4 text-primary-600" />
                </div>
                <div>
                  <h2 className="text-sm font-semibold text-gray-900">
                    Describe your agent
                  </h2>
                  <p className="text-xs text-gray-500">
                    AI will generate the prompt, pick tools, and configure
                    everything
                  </p>
                </div>
              </div>

              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="e.g., A data analyst agent that can read CSV files, clean data, run SQL queries, and create visualizations..."
                rows={4}
                className="w-full px-3 py-2.5 text-sm border border-[var(--border)] rounded-lg focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500 resize-none mb-4"
                disabled={generating}
              />

              <button
                onClick={handleGenerate}
                disabled={generating || !description.trim()}
                className="flex items-center gap-2 px-5 py-2.5 bg-primary-600 text-white text-sm font-medium rounded-lg hover:bg-primary-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {generating ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4" />
                    Generate Agent
                  </>
                )}
              </button>
            </div>

            {/* Divider */}
            <div className="flex items-center gap-3">
              <div className="flex-1 h-px bg-[var(--border-light)]" />
              <span className="text-xs text-gray-400">or</span>
              <div className="flex-1 h-px bg-[var(--border-light)]" />
            </div>

            {/* Manual */}
            <button
              onClick={() => setStep("manual")}
              className="w-full py-3 border border-[var(--border)] rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition-colors"
            >
              Configure manually
            </button>
          </div>
        )}

        {/* ========== STEP 2: Review Generated Config ========== */}
        {step === "review" && (
          <div className="space-y-5">
            <div className="bg-white rounded-lg border border-[var(--border-light)] p-6 space-y-5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-lg bg-green-50 flex items-center justify-center">
                    <Check className="w-4 h-4 text-[var(--success)]" />
                  </div>
                  <div>
                    <h2 className="text-sm font-semibold text-gray-900">
                      Agent Generated
                    </h2>
                    <p className="text-xs text-gray-500">
                      Review and edit before saving
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => setStep("describe")}
                  className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
                >
                  <ArrowLeft className="w-3 h-3" />
                  Re-describe
                </button>
              </div>

              {/* Editable Name */}
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">
                  Agent Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-[var(--border)] rounded-lg focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500"
                />
              </div>

              {/* Model & Temp & Iterations */}
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">
                    Model
                  </label>
                  <select
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    className="w-full px-3 py-2 text-sm border border-[var(--border)] rounded-lg focus:outline-none focus:border-primary-500 bg-white"
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
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">
                    Temperature: {temperature}
                  </label>
                  <input
                    type="range"
                    min="0"
                    max="2"
                    step="0.1"
                    value={temperature}
                    onChange={(e) => setTemperature(parseFloat(e.target.value))}
                    className="w-full mt-2 accent-primary-600"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">
                    Max Iterations: {maxIterations}
                  </label>
                  <input
                    type="range"
                    min="5"
                    max="75"
                    step="5"
                    value={maxIterations}
                    onChange={(e) =>
                      setMaxIterations(parseInt(e.target.value))
                    }
                    className="w-full mt-2 accent-primary-600"
                  />
                </div>
              </div>

              {/* Tools */}
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">
                  Tools ({selectedTools.length} selected)
                </label>
                <div className="flex flex-wrap gap-1.5">
                  {selectedTools.map((t) => (
                    <span
                      key={t}
                      className="inline-flex items-center gap-1 text-xs px-2 py-1 bg-primary-50 text-primary-700 rounded-md"
                    >
                      {t}
                      <button onClick={() => toggleTool(t)}>
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                  <button
                    onClick={() => setStep("manual")}
                    className="text-xs px-2 py-1 text-gray-500 border border-dashed border-gray-300 rounded-md hover:border-gray-400 transition-colors"
                  >
                    + Add tools
                  </button>
                </div>
              </div>

              {/* System Prompt */}
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1 flex items-center gap-1">
                  System Prompt
                  <Pencil className="w-3 h-3 text-gray-400" />
                </label>
                <textarea
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  rows={10}
                  className="w-full px-3 py-2 text-xs font-mono border border-[var(--border)] rounded-lg focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500 resize-y"
                />
              </div>

              {/* Actions */}
              <div className="flex items-center gap-3 pt-2">
                <button
                  onClick={handleSaveAndChat}
                  disabled={saving || !name.trim()}
                  className="flex items-center gap-2 px-5 py-2.5 bg-primary-600 text-white text-sm font-medium rounded-lg hover:bg-primary-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {saving ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Saving...
                    </>
                  ) : (
                    <>
                      <ArrowRight className="w-4 h-4" />
                      Save &amp; Start Chatting
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ========== MANUAL MODE ========== */}
        {step === "manual" && (
          <div className="bg-white rounded-lg border border-[var(--border-light)] p-6 space-y-5">
            <div className="flex items-center justify-between mb-1">
              <h2 className="text-sm font-semibold text-gray-900">
                Manual Configuration
              </h2>
              <button
                onClick={() => setStep("describe")}
                className="text-xs text-primary-600 hover:text-primary-700"
              >
                Use AI instead
              </button>
            </div>

            {/* Name */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                Agent Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., ResearchAssistant"
                className="w-full px-3 py-2 text-sm border border-[var(--border)] rounded-lg focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500"
              />
            </div>

            {/* Model & Temperature */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Model
                </label>
                <select
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-[var(--border)] rounded-lg focus:outline-none focus:border-primary-500 bg-white"
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
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Temperature: {temperature}
                </label>
                <input
                  type="range"
                  min="0"
                  max="2"
                  step="0.1"
                  value={temperature}
                  onChange={(e) => setTemperature(parseFloat(e.target.value))}
                  className="w-full mt-2 accent-primary-600"
                />
              </div>
            </div>

            {/* Tools */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                Tools ({selectedTools.length} selected)
              </label>
              {selectedTools.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-2">
                  {selectedTools.map((t) => (
                    <span
                      key={t}
                      className="inline-flex items-center gap-1 text-xs px-2 py-1 bg-primary-50 text-primary-700 rounded-md"
                    >
                      {t}
                      <button onClick={() => toggleTool(t)}>
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <input
                type="text"
                placeholder="Search tools..."
                value={toolSearch}
                onChange={(e) => setToolSearch(e.target.value)}
                className="w-full px-3 py-2 text-sm border border-[var(--border)] rounded-lg mb-2 focus:outline-none focus:border-primary-500"
              />
              <div className="max-h-48 overflow-y-auto border border-[var(--border-light)] rounded-lg">
                {filteredTools.map((tool) => (
                  <label
                    key={tool.name}
                    className="flex items-center gap-2.5 px-3 py-2 hover:bg-gray-50 cursor-pointer text-sm border-b border-[var(--border-light)] last:border-0"
                  >
                    <input
                      type="checkbox"
                      checked={selectedTools.includes(tool.name)}
                      onChange={() => toggleTool(tool.name)}
                      className="rounded accent-primary-600"
                    />
                    <span className="text-gray-900">{tool.name}</span>
                    <span className="text-[10px] px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded ml-auto">
                      {tool.category}
                    </span>
                  </label>
                ))}
              </div>
            </div>

            {/* System Prompt */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                System Prompt
              </label>
              <textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                placeholder="You are a helpful AI assistant..."
                rows={4}
                className="w-full px-3 py-2 text-sm border border-[var(--border)] rounded-lg focus:outline-none focus:border-primary-500 resize-none"
              />
            </div>

            {/* Create */}
            <button
              onClick={handleCreate}
              disabled={saving || !name.trim()}
              className="flex items-center gap-2 px-5 py-2.5 bg-primary-600 text-white text-sm font-medium rounded-lg hover:bg-primary-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Plus className="w-4 h-4" />
              {saving ? "Creating..." : "Create Agent"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
