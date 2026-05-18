"use client";

import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { X, Bot, Wrench, GitBranch, ShieldCheck, Play, Plus, Trash2, GripVertical, Search, AlertCircle, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { MODELS, MODEL_IDS } from "@/lib/models";
import type { Node } from "@xyflow/react";
import type { Agent, Tool, ToolSchema, WorkflowNodeData, WorkflowInputField } from "@/types";

interface NodeConfigPanelProps {
  node: Node | null;
  onUpdate: (nodeId: string, data: Partial<WorkflowNodeData>) => void;
  onClose: () => void;
}

const FIELD_TYPES: { value: WorkflowInputField["type"]; label: string; hint: string }[] = [
  { value: "text", label: "Text", hint: "Single line input" },
  { value: "textarea", label: "Long Text", hint: "Multi-line input" },
  { value: "number", label: "Number", hint: "Numeric value" },
  { value: "select", label: "Dropdown", hint: "Pick from options" },
  { value: "file", label: "File Upload", hint: "Browse & upload a file" },
];

function InputFieldBuilder({
  fields,
  onChange,
}: {
  fields: WorkflowInputField[];
  onChange: (fields: WorkflowInputField[]) => void;
}) {
  const addField = () => {
    onChange([
      ...fields,
      { name: `field_${fields.length + 1}`, label: `Field ${fields.length + 1}`, type: "text", required: false, placeholder: "" },
    ]);
  };

  const updateField = (index: number, patch: Partial<WorkflowInputField>) => {
    const updated = fields.map((f, i) => (i === index ? { ...f, ...patch } : f));
    onChange(updated);
  };

  const removeField = (index: number) => {
    onChange(fields.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wide">Input Fields</label>
        <button
          type="button"
          onClick={addField}
          className="flex items-center gap-1 text-[10px] font-medium text-primary-600 hover:text-primary-700"
        >
          <Plus className="w-3 h-3" /> Add Field
        </button>
      </div>

      {fields.length === 0 && (
        <div className="text-[10px] text-gray-400 italic py-2 text-center border border-dashed border-gray-200 rounded-md">
          No input fields. Add fields to collect data when running.
        </div>
      )}

      {fields.map((field, i) => (
        <div key={i} className="bg-gray-50 rounded-md border border-[var(--border-light)] p-2 space-y-1.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1">
              <GripVertical className="w-3 h-3 text-gray-300" />
              <span className="text-[10px] font-semibold text-gray-500">Field {i + 1}</span>
            </div>
            <button type="button" title="Remove field" onClick={() => removeField(i)} className="p-0.5 text-gray-400 hover:text-red-500">
              <Trash2 className="w-3 h-3" />
            </button>
          </div>

          <input
            type="text"
            value={field.label}
            onChange={(e) => updateField(i, { label: e.target.value, name: e.target.value.toLowerCase().replace(/\s+/g, "_") })}
            placeholder="Field label"
            className="w-full px-2 py-1 text-[11px] border border-[var(--border-light)] rounded focus:outline-none focus:border-primary-500"
          />

          <div className="flex items-center gap-1.5">
            <select
              value={field.type}
              onChange={(e) => updateField(i, { type: e.target.value as WorkflowInputField["type"] })}
              title="Field type"
              className="flex-1 px-2 py-1 text-[11px] border border-[var(--border-light)] rounded focus:outline-none focus:border-primary-500 bg-white"
            >
              {FIELD_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label} — {t.hint}</option>
              ))}
            </select>
            <label className="flex items-center gap-1 text-[10px] text-gray-500 whitespace-nowrap">
              <input
                type="checkbox"
                checked={field.required || false}
                onChange={(e) => updateField(i, { required: e.target.checked })}
                className="w-3 h-3 rounded"
              />
              Required
            </label>
          </div>

          <input
            type="text"
            value={field.placeholder || ""}
            onChange={(e) => updateField(i, { placeholder: e.target.value })}
            placeholder="Placeholder text..."
            className="w-full px-2 py-1 text-[11px] border border-[var(--border-light)] rounded focus:outline-none focus:border-primary-500"
          />

          <input
            type="text"
            value={field.defaultValue || ""}
            onChange={(e) => updateField(i, { defaultValue: e.target.value })}
            placeholder="Default value..."
            className="w-full px-2 py-1 text-[11px] border border-[var(--border-light)] rounded focus:outline-none focus:border-primary-500"
          />

          {field.type === "select" && (
            <input
              type="text"
              value={(field.options || []).join(", ")}
              onChange={(e) => updateField(i, { options: e.target.value.split(",").map((o) => o.trim()).filter(Boolean) })}
              placeholder="Options (comma-separated)"
              className="w-full px-2 py-1 text-[11px] border border-[var(--border-light)] rounded focus:outline-none focus:border-primary-500"
            />
          )}
        </div>
      ))}
    </div>
  );
}

