"""Workflow CRUD, compilation, execution, and HITL for AgentOS Studio."""

import json
import time
from typing import Any, Optional
from dotenv import load_dotenv

load_dotenv()

from db.database import get_db, generate_id, now_iso


# ---------------------------------------------------------------------------
# Workflows CRUD
# ---------------------------------------------------------------------------

def create_workflow(name: str, description: str = "", graph_json: Optional[dict] = None) -> dict[str, Any]:
    db = get_db()
    wid = generate_id()
    ts = now_iso()
    graph = json.dumps(graph_json or {"nodes": [], "edges": []})
    db.execute(
        "INSERT INTO workflows (id, name, description, graph_json, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (wid, name, description, graph, "draft", ts, ts),
    )
    db.commit()
    return _row_to_workflow(db.execute("SELECT * FROM workflows WHERE id = ?", (wid,)).fetchone())


def list_workflows() -> list[dict[str, Any]]:
    db = get_db()
    rows = db.execute("SELECT * FROM workflows ORDER BY updated_at DESC").fetchall()
    return [_row_to_workflow(r) for r in rows]


def get_workflow(wid: str) -> Optional[dict[str, Any]]:
    db = get_db()
    row = db.execute("SELECT * FROM workflows WHERE id = ?", (wid,)).fetchone()
    return _row_to_workflow(row) if row else None


def update_workflow(wid: str, name: Optional[str] = None, description: Optional[str] = None, graph_json: Optional[dict] = None, status: Optional[str] = None) -> Optional[dict[str, Any]]:
    db = get_db()
    row = db.execute("SELECT * FROM workflows WHERE id = ?", (wid,)).fetchone()
    if not row:
        return None
    ts = now_iso()
    if name is not None:
        db.execute("UPDATE workflows SET name = ?, updated_at = ? WHERE id = ?", (name, ts, wid))
    if description is not None:
        db.execute("UPDATE workflows SET description = ?, updated_at = ? WHERE id = ?", (description, ts, wid))
    if graph_json is not None:
        db.execute("UPDATE workflows SET graph_json = ?, updated_at = ? WHERE id = ?", (json.dumps(graph_json), ts, wid))
    if status is not None:
        db.execute("UPDATE workflows SET status = ?, updated_at = ? WHERE id = ?", (status, ts, wid))
    db.commit()
    return _row_to_workflow(db.execute("SELECT * FROM workflows WHERE id = ?", (wid,)).fetchone())


def delete_workflow(wid: str) -> bool:
    db = get_db()
    row = db.execute("SELECT id FROM workflows WHERE id = ?", (wid,)).fetchone()
    if not row:
        return False
    db.execute("DELETE FROM workflow_runs WHERE workflow_id = ?", (wid,))
    db.execute("DELETE FROM workflows WHERE id = ?", (wid,))
    db.commit()
    return True


def _row_to_workflow(row) -> dict[str, Any]:
    d = dict(row)
    d["graph_json"] = json.loads(d["graph_json"]) if isinstance(d["graph_json"], str) else d["graph_json"]
    return d


# ---------------------------------------------------------------------------
# Workflow Validation
# ---------------------------------------------------------------------------

MAX_NODES = 25


def validate_workflow(graph_json: dict) -> dict[str, Any]:
    """Validate a workflow graph. Returns {"errors": [...], "warnings": [...]}."""
    errors: list[str] = []
    warnings: list[str] = []
    nodes = graph_json.get("nodes", [])
    edges = graph_json.get("edges", [])

    # --- Structure checks (errors block execution) ---

    starts = [n for n in nodes if n.get("data", {}).get("type") == "start"]
    ends = [n for n in nodes if n.get("data", {}).get("type") == "end"]

    if len(starts) == 0:
        errors.append("Workflow must have a Start node")
    elif len(starts) > 1:
        errors.append(f"Only 1 Start node allowed (found {len(starts)})")

    if len(ends) == 0:
        errors.append("Workflow must have an End node")
    elif len(ends) > 1:
        errors.append(f"Only 1 End node allowed (found {len(ends)})")

    if len(nodes) > MAX_NODES:
        errors.append(f"Max {MAX_NODES} nodes allowed (found {len(nodes)})")

    # --- Node config checks (errors block execution) ---

    for n in nodes:
        ndata = n.get("data", {})
        ntype = ndata.get("type", "")
        label = ndata.get("label", n.get("id", "?"))

        if ntype == "agent" and not ndata.get("agentName"):
            errors.append(f"Agent node '{label}' has no agent selected")
        if ntype == "tool" and not ndata.get("toolName"):
            errors.append(f"Tool node '{label}' has no tool selected")

    # --- Connectivity checks (warnings, non-blocking) ---

    targets = {e["target"] for e in edges}
    sources = {e["source"] for e in edges}

    for n in nodes:
        ndata = n.get("data", {})
        ntype = ndata.get("type", "")
        label = ndata.get("label", n.get("id", "?"))

        if ntype != "start" and n["id"] not in targets:
            warnings.append(f"Node '{label}' has no incoming connection")
        if ntype != "end" and n["id"] not in sources:
            warnings.append(f"Node '{label}' has no outgoing connection")

    return {"errors": errors, "warnings": warnings}


