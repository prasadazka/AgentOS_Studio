"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams } from "next/navigation";
import { ReactFlowProvider } from "@xyflow/react";
import type { Node, Edge } from "@xyflow/react";
import { api, API_URL } from "@/lib/api";
import type { Workflow, WorkflowNodeData, WorkflowInputField, RunNodeState, DebugEvent } from "@/types";

import WorkflowCanvas from "@/components/workflows/WorkflowCanvas";
import NodePalette from "@/components/workflows/NodePalette";
import NodeConfigPanel from "@/components/workflows/NodeConfigPanel";
import WorkflowToolbar from "@/components/workflows/WorkflowToolbar";
import RunOverlay from "@/components/workflows/RunOverlay";
import HITLDialog from "@/components/workflows/HITLDialog";
import WorkflowInputDialog from "@/components/workflows/WorkflowInputDialog";
import DebugPanel from "@/components/workflows/DebugPanel";

export default function WorkflowEditorPage() {
  const params = useParams();
  const wid = params.id as string;

  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [autoSave, setAutoSave] = useState(true);
  const [saveToast, setSaveToast] = useState<"saved" | "off" | null>(null);
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Execution state
  const [isRunning, setIsRunning] = useState(false);
  const [runStatus, setRunStatus] = useState("");
  const [nodeStatuses, setNodeStatuses] = useState<Record<string, RunNodeState>>({});
  const [runOutput, setRunOutput] = useState("");
  const [runError, setRunError] = useState("");
  const [hitlRequest, setHitlRequest] = useState<{ type: string; prompt: string; node_id: string; context?: Record<string, unknown> } | null>(null);
  const runIdRef = useRef<string>("");

  // Input dialog state
  const [showInputDialog, setShowInputDialog] = useState(false);

  // Debug state
  const [debugEvents, setDebugEvents] = useState<DebugEvent[]>([]);
  const [showDebug, setShowDebug] = useState(false);

  // Validation toast
  const [validationToast, setValidationToast] = useState<string | null>(null);
  const validationTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Track local node/edge state for saving
  const nodesRef = useRef<Node[]>([]);
  const edgesRef = useRef<Edge[]>([]);

  // Live nodes for NodePalette disabled states
  const [canvasNodes, setCanvasNodes] = useState<Node[]>([]);

  useEffect(() => {
    async function load() {
      try {
        const wf = await api<Workflow>(`/api/workflows/${wid}`);
        setWorkflow(wf);
        nodesRef.current = wf.graph_json?.nodes || [];
        edgesRef.current = wf.graph_json?.edges || [];
        setCanvasNodes(nodesRef.current);
      } catch (e) {
        console.error("Failed to load workflow:", e);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [wid]);

  // Ctrl+S to save
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        handleSave();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  // Show a toast notification for 2 seconds
  const showToast = useCallback((type: "saved" | "off") => {
    setSaveToast(type);
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setSaveToast(null), 2000);
  }, []);

  // Toggle auto-save on/off
  const handleAutoSaveToggle = useCallback(() => {
    setAutoSave((prev) => {
      const next = !prev;
      if (!next) {
        // Turning off — cancel any pending auto-save
        if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
        showToast("off");
      }
      return next;
    });
  }, [showToast]);

  // Validation error handler — shows toast for 3 seconds
  const handleValidationError = useCallback((message: string) => {
    setValidationToast(message);
    if (validationTimerRef.current) clearTimeout(validationTimerRef.current);
    validationTimerRef.current = setTimeout(() => setValidationToast(null), 3000);
  }, []);

  // Unified graph change handler — triggers auto-save debounce
  const handleGraphChange = useCallback((nodes: Node[], edges: Edge[]) => {
    nodesRef.current = nodes;
    edgesRef.current = edges;
    setCanvasNodes(nodes);
    // Schedule auto-save after 2s of inactivity
    if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
    autoSaveTimerRef.current = setTimeout(async () => {
      // Read autoSave from ref to avoid stale closure
      setAutoSave((current) => {
        if (current) {
          // Perform the save and show toast
          setIsSaving(true);
          api<Workflow>(`/api/workflows/${wid}`, {
            method: "PUT",
            body: JSON.stringify({
              graph_json: { nodes: nodesRef.current, edges: edgesRef.current },
            }),
          })
            .then((updated) => {
              setWorkflow(updated);
              showToast("saved");
            })
            .catch(console.error)
            .finally(() => setIsSaving(false));
        }
        return current;
      });
    }, 2000);
  }, [wid, showToast]);

  // Update node data from config panel — also schedules auto-save
  const handleNodeUpdate = useCallback((nodeId: string, data: Partial<WorkflowNodeData>) => {
    nodesRef.current = nodesRef.current.map((n) =>
      n.id === nodeId ? { ...n, data: { ...n.data, ...data } } : n
    );
    setSelectedNode((prev) =>
      prev && prev.id === nodeId ? { ...prev, data: { ...prev.data, ...data } } : prev
    );
    setWorkflow((prev) => {
      if (!prev) return prev;
      const updated = {
        ...prev,
        graph_json: { ...prev.graph_json, nodes: [...nodesRef.current], edges: [...edgesRef.current] },
      };
      return updated;
    });
    // Trigger auto-save debounce on config changes too
    if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
    autoSaveTimerRef.current = setTimeout(() => {
      setAutoSave((current) => {
        if (current) {
          setIsSaving(true);
          api<Workflow>(`/api/workflows/${wid}`, {
            method: "PUT",
            body: JSON.stringify({
              graph_json: { nodes: nodesRef.current, edges: edgesRef.current },
            }),
          })
            .then((updated) => { setWorkflow(updated); showToast("saved"); })
            .catch(console.error)
            .finally(() => setIsSaving(false));
        }
        return current;
      });
    }, 2000);
  }, [wid, showToast]);

  const handleSave = useCallback(async () => {
    if (!workflow) return;
    setIsSaving(true);
    try {
      const updated = await api<Workflow>(`/api/workflows/${wid}`, {
        method: "PUT",
        body: JSON.stringify({
          name: workflow.name,
          description: workflow.description,
          graph_json: {
            nodes: nodesRef.current,
            edges: edgesRef.current,
          },
        }),
      });
      setWorkflow(updated);
    } catch (e) {
      alert(`Save failed: ${e}`);
    } finally {
      setIsSaving(false);
    }
  }, [workflow, wid]);

  // Get input fields from Start node
  const getStartNodeFields = useCallback((): WorkflowInputField[] => {
    const startNode = nodesRef.current.find((n) => n.type === "start" || (n.data as WorkflowNodeData)?.type === "start");
    if (!startNode) return [];
    return ((startNode.data as WorkflowNodeData)?.inputFields as WorkflowInputField[]) || [];
  }, []);

  // Step 1: User clicks Run → save first, then show input dialog
  const handleRun = useCallback(async () => {
    if (!workflow) return;
    await handleSave();
    setShowInputDialog(true);
  }, [workflow, handleSave]);

  // Step 2: User submits the input form → execute workflow
  const handleExecute = useCallback(async (inputValues: Record<string, string>) => {
    setShowInputDialog(false);

    // Build input_text from values
    const fields = getStartNodeFields();
    let inputText: string;
    if (fields.length > 0) {
      // Structured input: JSON with field names
      inputText = JSON.stringify(inputValues);
    } else {
      // Simple text input
      inputText = inputValues["_input"] || "";
    }

    setIsRunning(true);
    setRunStatus("running");
    setNodeStatuses({});
    setRunOutput("");
    setRunError("");
    setHitlRequest(null);
    setDebugEvents([]);
    setShowDebug(true);

    try {
      const response = await fetch(`${API_URL}/api/workflows/${wid}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input_text: inputText }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      if (!response.body) throw new Error("No response body");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;

          try {
            const event = JSON.parse(raw);

            switch (event.type) {
              case "node_completed":
                setNodeStatuses((prev) => ({
                  ...prev,
                  [event.node_id]: { status: "completed", output: event.output },
                }));
                break;

              case "node_started":
                setNodeStatuses((prev) => ({
                  ...prev,
                  [event.node_id]: { status: "running" },
                }));
                break;

              case "hitl_required":
                setHitlRequest(event.request);
                runIdRef.current = event.run_id || runIdRef.current;
                setRunStatus("paused");
                break;

              case "hitl_resolved":
                setHitlRequest(null);
                setRunStatus("running");
                setNodeStatuses((prev) => ({
                  ...prev,
                  [event.node_id]: { status: "completed", output: "Approved" },
                }));
                break;

              case "hitl_rejected":
                setHitlRequest(null);
                setRunStatus("error");
                setRunError(`HITL ${event.reason} at ${event.node_id}`);
                break;

              case "workflow_completed":
                setRunStatus("completed");
                setRunOutput(event.output || "");
                runIdRef.current = event.run_id || "";
                break;

              case "validation_error":
                setRunStatus("error");
                setRunError("Validation failed:\n" + (event.errors || []).join("\n"));
                break;

              case "error":
                setRunStatus("error");
                setRunError(event.message);
                break;

              case "debug":
                setDebugEvents((prev) => [...prev, { ...event, timestamp: Date.now() }]);
                break;

              case "done":
                break;
            }
          } catch {
            // skip malformed
          }
        }
      }
    } catch (e) {
      setRunStatus("error");
      setRunError(e instanceof Error ? e.message : "Connection failed");
    } finally {
      setIsRunning(false);
    }
  }, [wid, getStartNodeFields]);

  const handleHitlRespond = useCallback(async (action: "approve" | "reject", comment?: string) => {
    if (!runIdRef.current) return;
    try {
      await api(`/api/workflows/${wid}/runs/${runIdRef.current}/hitl-respond`, {
        method: "POST",
        body: JSON.stringify({ action, comment }),
      });
    } catch (e) {
      console.error("HITL respond failed:", e);
    }
    setHitlRequest(null);
  }, [wid]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-sm text-gray-400">Loading workflow...</div>
      </div>
    );
  }

  if (!workflow) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-sm text-red-500">Workflow not found</div>
      </div>
    );
  }

  return (
    <ReactFlowProvider>
      <div className="flex flex-col h-full">
        <WorkflowToolbar
          name={workflow.name}
          status={isRunning ? runStatus : workflow.status}
          onNameChange={(name) => setWorkflow((prev) => prev ? { ...prev, name } : prev)}
          onSave={handleSave}
          onRun={handleRun}
          isSaving={isSaving}
          isRunning={isRunning}
          autoSave={autoSave}
          onAutoSaveToggle={handleAutoSaveToggle}
          saveToast={saveToast}
        />

        <div className="flex flex-1 overflow-hidden relative">
          {!isRunning && <NodePalette nodes={canvasNodes} />}

          <WorkflowCanvas
            initialNodes={workflow.graph_json?.nodes || []}
            initialEdges={workflow.graph_json?.edges || []}
            onGraphChange={handleGraphChange}
            onNodeSelect={setSelectedNode}
            nodeStatuses={isRunning ? nodeStatuses : undefined}
            readOnly={isRunning}
            onValidationError={handleValidationError}
          />

          {selectedNode && !isRunning && (
            <NodeConfigPanel
              node={selectedNode}
              onUpdate={handleNodeUpdate}
              onClose={() => setSelectedNode(null)}
            />
          )}

          {/* Run overlay */}
          {(isRunning || runStatus) && runStatus !== "" && (
            <RunOverlay
              nodeStatuses={nodeStatuses}
              runStatus={runStatus}
              output={runOutput}
              error={runError}
              onClose={() => { setRunStatus(""); setNodeStatuses({}); }}
            />
          )}

          {/* HITL Dialog */}
          {hitlRequest && (
            <HITLDialog
              request={hitlRequest}
              onRespond={handleHitlRespond}
              onClose={() => setHitlRequest(null)}
            />
          )}

          {/* Debug Panel */}
          {showDebug && (
            <DebugPanel
              events={debugEvents}
              visible={showDebug}
              onClose={() => setShowDebug(false)}
            />
          )}
        </div>

        {/* Workflow Input Dialog */}
        {showInputDialog && (
          <WorkflowInputDialog
            workflowId={wid}
            workflowName={workflow.name}
            fields={getStartNodeFields()}
            onSubmit={handleExecute}
            onCancel={() => setShowInputDialog(false)}
          />
        )}

        {/* Validation error toast */}
        {validationToast && (
          <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 animate-in fade-in slide-in-from-bottom-2">
            <div className="flex items-center gap-2 px-4 py-2.5 bg-red-600 text-white rounded-lg shadow-lg text-sm font-medium">
              <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
              {validationToast}
            </div>
          </div>
        )}
      </div>
    </ReactFlowProvider>
  );
}
