"use client";

import { useCallback, useRef, useMemo, useEffect, useState } from "react";
import {
  ReactFlow,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection,
  type Node,
  type Edge,
  type NodeTypes,
  type OnNodesChange,
  type OnEdgesChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import StartNode from "./nodes/StartNode";
import EndNode from "./nodes/EndNode";
import AgentNode from "./nodes/AgentNode";
import ToolNode from "./nodes/ToolNode";
import ConditionNode from "./nodes/ConditionNode";
import ApprovalNode from "./nodes/ApprovalNode";
import type { WorkflowNodeType, WorkflowNodeData, RunNodeState } from "@/types";

const NODE_DEFAULTS: Record<WorkflowNodeType, Partial<WorkflowNodeData>> = {
  start: { type: "start", label: "Start" },
  end: { type: "end", label: "End" },
  agent: { type: "agent", label: "Agent", agentName: "" },
  tool: { type: "tool", label: "Tool", toolName: "" },
  condition: { type: "condition", label: "Condition", expression: "has_error" },
  approval: { type: "approval", label: "Approval", approvalPrompt: "Approval required", approvalTimeout: 300 },
};

const MAX_NODES = 25;

let idCounter = 0;
function newId() {
  return `node_${++idCounter}_${Date.now()}`;
}

interface WorkflowCanvasProps {
  initialNodes: Node[];
  initialEdges: Edge[];
  onGraphChange?: (nodes: Node[], edges: Edge[]) => void;
  onNodeSelect?: (node: Node | null) => void;
  nodeStatuses?: Record<string, RunNodeState>;
  readOnly?: boolean;
  onValidationError?: (message: string) => void;
}

export default function WorkflowCanvas({
  initialNodes,
  initialEdges,
  onGraphChange,
  onNodeSelect,
  nodeStatuses,
  readOnly = false,
  onValidationError,
}: WorkflowCanvasProps) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Right-click context menu for edges
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; edgeId: string } | null>(null);

  // Sync nodes/edges when parent pushes updates (e.g. from config panel)
  useEffect(() => {
    setNodes(initialNodes);
  }, [initialNodes, setNodes]);
  useEffect(() => {
    setEdges(initialEdges);
  }, [initialEdges, setEdges]);

  // Keep refs in sync for parent callbacks
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  useEffect(() => { nodesRef.current = nodes; }, [nodes]);
  useEffect(() => { edgesRef.current = edges; }, [edges]);

  // Notify parent after any change
  const notifyChange = useCallback(() => {
    setTimeout(() => {
      onGraphChange?.(nodesRef.current, edgesRef.current);
    }, 0);
  }, [onGraphChange]);

  const nodeTypes: NodeTypes = useMemo(
    () => ({
      start: StartNode,
      end: EndNode,
      agent: AgentNode,
      tool: ToolNode,
      condition: ConditionNode,
      approval: ApprovalNode,
    }),
    []
  );

  // Inject execution status into node data so each node can render its own indicator
  const styledNodes = useMemo(() => {
    if (!nodeStatuses) return nodes;
    return nodes.map((n) => {
      const status = nodeStatuses[n.id];
      if (!status) return { ...n, data: { ...n.data, _runStatus: undefined } };
      return { ...n, data: { ...n.data, _runStatus: status.status } };
    });
  }, [nodes, nodeStatuses]);

  const onConnect = useCallback(
    (connection: Connection) => {
      if (readOnly) return;
      setEdges((eds) => addEdge(
        { ...connection, animated: true, style: { stroke: "#94a3b8", strokeWidth: 2 } },
        eds
      ));
      notifyChange();
    },
    [setEdges, notifyChange, readOnly]
  );

  const handleNodesChange: OnNodesChange = useCallback(
    (changes) => {
      if (readOnly) return;
      onNodesChange(changes);
      notifyChange();
    },
    [onNodesChange, notifyChange, readOnly]
  );

  const handleEdgesChange: OnEdgesChange = useCallback(
    (changes) => {
      if (readOnly) return;
      onEdgesChange(changes);
      notifyChange();
    },
    [onEdgesChange, notifyChange, readOnly]
  );

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      if (readOnly) return;
      e.preventDefault();

      const nodeType = e.dataTransfer.getData("application/workflow-node") as WorkflowNodeType;
      if (!nodeType) return;

      // Validation: enforce 1 Start, 1 End, max nodes
      if (nodeType === "start" && nodes.some((n) => n.data?.type === "start")) {
        onValidationError?.("Only one Start node allowed per workflow");
        return;
      }
      if (nodeType === "end" && nodes.some((n) => n.data?.type === "end")) {
        onValidationError?.("Only one End node allowed per workflow");
        return;
      }
      if (nodes.length >= MAX_NODES) {
        onValidationError?.(`Maximum ${MAX_NODES} nodes reached`);
        return;
      }

      const wrapper = reactFlowWrapper.current;
      if (!wrapper) return;

      const bounds = wrapper.getBoundingClientRect();
      const position = {
        x: e.clientX - bounds.left - 80,
        y: e.clientY - bounds.top - 20,
      };

      const newNode: Node = {
        id: newId(),
        type: nodeType,
        position,
        data: { ...NODE_DEFAULTS[nodeType] } as WorkflowNodeData,
      };

      setNodes((nds) => [...nds, newNode]);
      notifyChange();
    },
    [setNodes, notifyChange, readOnly, nodes, onValidationError]
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeSelect?.(node);
    },
    [onNodeSelect]
  );

  const onPaneClick = useCallback(() => {
    onNodeSelect?.(null);
    setContextMenu(null);
  }, [onNodeSelect]);

  // Right-click on edge to show delete menu
  const onEdgeContextMenu = useCallback(
    (event: React.MouseEvent, edge: Edge) => {
      if (readOnly) return;
      event.preventDefault();
      setContextMenu({ x: event.clientX, y: event.clientY, edgeId: edge.id });
    },
    [readOnly]
  );

  // Delete edge from context menu
  const handleDeleteEdge = useCallback(() => {
    if (!contextMenu) return;
    setEdges((eds) => eds.filter((e) => e.id !== contextMenu.edgeId));
    setContextMenu(null);
    notifyChange();
  }, [contextMenu, setEdges, notifyChange]);

  // Close context menu on click outside
  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [contextMenu]);

  return (
    <div ref={reactFlowWrapper} className="flex-1 h-full relative">
      <ReactFlow
        nodes={styledNodes}
        edges={edges}
        onNodesChange={handleNodesChange}
        onEdgesChange={handleEdgesChange}
        onConnect={onConnect}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        onEdgeContextMenu={onEdgeContextMenu}
        nodeTypes={nodeTypes}
        fitView
        deleteKeyCode={readOnly ? null : "Backspace"}
        defaultEdgeOptions={{ animated: true, style: { stroke: "#94a3b8", strokeWidth: 2 } }}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={!readOnly}
        nodesConnectable={!readOnly}
        elementsSelectable
        snapToGrid
        snapGrid={[20, 20]}
      >
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(n) => {
            const colors: Record<string, string> = {
              start: "#10b981", end: "#ef4444", agent: "#3b82f6",
              tool: "#a855f7", condition: "#f59e0b", approval: "#14b8a6",
            };
            return colors[n.type || ""] || "#94a3b8";
          }}
          className="!bg-gray-50 !border-[var(--border-light)]"
        />
        {/* Grid lines background like n8n */}
        <Background variant={BackgroundVariant.Lines} gap={20} size={1} color="#f0f0f0" />
        <Background id="bg2" variant={BackgroundVariant.Lines} gap={100} size={1} color="#e2e8f0" />
      </ReactFlow>

      {/* Edge right-click context menu */}
      {contextMenu && (
        <div
          className="fixed z-50 bg-white rounded-lg shadow-lg border border-[var(--border-light)] py-1 min-w-[140px]"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            type="button"
            onClick={handleDeleteEdge}
            className="w-full flex items-center gap-2 px-3 py-2 text-xs text-red-600 hover:bg-red-50 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
            Delete Connection
          </button>
        </div>
      )}
    </div>
  );
}

export { NODE_DEFAULTS, newId };
