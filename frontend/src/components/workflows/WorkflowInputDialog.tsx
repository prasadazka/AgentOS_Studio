"use client";

import { useState, useEffect, useRef } from "react";
import { Play, X, Upload, Loader2, CheckCircle2 } from "lucide-react";
import { uploadWorkflowFile } from "@/lib/api";
import type { WorkflowInputField } from "@/types";

interface WorkflowInputDialogProps {
  workflowId: string;
  workflowName: string;
  fields: WorkflowInputField[];
  onSubmit: (values: Record<string, string>) => void;
  onCancel: () => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function WorkflowInputDialog({ workflowId, workflowName, fields, onSubmit, onCancel }: WorkflowInputDialogProps) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Track file upload state per field
  const [fileUploading, setFileUploading] = useState<Record<string, boolean>>({});
  const [fileNames, setFileNames] = useState<Record<string, { name: string; size: number }>>({});
  const fileInputRefs = useRef<Record<string, HTMLInputElement | null>>({});

  // Initialize defaults
  useEffect(() => {
    const defaults: Record<string, string> = {};
    for (const f of fields) {
      defaults[f.name] = f.defaultValue || "";
    }
    setValues(defaults);
  }, [fields]);

  const setValue = (name: string, value: string) => {
    setValues((prev) => ({ ...prev, [name]: value }));
    setErrors((prev) => ({ ...prev, [name]: "" }));
  };

