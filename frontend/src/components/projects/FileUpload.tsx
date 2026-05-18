"use client";

import { useState, useCallback, useRef } from "react";
import {
  Upload,
  FileText,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Trash2,
} from "lucide-react";
import { uploadFile, api } from "@/lib/api";
import type { ProjectFile } from "@/types";

interface UploadingFile {
  name: string;
  size: number;
  progress: number; // 0–100
  error?: string;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function FileUpload({
  projectId,
  files,
  onFilesChange,
}: {
  projectId: string;
  files: ProjectFile[];
  onFilesChange: () => void;
}) {
  const [dragging, setDragging] = useState(false);
  const [uploadingFiles, setUploadingFiles] = useState<UploadingFile[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback(
    async (fileList: FileList | File[]) => {
      const arr = Array.from(fileList);

      // Register all files immediately so progress bars appear
      setUploadingFiles(arr.map((f) => ({ name: f.name, size: f.size, progress: 0 })));

      await Promise.all(
        arr.map(async (file, idx) => {
          try {
            await uploadFile(projectId, file, (pct) => {
              setUploadingFiles((prev) =>
                prev.map((u, i) => (i === idx ? { ...u, progress: pct } : u))
              );
            });
          } catch (e) {
            setUploadingFiles((prev) =>
              prev.map((u, i) =>
                i === idx ? { ...u, error: String(e) } : u
              )
            );
          }
        })
      );

      // Clear progress bars after a brief delay then refresh file list
      setTimeout(() => {
        setUploadingFiles([]);
        onFilesChange();
      }, 800);
    },
    [projectId, onFilesChange]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
    },
    [handleFiles]
  );

  async function handleDelete(fid: string) {
    try {
      await api(`/api/projects/${projectId}/files/${fid}`, { method: "DELETE" });
      onFilesChange();
    } catch (e) {
      console.error("Delete failed:", e);
    }
  }

  const isUploading = uploadingFiles.length > 0;

  return (
    <div className="space-y-4">
      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => !isUploading && inputRef.current?.click()}
        className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
          isUploading
            ? "border-primary-300 bg-primary-50 cursor-default"
            : dragging
            ? "border-primary-500 bg-primary-50 cursor-copy"
            : "border-gray-300 hover:border-gray-400 bg-gray-50 cursor-pointer"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          title="Upload files"
          aria-label="Upload files"
          className="hidden"
          accept=".csv,.txt,.json,.md,.xlsx,.pdf,.py,.js,.ts,.yaml,.yml,.log"
          onChange={(e) => {
            if (e.target.files?.length) handleFiles(e.target.files);
            e.target.value = "";
          }}
        />

        {isUploading ? (
          <div className="space-y-3">
            {uploadingFiles.map((uf, i) => (
              <div key={i} className="text-left">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium text-gray-700 truncate max-w-[200px]">{uf.name}</span>
                  <span className="text-[10px] text-gray-500 ml-2 flex-shrink-0">
                    {uf.error ? (
                      <span className="text-red-500">Failed</span>
                    ) : uf.progress === 100 ? (
                      <span className="text-emerald-600">Processing…</span>
                    ) : (
                      <>{uf.progress}% · {formatBytes(uf.size)}</>
                    )}
                  </span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-1.5 overflow-hidden">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <div
                    className={`h-1.5 rounded-full transition-all duration-200 ${
                      uf.error ? "bg-red-400 w-full" : uf.progress === 100 ? "bg-emerald-400 animate-pulse w-full" : "bg-primary-500"
                    }`}
                    // width must be dynamic; Tailwind can't purge arbitrary runtime values
                    {...(!uf.error && uf.progress < 100 ? { style: { width: `${uf.progress}%` } } : {})}
                  />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2">
            <Upload className="w-8 h-8 text-gray-400" />
            <p className="text-sm text-gray-600">Drop files here or click to upload</p>
            <p className="text-xs text-gray-400">
              TXT, CSV, JSON, PDF, XLSX, MD and more · Large files supported
            </p>
          </div>
        )}
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div className="space-y-2">
          {files.map((f) => (
            <div
              key={f.id}
              className="flex items-center gap-3 px-3 py-2 bg-white border border-[var(--border-light)] rounded-lg"
            >
              <FileText className="w-4 h-4 text-gray-400 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-gray-800 truncate">{f.filename}</p>
                <p className="text-xs text-gray-400">{formatBytes(f.file_size)}</p>
              </div>
              {f.status === "processing" && (
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <Loader2 className="w-3.5 h-3.5 text-primary-500 animate-spin" />
                  <span className="text-[10px] text-gray-400">Embedding…</span>
                </div>
              )}
              {f.status === "ready" && (
                <CheckCircle2 className="w-4 h-4 text-green-500 flex-shrink-0" />
              )}
              {f.status === "error" && (
                <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0" />
              )}
              <button
                type="button"
                title={`Delete ${f.filename}`}
                onClick={() => handleDelete(f.id)}
                className="p-1 text-gray-400 hover:text-red-500 transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
