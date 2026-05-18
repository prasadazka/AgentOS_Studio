"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  FolderOpen,
  FileText,
  FileSpreadsheet,
  FileCode,
  FileJson,
  File as FileIcon,
  Download,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Upload,
  Sparkles,
  Trash2,
} from "lucide-react";
import { api, uploadFile, API_URL } from "@/lib/api";
import { cn } from "@/lib/utils";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import type { DiskFile } from "@/types";

const FILE_ICONS: Record<string, typeof FileText> = {
  csv: FileSpreadsheet,
  xlsx: FileSpreadsheet,
  xls: FileSpreadsheet,
  json: FileJson,
  py: FileCode,
  js: FileCode,
  ts: FileCode,
  md: FileText,
  txt: FileText,
  log: FileText,
  pdf: FileText,
};

function getFileIcon(fileType: string) {
  return FILE_ICONS[fileType] || FileIcon;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface FolderNode {
  name: string;
  files: DiskFile[];
  children: Map<string, FolderNode>;
}

function buildTree(files: DiskFile[]): FolderNode {
  const root: FolderNode = { name: "files", files: [], children: new Map() };

  for (const file of files) {
    const parts = file.relative_path.replace(/\\/g, "/").split("/");
    if (parts.length === 1) {
      root.files.push(file);
    } else {
      let current = root;
      for (let i = 0; i < parts.length - 1; i++) {
        const dir = parts[i];
        if (!current.children.has(dir)) {
          current.children.set(dir, { name: dir, files: [], children: new Map() });
        }
        current = current.children.get(dir)!;
      }
      current.files.push(file);
    }
  }

  return root;
}

export default function ProjectFilesPanel({ projectId }: { projectId: string }) {
  const [files, setFiles] = useState<DiskFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [deleteFileTarget, setDeleteFileTarget] = useState<DiskFile | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadFiles = useCallback(async () => {
    try {
      const data = await api<{ files: DiskFile[] }>(
        `/api/projects/${projectId}/files/all`
      );
      setFiles(data.files);
    } catch (e) {
      console.error("Failed to load files:", e);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    loadFiles();
  }, [loadFiles]);

  // Auto-refresh every 10s to catch agent-generated files
  useEffect(() => {
    const interval = setInterval(loadFiles, 10000);
    return () => clearInterval(interval);
  }, [loadFiles]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files;
    if (!selected || selected.length === 0) return;
    setUploading(true);
    try {
      for (let i = 0; i < selected.length; i++) {
        await uploadFile(projectId, selected[i]);
      }
      await loadFiles();
    } catch (err) {
      console.error("Upload failed:", err);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function handleDeleteFile(file: DiskFile) {
    setDeleteFileTarget(file);
  }

  async function confirmDeleteFile() {
    if (!deleteFileTarget) return;
    try {
      await api(`/api/projects/${projectId}/files/by-name/${encodeURIComponent(deleteFileTarget.filename)}`, {
        method: "DELETE",
      });
      await loadFiles();
    } catch (err) {
      console.error("Delete failed:", err);
    } finally {
      setDeleteFileTarget(null);
    }
  }

  const uploadedCount = files.filter((f) => f.source === "uploaded").length;
  const generatedCount = files.filter((f) => f.source === "generated").length;

  return (
    <div className="border-l border-[var(--border-light)] bg-white flex flex-col h-full w-72 flex-shrink-0">
      {/* Header */}
      <div
        className="h-12 flex items-center justify-between px-3 border-b border-[var(--border-light)] cursor-pointer hover:bg-gray-50"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          {expanded ? (
            <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 text-gray-400" />
          )}
          <FolderOpen className="w-4 h-4 text-blue-600" />
          <span className="text-xs font-semibold text-gray-800">
            Project Files
          </span>
          <span className="text-[10px] text-gray-400 font-medium">
            {files.length}
          </span>
        </div>
        <div className="flex items-center gap-0.5">
          <button
            onClick={(e) => {
              e.stopPropagation();
              fileInputRef.current?.click();
            }}
            disabled={uploading}
            className="p-1 text-gray-400 hover:text-blue-600 rounded transition-colors"
            title="Upload files"
          >
            <Upload className={cn("w-3.5 h-3.5", uploading && "animate-pulse")} />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              setLoading(true);
              loadFiles();
            }}
            className="p-1 text-gray-400 hover:text-gray-600 rounded transition-colors"
            title="Refresh"
          >
            <RefreshCw className={cn("w-3.5 h-3.5", loading && "animate-spin")} />
          </button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          accept=".csv,.xlsx,.xls,.json,.txt,.md,.pdf,.py,.js,.ts,.log,.yaml,.yml"
          onChange={handleUpload}
          aria-label="Upload project files"
        />
      </div>

      {expanded && (
        <div className="flex-1 overflow-y-auto">
          {/* Stats bar */}
          {files.length > 0 && (
            <div className="flex gap-3 px-3 py-2 border-b border-[var(--border-light)] text-[10px] text-gray-500">
              {uploadedCount > 0 && (
                <span className="flex items-center gap-1">
                  <Upload className="w-3 h-3" />
                  {uploadedCount} uploaded
                </span>
              )}
              {generatedCount > 0 && (
                <span className="flex items-center gap-1">
                  <Sparkles className="w-3 h-3 text-amber-500" />
                  {generatedCount} generated
                </span>
              )}
            </div>
          )}

          {/* File tree */}
          {loading && files.length === 0 ? (
            <div className="text-xs text-gray-400 text-center py-6">
              Loading files...
            </div>
          ) : files.length === 0 ? (
            <div className="text-xs text-gray-400 text-center py-6">
              No files yet
            </div>
          ) : (
            <div className="py-1">
              <FolderTreeNode
                node={buildTree(files)}
                projectId={projectId}
                depth={0}
                isRoot
                onDelete={handleDeleteFile}
              />
            </div>
          )}
        </div>
      )}
      <ConfirmDialog
        open={!!deleteFileTarget}
        title="Delete File"
        message={`Are you sure you want to delete "${deleteFileTarget?.filename}"? This action cannot be undone.`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={confirmDeleteFile}
        onCancel={() => setDeleteFileTarget(null)}
      />
    </div>
  );
}

function FolderTreeNode({
  node,
  projectId,
  depth,
  isRoot,
  onDelete,
}: {
  node: FolderNode;
  projectId: string;
  depth: number;
  isRoot?: boolean;
  onDelete: (file: DiskFile) => void;
}) {
  const [open, setOpen] = useState(true);

  const paddingLeft = isRoot ? 8 : 8 + depth * 16;

  return (
    <div>
      {/* Folder header (skip for root) */}
      {!isRoot && (
        <div
          className="flex items-center gap-1.5 py-1 px-2 hover:bg-gray-50 cursor-pointer text-xs text-gray-700"
          style={{ paddingLeft }}
          onClick={() => setOpen(!open)}
        >
          {open ? (
            <ChevronDown className="w-3 h-3 text-gray-400 flex-shrink-0" />
          ) : (
            <ChevronRight className="w-3 h-3 text-gray-400 flex-shrink-0" />
          )}
          <FolderOpen className="w-3.5 h-3.5 text-blue-500 flex-shrink-0" />
          <span className="font-medium truncate">{node.name}</span>
        </div>
      )}

      {(isRoot || open) && (
        <>
          {/* Sub-folders */}
          {Array.from(node.children.values()).map((child) => (
            <FolderTreeNode
              key={child.name}
              node={child}
              projectId={projectId}
              depth={depth + 1}
              onDelete={onDelete}
            />
          ))}

          {/* Files */}
          {node.files.map((file) => (
            <FileRow
              key={file.relative_path}
              file={file}
              projectId={projectId}
              depth={isRoot ? depth : depth + 1}
              onDelete={onDelete}
            />
          ))}
        </>
      )}
    </div>
  );
}

function FileRow({
  file,
  projectId,
  depth,
  onDelete,
}: {
  file: DiskFile;
  projectId: string;
  depth: number;
  onDelete: (file: DiskFile) => void;
}) {
  const Icon = getFileIcon(file.file_type);
  const paddingLeft = 8 + (depth + 1) * 16;

  function handleDownload() {
    const url = `${API_URL}/api/projects/${projectId}/files/download/${encodeURIComponent(file.filename)}`;
    const a = document.createElement("a");
    a.href = url;
    a.download = file.filename;
    a.click();
  }

  return (
    <div
      className="group flex items-center gap-1.5 py-1 px-2 hover:bg-gray-50 text-xs"
      style={{ paddingLeft }}
    >
      <Icon
        className={cn(
          "w-3.5 h-3.5 flex-shrink-0",
          file.source === "generated" ? "text-amber-500" : "text-gray-400"
        )}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1">
          <span className="text-gray-800 truncate">{file.filename}</span>
          {file.source === "generated" && (
            <Sparkles className="w-2.5 h-2.5 text-amber-500 flex-shrink-0" />
          )}
        </div>
        <span className="text-[10px] text-gray-400">
          {formatSize(file.file_size)}
        </span>
      </div>
      <button
        onClick={handleDownload}
        className="hidden group-hover:flex p-1 text-gray-400 hover:text-primary-600 rounded transition-colors"
        title="Download"
      >
        <Download className="w-3.5 h-3.5" />
      </button>
      <button
        onClick={() => onDelete(file)}
        className="hidden group-hover:flex p-1 text-gray-400 hover:text-red-500 rounded transition-colors"
        title="Delete"
      >
        <Trash2 className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}
