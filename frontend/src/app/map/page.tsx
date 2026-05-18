"use client";

import { useState, useEffect, useRef } from "react";
import dynamic from "next/dynamic";
import {
  Globe,
  FileText,
  Loader2,
  AlertCircle,
  MapPin,
  Upload,
} from "lucide-react";
import { API_URL } from "@/lib/api";

const MapViewer = dynamic(
  () => import("@/components/map/MapViewer"),
  {
    ssr: false,
    loading: () => (
      <div className="flex-1 flex items-center justify-center text-gray-400">
        <Loader2 className="w-6 h-6 animate-spin mr-2" />
        Loading map...
      </div>
    ),
  }
);

interface GeoFile {
  path: string;
  filename: string;
  size_bytes: number;
  modified_at: string;
  workflow_id?: string;
  run_id?: string;
}

export default function MapPage() {
  const [files, setFiles] = useState<GeoFile[]>([]);
  const [selectedPath, setSelectedPath] = useState("");
  const [manualPath, setManualPath] = useState("");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [geoData, setGeoData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [loadingFiles, setLoadingFiles] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Fetch available geo files on mount
  useEffect(() => {
    fetch(`${API_URL}/api/geo/files`)
      .then((r) => r.json())
      .then((data) => setFiles(data.files || []))
      .catch(() => setFiles([]))
      .finally(() => setLoadingFiles(false));
  }, []);

  const loadGeoJSON = async (path: string) => {
    if (!path.trim()) return;
    setLoading(true);
    setError("");
    try {
      const r = await fetch(
        `${API_URL}/api/geo/serve?path=${encodeURIComponent(path.trim())}`
      );
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(err.detail || `Failed: ${r.status}`);
      }
      const data = await r.json();
      setGeoData(data);
      setSelectedPath(path.trim());
    } catch (e: unknown) {
      const err = e as Error;
      setError(err.message || "Failed to load file");
      setGeoData(null);
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (file: File) => {
    setLoading(true);
    setError("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      const r = await fetch(`${API_URL}/api/geo/upload`, {
        method: "POST",
        body: formData,
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(err.detail || `Upload failed: ${r.status}`);
      }
      const data = await r.json();
      setGeoData(data);
      setSelectedPath(file.name);
    } catch (e: unknown) {
      const err = e as Error;
      setError(err.message || "Failed to upload file");
      setGeoData(null);
    } finally {
      setLoading(false);
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes > 1_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`;
    return `${(bytes / 1_000).toFixed(1)} KB`;
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="h-14 border-b border-[var(--border-light)] flex items-center px-6 bg-white flex-shrink-0">
        <Globe className="w-5 h-5 text-primary-600 mr-2" />
        <h1 className="text-lg font-semibold text-gray-900">Map View</h1>
        <span className="ml-3 text-sm text-gray-500">
          Visualize geospatial workflow outputs
        </span>
      </div>

      {/* Controls bar */}
      <div className="border-b border-[var(--border-light)] bg-gray-50 px-6 py-3 flex-shrink-0">
        <div className="flex items-center gap-4 flex-wrap">
          {/* File selector */}
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-gray-500" />
            <select
              title="Select geo output file"
              className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 bg-white min-w-[280px]"
              value={selectedPath}
              onChange={(e) => {
                if (e.target.value) loadGeoJSON(e.target.value);
              }}
              disabled={loading}
            >
              <option value="">
                {loadingFiles
                  ? "Loading files..."
                  : files.length === 0
                  ? "No geo outputs found"
                  : "Select a geo output file..."}
              </option>
              {files.map((f) => (
                <option key={f.path} value={f.path}>
                  {f.filename} ({formatSize(f.size_bytes)})
                </option>
              ))}
            </select>
          </div>

          {/* Divider */}
          <div className="h-6 w-px bg-gray-300" />

          {/* Upload file button */}
          <div className="flex items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              title="Upload GeoJSON file"
              accept=".geojson,.json"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleFileUpload(file);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={loading}
              className="text-sm px-3 py-1.5 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 flex items-center gap-1.5"
            >
              <Upload className="w-3.5 h-3.5" />
              Upload File
            </button>
          </div>

          {/* Divider */}
          <div className="h-6 w-px bg-gray-300" />

          {/* Manual path input */}
          <div className="flex items-center gap-2 flex-1 min-w-[300px]">
            <MapPin className="w-4 h-4 text-gray-500 flex-shrink-0" />
            <input
              type="text"
              placeholder="Or paste file path from workflow output..."
              className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 flex-1"
              value={manualPath}
              onChange={(e) => setManualPath(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") loadGeoJSON(manualPath);
              }}
            />
            <button
              type="button"
              onClick={() => loadGeoJSON(manualPath)}
              disabled={loading || !manualPath.trim()}
              className="text-sm px-3 py-1.5 bg-gray-600 text-white rounded-lg hover:bg-gray-700 disabled:opacity-50 flex items-center gap-1.5"
            >
              Load
            </button>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="mt-2 flex items-center gap-2 text-sm text-red-600">
            <AlertCircle className="w-4 h-4" />
            {error}
          </div>
        )}
      </div>

      {/* Map area */}
      <div className="flex-1 relative">
        {loading && (
          <div className="absolute inset-0 z-[1001] bg-white/70 flex items-center justify-center">
            <Loader2 className="w-8 h-8 animate-spin text-primary-600" />
          </div>
        )}

        {geoData ? (
          <MapViewer geoData={geoData} />
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-gray-400">
            <Globe className="w-16 h-16 mb-4 opacity-30" />
            <p className="text-lg font-medium">No data loaded</p>
            <p className="text-sm mt-1">
              Upload a GeoJSON file, select a workflow output, or paste a file path
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
