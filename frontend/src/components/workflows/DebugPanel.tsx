"use client";

import { useState, useMemo } from "react";
import {
  Bug,
  X,
  ChevronDown,
  ChevronRight,
  Clock,
  Cpu,
  ArrowRight,
  AlertCircle,
  CheckCircle2,
  Layers,
  Workflow,
  Copy,
  Check,
} from "lucide-react";
import type { DebugEvent } from "@/types";

interface DebugPanelProps {
  events: DebugEvent[];
  visible: boolean;
  onClose: () => void;
}

type PhaseFilter = "all" | "compile" | "execute" | "summary";

function JsonBlock({ data, maxHeight = "max-h-60" }: { data: unknown; maxHeight?: string }) {
  const [copied, setCopied] = useState(false);
  const text = typeof data === "string" ? data : JSON.stringify(data, null, 2);

  const handleCopy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="relative group">
      <button
        type="button"
        onClick={handleCopy}
        className="absolute top-1.5 right-1.5 p-1 rounded hover:bg-gray-200 opacity-0 group-hover:opacity-100 transition-opacity z-10"
        title="Copy"
      >
        {copied ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3 text-gray-400" />}
      </button>
      <pre className={`text-[11px] font-mono bg-gray-50 border border-gray-200 rounded p-2 overflow-auto ${maxHeight} whitespace-pre-wrap break-words text-gray-700 leading-relaxed`}>
        {text}
      </pre>
    </div>
  );
}

function EventCard({ event, index }: { event: DebugEvent; index: number }) {
  const [expanded, setExpanded] = useState(false);

  const phaseColors: Record<string, string> = {
    compile: "bg-violet-100 text-violet-700",
    execute: "bg-blue-100 text-blue-700",
    summary: "bg-emerald-100 text-emerald-700",
  };

  const phaseIcons: Record<string, typeof Layers> = {
    compile: Layers,
    execute: Cpu,
    summary: Workflow,
  };

  const PhaseIcon = phaseIcons[event.phase] || Bug;
  const phaseColor = phaseColors[event.phase] || "bg-gray-100 text-gray-700";

  const isError = event.event.includes("error") || event.event.includes("fail");
  const isNodeIO = event.event === "node_input" || event.event === "node_output";
  const hasData = event.data && Object.keys(event.data).length > 0;

  const timeStr = event.timestamp
    ? new Date(event.timestamp).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit", fractionalSecondDigits: 3 })
    : "";

  return (
    <div className={`border rounded-lg overflow-hidden ${isError ? "border-red-200 bg-red-50/30" : "border-gray-200 bg-white"}`}>
      <button
        type="button"
        onClick={() => hasData && setExpanded(!expanded)}
        className={`w-full flex items-center gap-2 px-3 py-2 text-left ${hasData ? "cursor-pointer hover:bg-gray-50" : "cursor-default"}`}
      >
        {/* Index */}
        <span className="text-[10px] text-gray-400 w-5 text-right flex-shrink-0">
          {index + 1}
        </span>

        {/* Expand toggle */}
        {hasData ? (
          expanded ? <ChevronDown className="w-3 h-3 text-gray-400 flex-shrink-0" /> : <ChevronRight className="w-3 h-3 text-gray-400 flex-shrink-0" />
        ) : (
          <span className="w-3 h-3 flex-shrink-0" />
        )}

        {/* Phase badge */}
        <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded ${phaseColor} flex-shrink-0 flex items-center gap-1`}>
          <PhaseIcon className="w-2.5 h-2.5" />
          {event.phase}
        </span>

        {/* Event name */}
        <span className={`text-xs font-medium flex-1 ${isError ? "text-red-600" : "text-gray-700"}`}>
          {event.event}
          {event.node_id && (
            <span className="text-gray-400 font-normal ml-1">
              [{event.label || event.node_id}]
            </span>
          )}
        </span>

        {/* Data flow indicator for node I/O */}
        {isNodeIO && (
          <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium flex-shrink-0 ${
            event.event === "node_input" ? "bg-amber-100 text-amber-700" : "bg-green-100 text-green-700"
          }`}>
            {event.event === "node_input" ? "IN" : "OUT"}
          </span>
        )}

        {/* Duration if available */}
        {event.data?.duration_ms != null && (
          <span className="text-[10px] text-gray-400 flex-shrink-0 flex items-center gap-0.5">
            <Clock className="w-2.5 h-2.5" />
            {Number(event.data.duration_ms) >= 1000 ? (Number(event.data.duration_ms) / 1000).toFixed(1) + "s" : Number(event.data.duration_ms).toFixed(0) + "ms"}
          </span>
        )}

        {/* Timestamp */}
        {timeStr && (
          <span className="text-[10px] text-gray-300 flex-shrink-0">
            {timeStr}
          </span>
        )}

        {/* Error icon */}
        {isError && <AlertCircle className="w-3 h-3 text-red-500 flex-shrink-0" />}
      </button>

      {/* Expanded data */}
      {expanded && hasData && (
        <div className="border-t border-gray-100 px-3 py-2 space-y-2">
          {/* For node_input / node_output, show structured view */}
          {isNodeIO && event.data?.state ? (
            <div className="space-y-2">
              <div className="text-[10px] font-semibold text-gray-500 uppercase">State Snapshot</div>
              <JsonBlock data={event.data.state} />
              {!!event.data.error && (
                <div className="mt-1">
                  <div className="text-[10px] font-semibold text-red-500 uppercase">Error</div>
                  <div className="text-xs text-red-600 font-mono bg-red-50 rounded p-2">{String(event.data.error)}</div>
                </div>
              )}
              {!!event.data.output_preview && (
                <div className="mt-1">
                  <div className="text-[10px] font-semibold text-gray-500 uppercase">Output Preview</div>
                  <div className="text-xs text-gray-700 font-mono bg-gray-50 rounded p-2 whitespace-pre-wrap">{String(event.data.output_preview)}</div>
                </div>
              )}
            </div>
          ) : (
            <JsonBlock data={event.data} />
          )}
        </div>
      )}
    </div>
  );
}