# ---------------------------------------------------------------------------
# Workflow Runs
# ---------------------------------------------------------------------------

def create_run(workflow_id: str, input_text: str) -> dict[str, Any]:
    db = get_db()
    rid = generate_id()
    ts = now_iso()
    db.execute(
        "INSERT INTO workflow_runs (id, workflow_id, input_text, status, node_states_json, started_at) VALUES (?,?,?,?,?,?)",
        (rid, workflow_id, input_text, "running", "{}", ts),
    )
    db.commit()
    return _row_to_run(db.execute("SELECT * FROM workflow_runs WHERE id = ?", (rid,)).fetchone())


def list_runs(workflow_id: str) -> list[dict[str, Any]]:
    db = get_db()
    rows = db.execute("SELECT * FROM workflow_runs WHERE workflow_id = ? ORDER BY started_at DESC", (workflow_id,)).fetchall()
    return [_row_to_run(r) for r in rows]


def get_run(run_id: str) -> Optional[dict[str, Any]]:
    db = get_db()
    row = db.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()
    return _row_to_run(row) if row else None


def update_node_state(run_id: str, node_id: str, status: str, output: str = ""):
    db = get_db()
    row = db.execute("SELECT node_states_json FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        return
    # Safety: Gemini models may return content as a list — ensure string
    if isinstance(output, list):
        output = "\n".join(
            p.get("text", str(p)) if isinstance(p, dict) else str(p)
            for p in output
        )
    output = str(output)
    states = json.loads(row["node_states_json"])
    states[node_id] = {"status": status, "output": output[:500], "finished_at": now_iso()}
    db.execute("UPDATE workflow_runs SET node_states_json = ? WHERE id = ?", (json.dumps(states), run_id))
    db.commit()


def pause_for_hitl(run_id: str, node_id: str, request: dict):
    db = get_db()
    db.execute(
        "UPDATE workflow_runs SET status = 'paused', hitl_node_id = ?, hitl_request_json = ? WHERE id = ?",
        (node_id, json.dumps(request), run_id),
    )
    db.commit()


def submit_hitl_response(run_id: str, action: str, value: Optional[str] = None, comment: Optional[str] = None) -> bool:
    db = get_db()
    row = db.execute("SELECT id FROM workflow_runs WHERE id = ? AND status = 'paused'", (run_id,)).fetchone()
    if not row:
        return False
    response = {"action": action, "value": value, "comment": comment, "responded_at": now_iso()}
    db.execute(
        "UPDATE workflow_runs SET hitl_response_json = ?, status = 'running' WHERE id = ?",
        (json.dumps(response), run_id),
    )
    db.commit()
    return True


def wait_for_hitl_response(run_id: str, timeout: float = 300.0) -> Optional[dict]:
    """Poll DB every 2s waiting for HITL response. Returns response dict or None on timeout."""
    start = time.time()
    db = get_db()
    while time.time() - start < timeout:
        row = db.execute("SELECT hitl_response_json, status FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()
        if row and row["hitl_response_json"]:
            return json.loads(row["hitl_response_json"])
        if row and row["status"] not in ("paused", "running"):
            return None  # cancelled or errored
        time.sleep(2)
    return None


def complete_run(run_id: str, output: str = ""):
    db = get_db()
    # Safety: Gemini models may return content as a list of parts — ensure string
    if isinstance(output, list):
        output = "\n".join(
            p.get("text", str(p)) if isinstance(p, dict) else str(p)
            for p in output
        )
    db.execute(
        "UPDATE workflow_runs SET status = 'completed', output = ?, finished_at = ? WHERE id = ?",
        (str(output), now_iso(), run_id),
    )
    db.commit()


def fail_run(run_id: str, error: str):
    db = get_db()
    db.execute(
        "UPDATE workflow_runs SET status = 'error', error = ?, finished_at = ? WHERE id = ?",
        (error, now_iso(), run_id),
    )
    db.commit()


def _row_to_run(row) -> dict[str, Any]:
    d = dict(row)
    d["node_states"] = json.loads(d.pop("node_states_json", "{}"))
    d["hitl_request"] = json.loads(d.pop("hitl_request_json")) if d.get("hitl_request_json") else None
    d["hitl_response"] = json.loads(d.pop("hitl_response_json")) if d.get("hitl_response_json") else None
    return d


# ---------------------------------------------------------------------------
# Graph Compilation & Execution
# ---------------------------------------------------------------------------

def compile_and_execute(workflow: dict, input_text: str, run_id: str):
    """
    Generator that compiles the visual graph and executes it step by step.
    Yields SSE event dicts: {type, ...}
    """
    import time as _time
    from agent_os.workflows.builder import WorkflowBuilder, WorkflowState
    from agent_os.tools.global_registry import get_global_registry
    from agent_os.agents.base import BaseAgent
    from agent_os.config.loader import ConfigLoader
    from core.agent_manager import get_agent_config_path

    execution_start = _time.time()

    graph = workflow["graph_json"]

    # Pre-flight validation
    validation = validate_workflow(graph)
    if validation["errors"]:
        error_msg = "Workflow validation failed:\n" + "\n".join(f"- {e}" for e in validation["errors"])
        fail_run(run_id, error_msg)
        yield {"type": "validation_error", "errors": validation["errors"], "warnings": validation["warnings"]}
        yield {"type": "error", "message": error_msg}
        return
    if validation["warnings"]:
        yield {"type": "validation_warning", "warnings": validation["warnings"]}

    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    all_edges = graph.get("edges", [])

    # Filter out stale edges referencing deleted nodes
    edges = [e for e in all_edges if e["source"] in nodes and e["target"] in nodes]
    stale_count = len(all_edges) - len(edges)

    if not nodes or not edges:
        fail_run(run_id, "Empty workflow graph")
        yield {"type": "error", "message": "Empty workflow graph"}
        return

    # Debug: build node label map for readable names
    node_labels = {}
    for nid, node in nodes.items():
        ndata = node.get("data", {})
        label = ndata.get("label", ndata.get("agentName", ndata.get("toolName", nid)))
        ntype = ndata.get("type", node.get("type", ""))
        node_labels[nid] = f"{label} ({ntype})"

    # Debug: emit compilation start
    yield {
        "type": "debug",
        "phase": "compile",
        "event": "compile_start",
        "data": {
            "workflow_id": workflow.get("id", ""),
            "workflow_name": workflow.get("name", ""),
            "run_id": run_id,
            "input_text": input_text[:1000],
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "stale_edges_removed": stale_count,
            "node_summary": {nid: {"label": node_labels[nid], "type": nodes[nid].get("data", {}).get("type", "")} for nid in nodes},
            "edge_summary": [{"source": node_labels.get(e["source"], e["source"]), "target": node_labels.get(e["target"], e["target"])} for e in edges],
        },
    }

    # Build agents dict for WorkflowBuilder
    agents = {}
    registry = get_global_registry()
    agent_configs_debug = {}

    for nid, node in nodes.items():
        ndata = node.get("data", {})
        ntype = ndata.get("type", node.get("type", ""))

        if ntype == "agent":
            agent_name = ndata.get("agentName", "")
            has_inline_config = ndata.get("agentSystemPrompt") or ndata.get("agentTools")

            if agent_name or has_inline_config:
                try:
                    config = {}
                    overrides = {}

                    # Load base agent config if agentName is set
                    if agent_name:
                        config_path = get_agent_config_path(agent_name)
                        if config_path:
                            config = ConfigLoader.load_yaml(str(config_path))
                        else:
                            yield {"type": "debug", "phase": "compile", "event": "agent_not_found", "data": {"node_id": nid, "agent_name": agent_name}}
                            print(f"[workflow] Agent config not found for '{agent_name}' (node {nid}), using inline config")

                    # Apply per-node overrides / inline config
                    if ndata.get("agentModel"):
                        overrides["model"] = ndata["agentModel"]
                        config["model"] = ndata["agentModel"]
                    if ndata.get("agentTemperature") is not None:
                        overrides["temperature"] = ndata["agentTemperature"]
                        config["temperature"] = ndata["agentTemperature"]
                    if ndata.get("agentSystemPrompt"):
                        overrides["system_prompt"] = ndata["agentSystemPrompt"][:200] + "..." if len(ndata.get("agentSystemPrompt", "")) > 200 else ndata.get("agentSystemPrompt", "")
                        config["system_prompt"] = ndata["agentSystemPrompt"]
                    if ndata.get("agentTools"):
                        existing = config.get("tools", [])
                        config["tools"] = list(set(existing + ndata["agentTools"]))
                        overrides["extra_tools"] = ndata["agentTools"]

                    # Ensure minimal defaults for inline-only agents (no base agent)
                    if not config.get("name"):
                        config["name"] = ndata.get("label", nid)
                    if not config.get("model"):
                        config["model"] = "gpt-4o-mini"
                    if not config.get("tools"):
                        config["tools"] = []

                    agents[nid] = BaseAgent.from_config(config, tool_registry=registry)
                    agent_configs_debug[nid] = {
                        "agent_name": agent_name or "(inline)",
                        "model": config.get("model", ""),
                        "temperature": config.get("temperature", 0),
                        "tools": config.get("tools", []),
                        "overrides_applied": overrides,
                    }
                except Exception as e:
                    yield {"type": "debug", "phase": "compile", "event": "agent_load_error", "data": {"node_id": nid, "agent_name": agent_name or "(inline)", "error": str(e)}}
                    print(f"[workflow] Failed to load agent for node {nid}: {e}")

    # Debug: emit agent configs
    if agent_configs_debug:
        yield {"type": "debug", "phase": "compile", "event": "agents_loaded", "data": agent_configs_debug}

    # Wrap node functions to track start/complete + debug traces via shared event queue
    import queue as _queue_mod
    event_queue = _queue_mod.Queue()

    def _safe_state_snapshot(state, max_len=2000):
        """Create a safe serializable snapshot of state for debug"""
        snap = {}
        for k, v in state.items():
            sv = str(v)
            snap[k] = sv[:max_len] + "..." if len(sv) > max_len else sv
        return snap

    def _wrap_node_fn(original_fn, node_id):
        """Wrap a node function to emit start/complete events with debug data.
        Also handles HITL inside the wrapper since LangGraph strips unknown state keys."""
        def wrapped(state):
            t0 = _time.time()
            input_snapshot = _safe_state_snapshot(state)
            event_queue.put({"type": "node_started", "node_id": node_id})
            event_queue.put({
                "type": "_debug_node",
                "event": "node_input",
                "node_id": node_id,
                "label": node_labels.get(node_id, node_id),
                "data": {"state": input_snapshot},
            })
            update_node_state(run_id, node_id, "running")

            error_msg = None
            result = state
            try:
                result = original_fn(state)
            except Exception as e:
                error_msg = str(e)
                raise

            # Handle HITL inside the wrapper — LangGraph strips hitl_pending
            # from the state since it's not in WorkflowState TypedDict.
            # We block here (in the graph execution thread) until user responds.
            if isinstance(result, dict) and result.get("hitl_pending"):
                hitl_req = result.get("hitl_request", {})
                update_node_state(run_id, node_id, "paused")
                pause_for_hitl(run_id, node_id, hitl_req)
                event_queue.put({
                    "type": "_hitl_required",
                    "node_id": node_id,
                    "request": hitl_req,
                })

                timeout = hitl_req.get("timeout", 300)
                response = wait_for_hitl_response(run_id, timeout=timeout)

                if response and response.get("action") == "approve":
                    event_queue.put({"type": "_hitl_resolved", "node_id": node_id, "response": response})
                    update_node_state(run_id, node_id, "completed", "Approved")
                    # Preserve the previous node's output — don't overwrite with "Approved"
                    # The next agent needs the actual data, not just the approval status
                    if not result.get("output"):
                        result["output"] = "Approved"
                else:
                    reason = "Rejected" if response else "Timeout"
                    event_queue.put({"type": "_hitl_rejected", "node_id": node_id, "reason": reason})
                    update_node_state(run_id, node_id, "error", reason)
                    result["error"] = f"HITL {reason} at node {node_id}"

                # Clean up HITL fields before returning to LangGraph
                result.pop("hitl_pending", None)
                result.pop("hitl_request", None)

            duration = round((_time.time() - t0) * 1000)
            output_snapshot = _safe_state_snapshot(result if error_msg is None else state)
            event_queue.put({
                "type": "_debug_node",
                "event": "node_output",
                "node_id": node_id,
                "label": node_labels.get(node_id, node_id),
                "data": {
                    "state": output_snapshot,
                    "duration_ms": duration,
                    "error": error_msg,
                    "output_preview": str(output_snapshot.get("output", ""))[:500],
                },
            })
            return result
        return wrapped

    # Build WorkflowBuilder with manual graph construction
    builder = WorkflowBuilder(agents)

    # Register agent nodes — wrap functions BEFORE adding to graph
    for nid in list(agents.keys()):
        try:
            agent_fn = builder._create_agent_node(nid)
            wrapped_fn = _wrap_node_fn(agent_fn, nid)
            builder.graph.add_node(nid, wrapped_fn)
            builder._nodes_added.add(nid)
        except Exception as e:
            yield {"type": "debug", "phase": "compile", "event": "node_register_error", "data": {"node_id": nid, "error": str(e)}}
            print(f"[workflow] Failed to add agent node {nid}: {e}")

    # Add non-agent nodes (tool, condition, approval) — also wrapped
    for nid, node in nodes.items():
        ndata = node.get("data", {})
        ntype = ndata.get("type", node.get("type", ""))

        if ntype == "tool" and ndata.get("toolName"):
            tool_name = ndata["toolName"]
            tool_args = ndata.get("toolArgs", {})
            def _make_tool_fn(tn, ta):
                def tool_fn(state):
                    tool = registry.get(tn)
                    if tool:
                        # Resolve args: substitute {{output}} / {{input}} placeholders with state values
                        resolved_args = {}
                        prev_output = str(state.get("output", ""))
                        prev_input = str(state.get("input", ""))

                        # Pre-parse named input fields from JSON input_text
                        _input_fields = {}
                        try:
                            import json as _json2
                            _parsed_input = _json2.loads(prev_input)
                            if isinstance(_parsed_input, dict):
                                _input_fields = _parsed_input
                        except (ValueError, Exception):
                            pass

                        for k, v in ta.items():
                            if isinstance(v, str):
                                v = v.replace("{{output}}", prev_output).replace("{{input}}", prev_input)
                                # Resolve named input field refs: {{file_1}}, {{merge_mode}}, etc.
                                for field_name, field_value in _input_fields.items():
                                    v = v.replace("{{" + field_name + "}}", str(field_value))
                            # Boolean coercion: check if tool expects bool for this param
                            if isinstance(v, str) and v.lower() in ("yes", "true", "no", "false"):
                                try:
                                    import inspect as _insp
                                    sig = _insp.signature(tool._execute)
                                    if k in sig.parameters:
                                        ann = sig.parameters[k].annotation
                                        if ann is bool or sig.parameters[k].default is True or sig.parameters[k].default is False:
                                            resolved_args[k] = v.lower() in ("yes", "true", "1")
                                            continue
                                except Exception:
                                    pass
                            resolved_args[k] = v

                        # If no static args configured, extract from previous node's output
                        if not resolved_args and prev_output:
                            import inspect, json as _json
                            # 1. Agent output is JSON → parse and match keys to tool params
                            try:
                                parsed = _json.loads(prev_output)
                                if isinstance(parsed, dict):
                                    sig = inspect.signature(tool._execute)
                                    for pname in sig.parameters:
                                        if pname != "self" and pname in parsed:
                                            resolved_args[pname] = parsed[pname]
                            except (_json.JSONDecodeError, Exception):
                                pass

                            # 2. Fallback: pass raw output as first required param
                            if not resolved_args:
                                try:
                                    sig = inspect.signature(tool._execute)
                                    for pname, param in sig.parameters.items():
                                        if pname == "self":
                                            continue
                                        if param.default == inspect.Parameter.empty:
                                            resolved_args[pname] = prev_output
                                            break
                                except Exception:
                                    pass

                        result = tool.execute(**resolved_args)
                        state["intermediate_results"][tn] = result
                        state["output"] = str(result.get("result", result.get("error", "")))
                    else:
                        state["output"] = f"Tool '{tn}' not found"
                        state["error"] = f"Tool '{tn}' not found"
                    return state
                return tool_fn
            builder.graph.add_node(nid, _wrap_node_fn(_make_tool_fn(tool_name, tool_args), nid))
            builder._nodes_added.add(nid)

        elif ntype == "approval":
            prompt = ndata.get("approvalPrompt", "Approval required")
            auto_approve = ndata.get("autoApprove", False)
            def _make_approval_fn(p, node_id, auto):
                def approval_fn(state):
                    if auto:
                        # Auto-approve: skip HITL popup — preserve previous output
                        return state
                    state["hitl_pending"] = True
                    state["hitl_request"] = {
                        "type": "approval",
                        "prompt": p,
                        "node_id": node_id,
                        "context": {"current_output": str(state.get("output", ""))[:500]},
                    }
                    return state
                return approval_fn
            builder.graph.add_node(nid, _wrap_node_fn(_make_approval_fn(prompt, nid, auto_approve), nid))
            builder._nodes_added.add(nid)

    # Collect set of valid graph node IDs (registered in builder + start/end)
    from langgraph.graph import START, END
    registered_nodes = set(builder._nodes_added)
    start_ids = set()
    end_ids = set()
    for nid, node in nodes.items():
        ndata = node.get("data", {})
        ntype = ndata.get("type", node.get("type", ""))
        if ntype == "start":
            start_ids.add(nid)
        elif ntype == "end":
            end_ids.add(nid)

    # Add edges — only between nodes that exist in the compiled graph
    for edge in edges:
        src = edge["source"]
        tgt = edge["target"]
        src_data = nodes.get(src, {}).get("data", {})
        tgt_data = nodes.get(tgt, {}).get("data", {})
        src_type = src_data.get("type", nodes.get(src, {}).get("type", ""))
        tgt_type = tgt_data.get("type", nodes.get(tgt, {}).get("type", ""))

        actual_src = START if src_type == "start" else src
        actual_tgt = END if tgt_type == "end" else tgt

        # Skip edges to/from nodes not in the graph
        src_valid = src in start_ids or src in registered_nodes
        tgt_valid = tgt in end_ids or tgt in registered_nodes
        if not src_valid or not tgt_valid:
            print(f"[workflow] Skipping edge {src}->{tgt}: node not in graph")
            continue

        if src_type == "condition":
            # Handle condition routing — skip, handled separately below
            continue

        try:
            builder.graph.add_edge(actual_src, actual_tgt)
        except Exception as e:
            print(f"[workflow] Edge error {src}->{tgt}: {e}")

    # Handle condition nodes with conditional edges
    for nid, node in nodes.items():
        ndata = node.get("data", {})
        ntype = ndata.get("type", node.get("type", ""))
        if ntype != "condition":
            continue

        expression = ndata.get("expression", "has_error")
        # Find outgoing edges from this condition (true/false handles)
        true_target = None
        false_target = None
        for edge in edges:
            if edge["source"] == nid:
                handle = edge.get("sourceHandle", "")
                tgt = edge["target"]
                tgt_data = nodes.get(tgt, {}).get("data", {})
                actual_tgt = END if tgt_data.get("type") == "end" else tgt
                if handle == "true":
                    true_target = actual_tgt
                elif handle == "false":
                    false_target = actual_tgt
                else:
                    # Default: first edge = true, second = false
                    if true_target is None:
                        true_target = actual_tgt
                    else:
                        false_target = actual_tgt

        if true_target and false_target:
            def _make_router(expr):
                def router(state):
                    if expr == "has_error":
                        return "true" if state.get("error") else "false"
                    elif expr.startswith("output_contains:"):
                        kw = expr.split(":", 1)[1].strip()
                        return "true" if kw.lower() in str(state.get("output", "")).lower() else "false"
                    else:
                        try:
                            result = eval(expr, {"__builtins__": {}}, {"state": state})
                            return "true" if result else "false"
                        except Exception:
                            return "false"
                return router

            # Add condition as passthrough node
            def _passthrough(state):
                return state
            if nid not in builder._nodes_added:
                builder.graph.add_node(nid, _passthrough)
                builder._nodes_added.add(nid)

            builder.graph.add_conditional_edges(nid, _make_router(expression), {"true": true_target, "false": false_target})

    # Debug: emit compilation complete
    compile_duration = _time.time() - execution_start
    yield {
        "type": "debug", "phase": "compile", "event": "compile_done",
        "data": {
            "registered_nodes": list(builder._nodes_added),
            "compile_duration_ms": round(compile_duration * 1000),
        },
    }

    # Compile and execute
    try:
        compiled = builder.build()
    except Exception as e:
        fail_run(run_id, f"Compilation failed: {e}")
        yield {"type": "error", "message": f"Compilation failed: {e}"}
        return

    # Stream execution with pre-node events
    import threading

    node_order = []  # Track execution order

    def _run_graph():
        try:
            for step in compiled.stream({"input": input_text, "output": "", "intermediate_results": {}, "error": None}):
                for node_name, node_state in step.items():
                    event_queue.put({
                        "type": "_node_done",
                        "node_id": node_name,
                        "state": node_state,
                    })
            event_queue.put({"type": "_stream_done"})
        except Exception as e:
            event_queue.put({"type": "_stream_error", "error": str(e)})

    thread = threading.Thread(target=_run_graph, daemon=True)
    thread.start()

    try:
        while True:
            try:
                event = event_queue.get(timeout=300)
            except _queue_mod.Empty:
                fail_run(run_id, "Execution timed out (300s)")
                yield {"type": "error", "message": "Execution timed out"}
                return

            if event["type"] == "node_started":
                yield event

            elif event["type"] == "_debug_node":
                # Forward debug event to frontend
                yield {
                    "type": "debug",
                    "phase": "execute",
                    "event": event["event"],
                    "node_id": event["node_id"],
                    "label": event.get("label", ""),
                    "data": event["data"],
                }

            elif event["type"] == "_hitl_required":
                # HITL is handled inside wrapper (blocks graph thread).
                # Forward the event to frontend so HITLDialog pops up.
                yield {
                    "type": "hitl_required",
                    "node_id": event["node_id"],
                    "request": event["request"],
                    "run_id": run_id,
                }

            elif event["type"] == "_hitl_resolved":
                yield {
                    "type": "hitl_resolved",
                    "node_id": event["node_id"],
                    "response": event.get("response"),
                }

            elif event["type"] == "_hitl_rejected":
                yield {
                    "type": "hitl_rejected",
                    "node_id": event["node_id"],
                    "reason": event["reason"],
                }

            elif event["type"] == "_node_done":
                node_name = event["node_id"]
                node_state = event["state"]
                node_order.append(node_name)

                output = ""
                if isinstance(node_state, dict):
                    output = str(node_state.get("output", ""))[:500]
                update_node_state(run_id, node_name, "completed", output)
                yield {"type": "node_completed", "node_id": node_name, "output": output}

            elif event["type"] == "_stream_done":
                break

            elif event["type"] == "_stream_error":
                fail_run(run_id, event["error"])
                yield {"type": "error", "message": event["error"]}
                return

        thread.join(timeout=5)

        # Get final output
        final_output = ""
        run_data = get_run(run_id)
        if run_data:
            for ns in run_data.get("node_states", {}).values():
                if ns.get("output"):
                    final_output = ns["output"]

        total_duration = round((_time.time() - execution_start) * 1000)
        complete_run(run_id, final_output)

        # Debug: emit execution summary
        yield {
            "type": "debug", "phase": "summary", "event": "execution_summary",
            "data": {
                "run_id": run_id,
                "total_duration_ms": total_duration,
                "node_execution_order": [node_labels.get(n, n) for n in node_order],
                "nodes_executed": len(node_order),
                "final_output_length": len(final_output),
            },
        }

        yield {"type": "workflow_completed", "run_id": run_id, "output": final_output}

    except Exception as e:
        fail_run(run_id, str(e))
        yield {"type": "error", "message": str(e)}
