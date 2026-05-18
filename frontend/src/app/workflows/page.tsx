"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Plus, Search } from "lucide-react";
import Header from "@/components/layout/Header";
import WorkflowCard from "@/components/workflows/WorkflowCard";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { api } from "@/lib/api";
import type { Workflow } from "@/types";

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<Workflow | null>(null);

  useEffect(() => {
    loadWorkflows();
  }, []);

  async function loadWorkflows() {
    try {
      const data = await api<{ workflows: Workflow[] }>("/api/workflows");
      setWorkflows(data.workflows);
    } catch (e) {
      console.error("Failed to load workflows:", e);
    } finally {
      setLoading(false);
    }
  }

  function handleDelete(id: string) {
    const wf = workflows.find((w) => w.id === id);
    if (wf) setDeleteTarget(wf);
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    try {
      await api(`/api/workflows/${deleteTarget.id}`, { method: "DELETE" });
      setWorkflows((prev) => prev.filter((w) => w.id !== deleteTarget.id));
    } catch (e) {
      alert(`Failed to delete: ${e}`);
    } finally {
      setDeleteTarget(null);
    }
  }

  const filtered = workflows.filter((w) =>
    w.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="flex flex-col h-full">
      <Header title="Workflows" />

      <div className="flex-1 p-6">
        {/* Toolbar */}
        <div className="flex items-center justify-between mb-5">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="Search workflows..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 pr-4 py-2 text-sm bg-white border border-[var(--border-light)] rounded-lg w-72 focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500"
            />
          </div>
          <Link
            href="/workflows/new"
            className="flex items-center gap-2 px-4 py-2.5 bg-primary-600 text-white text-sm font-medium rounded-lg hover:bg-primary-700 transition-colors"
          >
            <Plus className="w-4 h-4" />
            New Workflow
          </Link>
        </div>

        {/* Grid */}
        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-36 bg-white rounded-lg border border-[var(--border-light)] animate-pulse" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-16">
            {search ? (
              <p className="text-gray-500 text-sm">No workflows match your search.</p>
            ) : (
              <div className="max-w-md mx-auto">
                <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-primary-50 flex items-center justify-center">
                  <svg className="w-8 h-8 text-primary-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
                  </svg>
                </div>
                <h3 className="text-base font-semibold text-gray-800 mb-1">Build your first workflow</h3>
                <p className="text-sm text-gray-500 mb-4">
                  Connect agents and tools visually to automate tasks. Drag nodes, draw connections, and add human approval steps.
                </p>
                <div className="grid grid-cols-3 gap-3 mb-6 text-left">
                  <div className="bg-blue-50 rounded-lg p-3 border border-blue-100">
                    <div className="text-[10px] font-semibold text-blue-600 mb-1">AGENTS</div>
                    <div className="text-[11px] text-blue-800">Run AI agents on your data</div>
                  </div>
                  <div className="bg-purple-50 rounded-lg p-3 border border-purple-100">
                    <div className="text-[10px] font-semibold text-purple-600 mb-1">TOOLS</div>
                    <div className="text-[11px] text-purple-800">Execute tools like SQL, CSV, search</div>
                  </div>
                  <div className="bg-teal-50 rounded-lg p-3 border border-teal-100">
                    <div className="text-[10px] font-semibold text-teal-600 mb-1">APPROVAL</div>
                    <div className="text-[11px] text-teal-800">Add human review checkpoints</div>
                  </div>
                </div>
                <Link
                  href="/workflows/new"
                  className="inline-flex items-center gap-2 px-5 py-2.5 bg-primary-600 text-white text-sm font-medium rounded-lg hover:bg-primary-700 transition-colors"
                >
                  <Plus className="w-4 h-4" />
                  Create Your First Workflow
                </Link>
              </div>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {filtered.map((wf) => (
              <WorkflowCard key={wf.id} workflow={wf} onDelete={handleDelete} />
            ))}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={!!deleteTarget}
        title="Delete Workflow"
        message={`Are you sure you want to delete "${deleteTarget?.name}"? This action cannot be undone.`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