function DataFlowView({ events }: { events: DebugEvent[] }) {
  // Build per-node input/output pairs
  const nodeFlows = useMemo(() => {
    const flows: Record<string, { input?: DebugEvent; output?: DebugEvent }> = {};
    for (const ev of events) {
      if (ev.event === "node_input" && ev.node_id) {
        if (!flows[ev.node_id]) flows[ev.node_id] = {};
        flows[ev.node_id].input = ev;
      }
      if (ev.event === "node_output" && ev.node_id) {
        if (!flows[ev.node_id]) flows[ev.node_id] = {};
        flows[ev.node_id].output = ev;
      }
    }
    return flows;
  }, [events]);

  const nodeIds = Object.keys(nodeFlows);
  if (nodeIds.length === 0) {
    return <div className="text-xs text-gray-400 py-4 text-center">No node execution data yet.</div>;
  }

  return (
    <div className="space-y-3">
      {nodeIds.map((nid, idx) => {
        const flow = nodeFlows[nid];
        const label = flow.input?.label || flow.output?.label || nid;
        const duration = flow.output?.data?.duration_ms;
        const hasError = !!flow.output?.data?.error;

        return (
          <div key={nid}>
            {/* Node header */}
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-t-lg border border-b-0 ${
              hasError ? "bg-red-50 border-red-200" : "bg-gray-50 border-gray-200"
            }`}>
              {hasError ? (
                <AlertCircle className="w-3.5 h-3.5 text-red-500" />
              ) : (
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
              )}
              <span className="text-xs font-semibold text-gray-700">{label}</span>
              <span className="text-[10px] text-gray-400">({nid})</span>
              {duration != null && (
                <span className="text-[10px] text-gray-400 ml-auto flex items-center gap-0.5">
                  <Clock className="w-2.5 h-2.5" />
                  {Number(duration) >= 1000 ? (Number(duration) / 1000).toFixed(1) + "s" : Number(duration).toFixed(0) + "ms"}
                </span>
              )}
            </div>

            {/* I/O panels */}
            <div className="grid grid-cols-2 gap-0 border border-gray-200 rounded-b-lg overflow-hidden">
              <div className="p-2 border-r border-gray-200 bg-amber-50/30">
                <div className="text-[9px] font-bold text-amber-600 uppercase mb-1">Input State</div>
                {flow.input?.data?.state ? (
                  <JsonBlock data={flow.input.data.state} maxHeight="max-h-32" />
                ) : (
                  <span className="text-[10px] text-gray-400">—</span>
                )}
              </div>
              <div className="p-2 bg-green-50/30">
                <div className="text-[9px] font-bold text-green-600 uppercase mb-1">Output State</div>
                {flow.output?.data?.state ? (
                  <JsonBlock data={flow.output.data.state} maxHeight="max-h-32" />
                ) : (
                  <span className="text-[10px] text-gray-400">—</span>
                )}
              </div>
            </div>

            {/* Arrow to next node */}
            {idx < nodeIds.length - 1 && (
              <div className="flex justify-center py-1">
                <ArrowRight className="w-4 h-4 text-gray-300 rotate-90" />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

type TabType = "timeline" | "dataflow";

export default function DebugPanel({ events, visible, onClose }: DebugPanelProps) {
  const [phaseFilter, setPhaseFilter] = useState<PhaseFilter>("all");
  const [tab, setTab] = useState<TabType>("timeline");

  const filtered = useMemo(() => {
    if (phaseFilter === "all") return events;
    return events.filter((e) => e.phase === phaseFilter);
  }, [events, phaseFilter]);

  const phaseCounts = useMemo(() => {
    const counts = { compile: 0, execute: 0, summary: 0 };
    for (const ev of events) {
      if (ev.phase in counts) counts[ev.phase as keyof typeof counts]++;
    }
    return counts;
  }, [events]);

  // Extract summary event
  const summaryEvent = useMemo(
    () => events.find((e) => e.event === "execution_summary"),
    [events]
  );

  if (!visible) return null;

  return (
    <div className="absolute top-0 right-0 bottom-0 w-[420px] bg-white border-l border-[var(--border-light)] shadow-lg z-30 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--border-light)] bg-gray-50">
        <div className="flex items-center gap-2">
          <Bug className="w-4 h-4 text-violet-500" />
          <span className="text-xs font-semibold text-gray-700">Debug Panel</span>
          <span className="text-[10px] text-gray-400">{events.length} events</span>
        </div>
        <button type="button" onClick={onClose} className="p-1 hover:bg-gray-200 rounded" title="Close debug panel">
          <X className="w-4 h-4 text-gray-500" />
        </button>
      </div>

      {/* Summary bar */}
      {summaryEvent && (
        <div className="px-4 py-2 border-b border-[var(--border-light)] bg-emerald-50/50 flex items-center gap-4 text-[10px]">
          <span className="text-emerald-700 font-semibold">
            Total: {(Number(summaryEvent.data?.total_duration_ms || 0) / 1000).toFixed(1)}s
          </span>
          <span className="text-gray-500">
            Nodes: {String(summaryEvent.data?.nodes_executed || 0)}
          </span>
          {!!summaryEvent.data?.execution_order && (
            <span className="text-gray-400 truncate flex-1" title={String(summaryEvent.data.execution_order)}>
              Flow: {Array.isArray(summaryEvent.data.execution_order) ? (summaryEvent.data.execution_order as string[]).join(" → ") : String(summaryEvent.data.execution_order)}
            </span>
          )}
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-[var(--border-light)]">
        <button
          type="button"
          onClick={() => setTab("timeline")}
          className={`flex-1 text-xs py-2 font-medium border-b-2 transition-colors ${
            tab === "timeline" ? "border-violet-500 text-violet-600" : "border-transparent text-gray-400 hover:text-gray-600"
          }`}
        >
          Timeline
        </button>
        <button
          type="button"
          onClick={() => setTab("dataflow")}
          className={`flex-1 text-xs py-2 font-medium border-b-2 transition-colors ${
            tab === "dataflow" ? "border-violet-500 text-violet-600" : "border-transparent text-gray-400 hover:text-gray-600"
          }`}
        >
          Data Flow
        </button>
      </div>

      {/* Phase filter (timeline only) */}
      {tab === "timeline" && (
        <div className="flex gap-1.5 px-4 py-2 border-b border-[var(--border-light)]">
          {(["all", "compile", "execute", "summary"] as PhaseFilter[]).map((phase) => (
            <button
              key={phase}
              type="button"
              onClick={() => setPhaseFilter(phase)}
              className={`text-[10px] px-2 py-0.5 rounded-full font-medium transition-colors ${
                phaseFilter === phase
                  ? "bg-violet-100 text-violet-700"
                  : "text-gray-400 hover:bg-gray-100 hover:text-gray-600"
              }`}
            >
              {phase === "all" ? `All (${events.length})` : `${phase} (${phaseCounts[phase as keyof typeof phaseCounts] || 0})`}
            </button>
          ))}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {tab === "timeline" ? (
          filtered.length === 0 ? (
            <div className="text-xs text-gray-400 py-8 text-center">
              {events.length === 0 ? "Waiting for debug events..." : "No events match filter."}
            </div>
          ) : (
            filtered.map((ev, i) => (
              <EventCard key={`${ev.event}-${ev.node_id || ""}-${ev.timestamp || i}`} event={ev} index={i} />
            ))
          )
        ) : (
          <DataFlowView events={events} />
        )}
      </div>
    </div>
  );
}