  const handleFileSelect = async (fieldName: string, file: File) => {
    setFileUploading((prev) => ({ ...prev, [fieldName]: true }));
    setErrors((prev) => ({ ...prev, [fieldName]: "" }));

    try {
      const result = await uploadWorkflowFile(workflowId, file);
      setValue(fieldName, result.filepath);
      setFileNames((prev) => ({ ...prev, [fieldName]: { name: result.filename, size: result.file_size } }));
    } catch (e) {
      setErrors((prev) => ({ ...prev, [fieldName]: e instanceof Error ? e.message : "Upload failed" }));
    } finally {
      setFileUploading((prev) => ({ ...prev, [fieldName]: false }));
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    // Block submit if any file is still uploading
    if (Object.values(fileUploading).some(Boolean)) return;

    // Validate required fields (only the ones visible to the user)
    const newErrors: Record<string, string> = {};
    for (const f of fields) {
      if (f.hidden) continue;
      if (f.required && !values[f.name]?.trim()) {
        newErrors[f.name] = `${f.label} is required`;
      }
    }

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    onSubmit(values);
  };

  // Skip hidden fields from rendering (their values still submit via `values`)
  const visibleFields = fields.filter((f) => !f.hidden);
  // If no fields configured, show simple text input
  const hasFields = visibleFields.length > 0;
  const isAnyUploading = Object.values(fileUploading).some(Boolean);

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border-light)] bg-gradient-to-r from-emerald-50 to-white">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-emerald-100 flex items-center justify-center">
              <Play className="w-4 h-4 text-emerald-600" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-gray-800">Run Workflow</h3>
              <p className="text-[11px] text-gray-500">{workflowName}</p>
            </div>
          </div>
          <button type="button" onClick={onCancel} title="Close" className="p-1.5 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {hasFields ? (
            visibleFields.map((field) => (
              <div key={field.name}>
                <label className="flex items-center gap-1 text-xs font-medium text-gray-700 mb-1">
                  {field.label}
                  {field.required && <span className="text-red-500">*</span>}
                </label>

                {field.type === "text" && (
                  <input
                    type="text"
                    value={values[field.name] || ""}
                    onChange={(e) => setValue(field.name, e.target.value)}
                    placeholder={field.placeholder || ""}
                    className="w-full px-3 py-2 text-sm border border-[var(--border-light)] rounded-lg focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500"
                  />
                )}

                {field.type === "textarea" && (
                  <textarea
                    value={values[field.name] || ""}
                    onChange={(e) => setValue(field.name, e.target.value)}
                    placeholder={field.placeholder || ""}
                    rows={3}
                    className="w-full px-3 py-2 text-sm border border-[var(--border-light)] rounded-lg focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500 resize-none"
                  />
                )}

                {field.type === "number" && (
                  <input
                    type="number"
                    value={values[field.name] || ""}
                    onChange={(e) => setValue(field.name, e.target.value)}
                    placeholder={field.placeholder || ""}
                    className="w-full px-3 py-2 text-sm border border-[var(--border-light)] rounded-lg focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500"
                  />
                )}

                {field.type === "select" && (
                  <select
                    value={values[field.name] || ""}
                    onChange={(e) => setValue(field.name, e.target.value)}
                    title={field.label}
                    className="w-full px-3 py-2 text-sm border border-[var(--border-light)] rounded-lg focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500 bg-white"
                  >
                    <option value="">{field.placeholder || "Select..."}</option>
                    {(field.options || []).map((opt) => (
                      <option key={opt} value={opt}>{opt}</option>
                    ))}
                  </select>
                )}

                {field.type === "file" && (
                  <div>
                    <input
                      ref={(el) => { fileInputRefs.current[field.name] = el; }}
                      type="file"
                      title={`Upload ${field.label}`}
                      className="hidden"
                      accept=".txt,.csv,.json,.xlsx,.pdf,.py,.yaml,.yml,.log,.db,.parquet"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) handleFileSelect(field.name, file);
                        e.target.value = "";
                      }}
                    />

                    {/* File selected state */}
                    {values[field.name] && fileNames[field.name] ? (
                      <div className="flex items-center gap-2 px-3 py-2 bg-emerald-50 border border-emerald-200 rounded-lg">
                        <CheckCircle2 className="w-4 h-4 text-emerald-500 flex-shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className="text-xs font-medium text-emerald-700 truncate">{fileNames[field.name].name}</p>
                          <p className="text-[10px] text-emerald-600">{formatBytes(fileNames[field.name].size)}</p>
                        </div>
                        <button
                          type="button"
                          onClick={() => fileInputRefs.current[field.name]?.click()}
                          className="text-[10px] text-emerald-600 hover:text-emerald-800 font-medium px-2 py-1 rounded hover:bg-emerald-100"
                        >
                          Change
                        </button>
                      </div>
                    ) : fileUploading[field.name] ? (
                      /* Uploading state */
                      <div className="flex items-center gap-2 px-3 py-3 bg-blue-50 border border-blue-200 rounded-lg">
                        <Loader2 className="w-4 h-4 text-blue-500 animate-spin flex-shrink-0" />
                        <span className="text-xs text-blue-600">Uploading...</span>
                      </div>
                    ) : (
                      /* Empty state — browse button */
                      <button
                        type="button"
                        onClick={() => fileInputRefs.current[field.name]?.click()}
                        className="w-full flex items-center gap-3 px-3 py-3 border-2 border-dashed border-gray-300 rounded-lg hover:border-primary-400 hover:bg-gray-50 transition-colors group"
                      >
                        <div className="w-8 h-8 rounded-lg bg-gray-100 flex items-center justify-center group-hover:bg-primary-50">
                          <Upload className="w-4 h-4 text-gray-400 group-hover:text-primary-500" />
                        </div>
                        <div className="text-left">
                          <p className="text-xs font-medium text-gray-600 group-hover:text-primary-600">Browse files</p>
                          <p className="text-[10px] text-gray-400">{field.placeholder || "TXT, CSV, JSON, PDF, XLSX..."}</p>
                        </div>
                      </button>
                    )}
                  </div>
                )}

                {errors[field.name] && (
                  <p className="text-[11px] text-red-500 mt-0.5">{errors[field.name]}</p>
                )}
              </div>
            ))
          ) : (
            /* Fallback: simple text input when no fields configured */
            <div>
              <label className="text-xs font-medium text-gray-700 mb-1 block">Input</label>
              <textarea
                value={values["_input"] || ""}
                onChange={(e) => setValue("_input", e.target.value)}
                placeholder="Enter workflow input (or leave empty)..."
                rows={3}
                className="w-full px-3 py-2 text-sm border border-[var(--border-light)] rounded-lg focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500 resize-none"
                autoFocus
              />
              <p className="text-[10px] text-gray-400 mt-1">
                Tip: Click the Start node to configure custom input fields.
              </p>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 pt-1">
            <button
              type="submit"
              disabled={isAnyUploading}
              className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-emerald-600 text-white text-sm font-medium rounded-lg hover:bg-emerald-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isAnyUploading ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Uploading...
                </>
              ) : (
                <>
                  <Play className="w-3.5 h-3.5" />
                  Execute Workflow
                </>
              )}
            </button>
            <button
              type="button"
              onClick={onCancel}
              className="px-4 py-2.5 text-sm font-medium text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