// Group models by provider for the select dropdown
const MODEL_GROUPS = MODELS.reduce<Record<string, typeof MODELS>>((acc, m) => {
  (acc[m.provider] ??= []).push(m);
  return acc;
}, {});

function AgentConfig({
  data,
  nodeId,
  agents,
  allTools,
  onUpdate,
}: {
  data: WorkflowNodeData;
  nodeId: string;
  agents: Agent[];
  allTools: Tool[];
  onUpdate: (nodeId: string, data: Partial<WorkflowNodeData>) => void;
}) {
  const [toolSearch, setToolSearch] = useState("");
  const [showToolPicker, setShowToolPicker] = useState(false);
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const [promptDragOver, setPromptDragOver] = useState(false);

  const selectedAgent = agents.find((a) => a.name === data.agentName);

  // Resolved values: node override > agent default > fallback
  const currentModel = (data.agentModel as string) || selectedAgent?.model || "";
  const currentTemp = data.agentTemperature != null ? (data.agentTemperature as number) : (selectedAgent?.temperature ?? 0);
  const currentPrompt = (data.agentSystemPrompt as string) ?? selectedAgent?.system_prompt ?? "";

  // Show full config when agent is selected OR when inline prompt/tools exist (e.g. from templates)
  const hasInlineConfig = !!(data.agentSystemPrompt || (data.agentTools as string[])?.length);
  const showConfig = !!data.agentName || hasInlineConfig;

  // Tools: merge agent defaults + user overrides
  const agentDefaultTools = selectedAgent?.tools || [];
  const extraTools = ((data.agentTools as string[]) || []);
  const activeTools = useMemo(
    () => Array.from(new Set([...agentDefaultTools, ...extraTools])),
    [agentDefaultTools, extraTools]
  );

  const availableTools = useMemo(() => {
    return allTools
      .filter((t) => !activeTools.includes(t.name))
      .filter((t) =>
        !toolSearch || t.name.toLowerCase().includes(toolSearch.toLowerCase()) || t.category.toLowerCase().includes(toolSearch.toLowerCase())
      );
  }, [allTools, activeTools, toolSearch]);

  const addTool = (toolName: string) => {
    const updated = Array.from(new Set([...extraTools, toolName]));
    onUpdate(nodeId, { agentTools: updated });
  };

  const removeTool = (toolName: string) => {
    if (agentDefaultTools.includes(toolName)) {
      // Removing a default tool — store as negative override
      // For simplicity, we just filter from extra. Default tools can't be removed currently.
      return;
    }
    onUpdate(nodeId, { agentTools: extraTools.filter((t) => t !== toolName) });
  };

  // When agent changes, populate overrides from agent defaults
  const handleAgentChange = (name: string) => {
    const agent = agents.find((a) => a.name === name);
    onUpdate(nodeId, {
      agentName: name,
      label: name || "Agent",
      agentModel: agent?.model || "",
      agentTemperature: agent?.temperature ?? 0,
      agentSystemPrompt: agent?.system_prompt || "",
      agentTools: [],
    });
  };

  return (
    <>
      {/* Agent selector */}
      <div>
        <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wide">Base Agent</label>
        <select
          title="Base agent"
          value={data.agentName || ""}
          onChange={(e) => handleAgentChange(e.target.value)}
          className="mt-1 w-full px-2.5 py-1.5 text-xs border border-[var(--border-light)] rounded-md focus:outline-none focus:border-primary-500 bg-white"
        >
          <option value="">{hasInlineConfig ? "— Inline Agent (custom config below) —" : "Select agent..."}</option>
          {agents.map((a) => (
            <option key={a.name} value={a.name}>{a.name}</option>
          ))}
        </select>
        {selectedAgent && (
          <p className="text-[9px] text-gray-400 mt-0.5">Override any setting below per-node</p>
        )}
        {!selectedAgent && hasInlineConfig && (
          <p className="text-[9px] text-blue-500 mt-0.5">Using inline config from template. Select a base agent to inherit its defaults.</p>
        )}
      </div>

      {/* Model */}
      {showConfig && (
        <div>
          <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wide">Model</label>
          <select
            value={currentModel}
            onChange={(e) => onUpdate(nodeId, { agentModel: e.target.value })}
            className="mt-1 w-full px-2.5 py-1.5 text-xs border border-[var(--border-light)] rounded-md focus:outline-none focus:border-primary-500 bg-white"
          >
            <option value="">Select model...</option>
            {Object.entries(MODEL_GROUPS).map(([provider, models]) => (
              <optgroup key={provider} label={provider}>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>{m.label} ({m.context})</option>
                ))}
              </optgroup>
            ))}
            {currentModel && !MODEL_IDS.includes(currentModel) && (
              <option value={currentModel}>{currentModel}</option>
            )}
          </select>
          <input
            type="text"
            value={currentModel}
            onChange={(e) => onUpdate(nodeId, { agentModel: e.target.value })}
            placeholder="Or type custom model ID..."
            className="mt-1 w-full px-2.5 py-1.5 text-[10px] border border-[var(--border-light)] rounded-md focus:outline-none focus:border-primary-500 font-mono text-gray-600"
          />
        </div>
      )}

      {/* Temperature */}
      {showConfig && (
        <div>
          <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wide">
            Temperature <span className="text-gray-400 normal-case font-normal">({currentTemp})</span>
          </label>
          <input
            type="range"
            title="Temperature"
            min={0}
            max={2}
            step={0.1}
            value={currentTemp}
            onChange={(e) => onUpdate(nodeId, { agentTemperature: parseFloat(e.target.value) })}
            className="mt-1 w-full h-1.5 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-500"
          />
          <div className="flex justify-between text-[9px] text-gray-400 mt-0.5">
            <span>Precise (0)</span>
            <span>Creative (2)</span>
          </div>
        </div>
      )}

      {/* System Prompt */}
      {showConfig && (
        <div>
          <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wide">System Prompt</label>
          <p className="text-[9px] text-gray-400 mt-0.5 mb-1">
            Drag tools from below into the prompt to insert <code className="bg-gray-100 px-0.5 rounded font-mono">{"{{tool:name}}"}</code> variables
          </p>
          <textarea
            ref={promptRef}
            value={currentPrompt}
            onChange={(e) => onUpdate(nodeId, { agentSystemPrompt: e.target.value })}
            placeholder="Instructions for the agent..."
            rows={6}
            onDragOver={(e) => { e.preventDefault(); setPromptDragOver(true); }}
            onDragLeave={() => setPromptDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setPromptDragOver(false);
              const toolName = e.dataTransfer.getData("text/tool-name");
              if (!toolName) return;
              const ta = promptRef.current;
              if (!ta) return;
              const pos = ta.selectionStart ?? currentPrompt.length;
              const variable = `{{tool:${toolName}}}`;
              const updated = currentPrompt.slice(0, pos) + variable + currentPrompt.slice(pos);
              onUpdate(nodeId, { agentSystemPrompt: updated });
            }}
            className={`mt-1 w-full px-2.5 py-1.5 text-xs border rounded-md focus:outline-none focus:border-primary-500 resize-none leading-relaxed transition-colors ${
              promptDragOver ? "border-purple-400 bg-purple-50/50 ring-1 ring-purple-300" : "border-[var(--border-light)]"
            }`}
          />
        </div>
      )}

      {/* Tools */}
      {showConfig && (
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wide">Tools</label>
            <button
              type="button"
              onClick={() => setShowToolPicker(!showToolPicker)}
              className="flex items-center gap-0.5 text-[10px] font-medium text-primary-600 hover:text-primary-700"
            >
              <Plus className="w-3 h-3" /> Add Tool
            </button>
          </div>

          {activeTools.length === 0 ? (
            <div className="text-[10px] text-gray-400 italic py-1">No tools assigned</div>
          ) : (
            <div className="space-y-1">
              <p className="text-[9px] text-gray-400">Drag a tool into the prompt to reference it</p>
              {activeTools.map((toolName) => {
                const isDefault = agentDefaultTools.includes(toolName);
                return (
                  <div
                    key={toolName}
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.setData("text/tool-name", toolName);
                      e.dataTransfer.effectAllowed = "copy";
                    }}
                    className="flex items-center justify-between px-2 py-1 bg-gray-50 rounded border border-[var(--border-light)] cursor-grab active:cursor-grabbing hover:border-purple-300 hover:bg-purple-50/30 transition-colors"
                  >
                    <div className="flex items-center gap-1.5">
                      <GripVertical className="w-3 h-3 text-gray-300" />
                      <Wrench className="w-3 h-3 text-purple-400" />
                      <span className="text-[11px] text-gray-700">{toolName}</span>
                      {isDefault && (
                        <span className="text-[9px] px-1 py-0.5 bg-blue-100 text-blue-500 rounded font-medium">default</span>
                      )}
                    </div>
                    {!isDefault && (
                      <button
                        type="button"
                        title="Remove tool"
                        onClick={() => removeTool(toolName)}
                        className="p-0.5 text-gray-400 hover:text-red-500"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Tool picker dropdown */}
          {showToolPicker && (
            <div className="mt-2 border border-[var(--border-light)] rounded-md bg-white shadow-sm overflow-hidden">
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-gray-400" />
                <input
                  type="text"
                  value={toolSearch}
                  onChange={(e) => setToolSearch(e.target.value)}
                  placeholder="Search tools..."
                  className="w-full pl-7 pr-2 py-1.5 text-[11px] border-b border-[var(--border-light)] focus:outline-none"
                  autoFocus
                />
              </div>
              <div className="max-h-32 overflow-y-auto">
                {availableTools.length === 0 ? (
                  <div className="text-[10px] text-gray-400 p-2 text-center">No tools found</div>
                ) : (
                  availableTools.slice(0, 20).map((t) => (
                    <button
                      type="button"
                      key={t.name}
                      onClick={() => { addTool(t.name); setToolSearch(""); }}
                      className="w-full flex items-center gap-1.5 px-2 py-1.5 text-left hover:bg-purple-50 transition-colors"
                    >
                      <Wrench className="w-3 h-3 text-purple-400 flex-shrink-0" />
                      <div>
                        <div className="text-[11px] text-gray-700">{t.name}</div>
                        <div className="text-[9px] text-gray-400">{t.category}</div>
                      </div>
                    </button>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </>
  );
}

function ToolConfig({
  data,
  nodeId,
  tools,
  onUpdate,
}: {
  data: WorkflowNodeData;
  nodeId: string;
  tools: Tool[];
  onUpdate: (nodeId: string, data: Partial<WorkflowNodeData>) => void;
}) {
  const [schema, setSchema] = useState<ToolSchema | null>(null);
  const [loading, setLoading] = useState(false);
  const [showRawJson, setShowRawJson] = useState(false);

  const toolArgs = (data.toolArgs || {}) as Record<string, unknown>;

  // Fetch schema when tool changes
  useEffect(() => {
    if (!data.toolName) {
      setSchema(null);
      return;
    }
    setLoading(true);
    api<ToolSchema>(`/api/tools/${data.toolName}/schema`)
      .then((s) => setSchema(s))
      .catch(() => setSchema(null))
      .finally(() => setLoading(false));
  }, [data.toolName]);

  const handleToolChange = useCallback(
    (name: string) => {
      onUpdate(nodeId, { toolName: name, label: name || "Tool", toolArgs: {} });
    },
    [nodeId, onUpdate]
  );

  const updateArg = useCallback(
    (key: string, value: unknown) => {
      onUpdate(nodeId, { toolArgs: { ...toolArgs, [key]: value } });
    },
    [nodeId, toolArgs, onUpdate]
  );

  const params = schema?.parameters;
  const properties = params?.properties || {};
  const required = params?.required || [];
  const paramNames = Object.keys(properties);

  return (
    <>
      {/* Tool selector */}
      <div>
        <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wide">Tool</label>
        <select
          title="Select tool"
          value={data.toolName || ""}
          onChange={(e) => handleToolChange(e.target.value)}
          className="mt-1 w-full px-2.5 py-1.5 text-xs border border-[var(--border-light)] rounded-md focus:outline-none focus:border-primary-500 bg-white"
        >
          <option value="">Select tool...</option>
          {tools.map((t) => (
            <option key={t.name} value={t.name}>{t.name}</option>
          ))}
        </select>
      </div>

      {/* Loading state */}
      {loading && (
        <div className="flex items-center gap-1.5 text-[10px] text-gray-400 py-1">
          <Loader2 className="w-3 h-3 animate-spin" /> Loading parameters...
        </div>
      )}

      {/* Auto-detected parameters */}
      {data.toolName && !loading && paramNames.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wide">Parameters</label>
            <button
              type="button"
              onClick={() => setShowRawJson(!showRawJson)}
              className="text-[9px] text-gray-400 hover:text-gray-600 underline"
            >
              {showRawJson ? "Form view" : "JSON view"}
            </button>
          </div>

          {/* Required params warning */}
          {required.length > 0 && (
            <div className="flex items-start gap-1.5 px-2 py-1.5 bg-amber-50 border border-amber-200 rounded-md">
              <AlertCircle className="w-3 h-3 text-amber-500 flex-shrink-0 mt-0.5" />
              <span className="text-[10px] text-amber-700">
                Required: {required.join(", ")}
              </span>
            </div>
          )}

          {/* Placeholder hint */}
          <div className="px-2 py-1.5 bg-blue-50 border border-blue-200 rounded-md">
            <p className="text-[9px] text-blue-600 leading-relaxed">
              Use <code className="bg-blue-100 px-0.5 rounded font-mono">{"{{output}}"}</code> to reference the previous node&apos;s output, or <code className="bg-blue-100 px-0.5 rounded font-mono">{"{{input}}"}</code> for workflow input. Leave empty to auto-pass previous output.
            </p>
          </div>

          {showRawJson ? (
            /* Raw JSON editor fallback */
            <textarea
              title="Tool arguments (JSON)"
              placeholder="{}"
              value={JSON.stringify(toolArgs, null, 2)}
              onChange={(e) => {
                try { onUpdate(nodeId, { toolArgs: JSON.parse(e.target.value) }); } catch { /* ignore */ }
              }}
              className="w-full px-2.5 py-1.5 text-xs border border-[var(--border-light)] rounded-md focus:outline-none focus:border-primary-500 font-mono h-28 resize-none"
            />
          ) : (
            /* Smart form inputs */
            <div className="space-y-2">
              {paramNames.map((pName) => {
                const pSchema = properties[pName];
                const isRequired = required.includes(pName);
                const currentVal = toolArgs[pName];
                const isEmpty = currentVal === undefined || currentVal === "" || currentVal === null;

                return (
                  <div key={pName}>
                    <label className="flex items-center gap-1 text-[10px] font-medium text-gray-600">
                      {pName}
                      {isRequired && <span className="text-red-500">*</span>}
                      <span className="text-gray-400 font-normal">({pSchema.type})</span>
                    </label>

                    {pSchema.type === "boolean" ? (
                      <label className="flex items-center gap-1.5 mt-1">
                        <input
                          type="checkbox"
                          checked={!!currentVal}
                          onChange={(e) => updateArg(pName, e.target.checked)}
                          className="w-3.5 h-3.5 rounded"
                        />
                        <span className="text-[11px] text-gray-600">{currentVal ? "true" : "false"}</span>
                      </label>
                    ) : pSchema.type === "integer" || pSchema.type === "number" ? (
                      <input
                        type="number"
                        title={pName}
                        value={currentVal != null ? String(currentVal) : ""}
                        onChange={(e) => {
                          const v = e.target.value;
                          updateArg(pName, v === "" ? undefined : pSchema.type === "integer" ? parseInt(v) : parseFloat(v));
                        }}
                        placeholder={isRequired ? `${pName} (required)` : pName}
                        className={`mt-1 w-full px-2.5 py-1.5 text-xs border rounded-md focus:outline-none focus:border-primary-500 ${
                          isRequired && isEmpty ? "border-red-300 bg-red-50/50" : "border-[var(--border-light)]"
                        }`}
                      />
                    ) : (
                      <input
                        type="text"
                        title={pName}
                        value={currentVal != null ? String(currentVal) : ""}
                        onChange={(e) => updateArg(pName, e.target.value || undefined)}
                        placeholder={isRequired ? `${pName} (required)` : pName}
                        className={`mt-1 w-full px-2.5 py-1.5 text-xs border rounded-md focus:outline-none focus:border-primary-500 ${
                          isRequired && isEmpty ? "border-red-300 bg-red-50/50" : "border-[var(--border-light)]"
                        }`}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* No params detected */}
      {data.toolName && !loading && paramNames.length === 0 && schema && (
        <div className="text-[10px] text-gray-400 italic py-1">No parameters required.</div>
      )}

      {/* Fallback if schema failed to load */}
      {data.toolName && !loading && !schema && (
        <div>
          <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wide">Tool Args (JSON)</label>
          <textarea
            title="Tool arguments"
            placeholder="{}"
            value={JSON.stringify(toolArgs, null, 2)}
            onChange={(e) => {
              try { onUpdate(nodeId, { toolArgs: JSON.parse(e.target.value) }); } catch { /* ignore */ }
            }}
            className="mt-1 w-full px-2.5 py-1.5 text-xs border border-[var(--border-light)] rounded-md focus:outline-none focus:border-primary-500 font-mono h-20 resize-none"
          />
        </div>
      )}
    </>
  );
}

export default function NodeConfigPanel({ node, onUpdate, onClose }: NodeConfigPanelProps) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);

  useEffect(() => {
    api<{ agents: Agent[] }>("/api/agents").then((d) => setAgents(d.agents)).catch(() => {});
    api<{ tools: Tool[] }>("/api/tools").then((d) => setTools(d.tools)).catch(() => {});
  }, []);

  if (!node) return null;

  const data = node.data as WorkflowNodeData;
  const nodeType = data.type || node.type;

  // Start node — configurable input fields
  if (nodeType === "start") {
    return (
      <div className="w-72 border-l border-[var(--border-light)] bg-white flex flex-col h-full flex-shrink-0">
        <div className="flex items-center justify-between px-3 py-3 border-b border-[var(--border-light)]">
          <div className="flex items-center gap-2">
            <Play className="w-4 h-4 text-emerald-500" />
            <span className="text-xs font-semibold text-gray-700">Start Config</span>
          </div>
          <button type="button" title="Close panel" onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600 rounded">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          <div className="bg-emerald-50 rounded-md p-2 border border-emerald-100">
            <p className="text-[10px] text-emerald-700 leading-relaxed">
              Add fields that appear when someone runs this workflow.
            </p>
            <p className="text-[9px] text-emerald-600 mt-1 leading-relaxed">
              Examples: a <strong>File Upload</strong> to pick a file, a <strong>Dropdown</strong> to choose output format (txt, json, csv), or <strong>Text</strong> for a name.
            </p>
          </div>
          <InputFieldBuilder
            fields={(data.inputFields as WorkflowInputField[]) || []}
            onChange={(inputFields) => onUpdate(node.id, { inputFields })}
          />
        </div>
      </div>
    );
  }

  // End node — no config
  if (nodeType === "end") {
    return (
      <div className="w-64 border-l border-[var(--border-light)] bg-white flex flex-col h-full flex-shrink-0">
        <div className="flex items-center justify-between px-3 py-3 border-b border-[var(--border-light)]">
          <span className="text-xs font-semibold text-gray-700 capitalize">End Node</span>
          <button type="button" title="Close panel" onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600 rounded">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-3 text-xs text-gray-500">No configuration needed.</div>
      </div>
    );
  }

  const icons: Record<string, typeof Bot> = {
    agent: Bot, tool: Wrench, condition: GitBranch, approval: ShieldCheck,
  };
  const Icon = icons[nodeType || ""] || Bot;

  return (
    <div className={`${nodeType === "agent" ? "w-72" : "w-64"} border-l border-[var(--border-light)] bg-white flex flex-col h-full flex-shrink-0`}>
      <div className="flex items-center justify-between px-3 py-3 border-b border-[var(--border-light)]">
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-gray-500" />
          <span className="text-xs font-semibold text-gray-700 capitalize">{nodeType} Config</span>
        </div>
        <button type="button" title="Close panel" onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600 rounded">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {/* Label */}
        <div>
          <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wide">Label</label>
          <input
            type="text"
            title="Node label"
            placeholder="Node label"
            value={data.label || ""}
            onChange={(e) => onUpdate(node.id, { label: e.target.value })}
            className="mt-1 w-full px-2.5 py-1.5 text-xs border border-[var(--border-light)] rounded-md focus:outline-none focus:border-primary-500"
          />
        </div>

        {/* Agent-specific */}
        {nodeType === "agent" && (
          <AgentConfig
            data={data}
            nodeId={node.id}
            agents={agents}
            allTools={tools}
            onUpdate={onUpdate}
          />
        )}

        {/* Tool-specific */}
        {nodeType === "tool" && (
          <ToolConfig data={data} nodeId={node.id} tools={tools} onUpdate={onUpdate} />
        )}

        {/* Condition-specific */}
        {nodeType === "condition" && (
          <div>
            <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wide">Expression</label>
            <select
              title="Condition expression"
              value={data.expression || "has_error"}
              onChange={(e) => onUpdate(node.id, { expression: e.target.value })}
              className="mt-1 w-full px-2.5 py-1.5 text-xs border border-[var(--border-light)] rounded-md focus:outline-none focus:border-primary-500 bg-white"
            >
              <option value="has_error">has_error</option>
              <option value="output_contains:">output_contains:</option>
              <option value="custom">Custom expression</option>
            </select>
            {(data.expression === "output_contains:" || data.expression?.startsWith("output_contains:")) && (
              <input
                type="text"
                placeholder="keyword..."
                value={data.expression?.replace("output_contains:", "") || ""}
                onChange={(e) => onUpdate(node.id, { expression: `output_contains:${e.target.value}` })}
                className="mt-1 w-full px-2.5 py-1.5 text-xs border border-[var(--border-light)] rounded-md focus:outline-none focus:border-primary-500"
              />
            )}
          </div>
        )}

        {/* Approval-specific */}
        {nodeType === "approval" && (
          <>
            {/* Auto-approve toggle */}
            <div className="flex items-center justify-between px-3 py-2.5 bg-teal-50 border border-teal-200 rounded-lg">
              <div>
                <div className="text-[11px] font-semibold text-teal-700">Auto-Approve</div>
                <div className="text-[9px] text-teal-600 mt-0.5">
                  {data.autoApprove ? "Skips popup — auto-approved" : "Shows popup for manual approval"}
                </div>
              </div>
              <button
                type="button"
                title="Toggle auto-approve"
                onClick={() => onUpdate(node.id, { autoApprove: !data.autoApprove })}
                className={`relative w-10 h-5 rounded-full transition-colors ${
                  data.autoApprove ? "bg-teal-500" : "bg-gray-300"
                }`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                    data.autoApprove ? "translate-x-5" : "translate-x-0"
                  }`}
                />
              </button>
            </div>

            <div>
              <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wide">Prompt</label>
              <textarea
                value={data.approvalPrompt || ""}
                onChange={(e) => onUpdate(node.id, { approvalPrompt: e.target.value })}
                className="mt-1 w-full px-2.5 py-1.5 text-xs border border-[var(--border-light)] rounded-md focus:outline-none focus:border-primary-500 h-20 resize-none"
                placeholder="What should the human review?"
              />
            </div>

            {/* Only show timeout when manual approval is needed */}
            {!data.autoApprove && (
              <div>
                <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wide">Timeout (seconds)</label>
                <input
                  type="number"
                  title="Timeout in seconds"
                  placeholder="300"
                  value={data.approvalTimeout || 300}
                  onChange={(e) => onUpdate(node.id, { approvalTimeout: parseInt(e.target.value) || 300 })}
                  className="mt-1 w-full px-2.5 py-1.5 text-xs border border-[var(--border-light)] rounded-md focus:outline-none focus:border-primary-500"
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
