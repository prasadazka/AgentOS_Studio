"""AgentOS Studio - FastAPI Backend"""

import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

load_dotenv()

# Make the bundled agent_os package importable.
# Layout: <repo_root>/agent_os/  and  <repo_root>/backend/main.py
repo_root = Path(__file__).parent.parent
if (repo_root / "agent_os").exists():
    sys.path.insert(0, str(repo_root))
else:
    # Fallback for the legacy split layout (AAF/AgentOS sibling to AAF/AgentOS-Studio)
    legacy = repo_root.parent / "AgentOS"
    if legacy.exists():
        sys.path.insert(0, str(legacy))

from core import agent_manager, tool_manager
from core import project_manager
from core import workflow_manager
from core import gwdb_manager
from core.memory_pool import get_project_memory

# --- App ---

app = FastAPI(
    title="AgentOS Studio",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

_default_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
_extra = os.getenv("ALLOWED_ORIGINS", "").strip()
_allowed_origins = _default_origins + [o.strip() for o in _extra.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"^https://.*\.run\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Schemas ---

class AgentCreateRequest(BaseModel):
    name: str
    tools: list[str] = []
    model: str = "gpt-4o-mini"
    temperature: float = Field(default=0, ge=0, le=2)
    system_prompt: Optional[str] = None
    max_iterations: int = Field(default=15, ge=1, le=50)
    enable_memory: bool = True


class AgentUpdateRequest(BaseModel):
    model: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    system_prompt: Optional[str] = None
    tools: Optional[list[str]] = None
    max_iterations: Optional[int] = Field(default=None, ge=1, le=50)
    enable_memory: Optional[bool] = None


class AgentGenerateRequest(BaseModel):
    description: str
    name: Optional[str] = None


class ChatRequest(BaseModel):
    message: str


class ProjectCreateRequest(BaseModel):
    name: str
    description: str = ""
    agent_name: str


class ProjectChatRequest(BaseModel):
    message: str
    session_id: str


class WorkflowCreateRequest(BaseModel):
    name: str
    description: str = ""
    graph_json: Optional[dict] = None
    template_id: Optional[str] = None


class WorkflowUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    graph_json: Optional[dict] = None
    status: Optional[str] = None


class WorkflowExecuteRequest(BaseModel):
    input_text: str = ""


class HITLResponseRequest(BaseModel):
    action: str  # "approve" | "reject"
    value: Optional[str] = None
    comment: Optional[str] = None


# --- Health ---

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


# --- Agents ---

@app.get("/api/agents")
def list_agents():
    agents = agent_manager.list_agents()
    return {"agents": agents, "total": len(agents)}


@app.get("/api/agents/{name}")
def get_agent(name: str):
    agent = agent_manager.get_agent(name)
    if agent is None:
        raise HTTPException(404, f"Agent '{name}' not found")
    return agent


@app.post("/api/agents", status_code=201)
def create_agent(req: AgentCreateRequest):
    config = {
        "name": req.name,
        "tools": req.tools,
        "model": req.model,
        "temperature": req.temperature,
        "system_prompt": req.system_prompt or f"You are {req.name}, an AI assistant.",
        "max_iterations": req.max_iterations,
        "enable_memory": req.enable_memory,
    }
    result = agent_manager.create_agent(config)
    return result


@app.put("/api/agents/{name}")
def update_agent(name: str, req: AgentUpdateRequest):
    agent = agent_manager.get_agent(name)
    if agent is None:
        raise HTTPException(404, f"Agent '{name}' not found")
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No fields to update")
    try:
        result = agent_manager.update_agent(name, updates)
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))


# --- Smart Agent Generation ---

@app.post("/api/agents/generate")
def generate_agent(req: AgentGenerateRequest):
    """Generate agent config from description using AI.

    Uses AgentOS prompt_generator to create a smart system prompt,
    pick temperature, max_iterations, and suggest tools.
    """
    from agent_os.cli.core.prompt_generator import generate_system_prompt_and_config
    from agent_os.cli.core.config_generator import ConfigGenerator
    from agent_os.tools.global_registry import get_global_registry

    registry = get_global_registry()
    all_tool_names = registry.list_all()

    # Step 1: Use LLM to suggest tools based on description
    suggested_tools = _suggest_tools(req.description, all_tool_names)

    # Step 2: Generate system prompt, temperature, max_iterations via LLM
    try:
        system_prompt, temperature, max_iterations = generate_system_prompt_and_config(
            description=req.description,
            tools=suggested_tools,
        )
    except Exception as e:
        raise HTTPException(500, f"Prompt generation failed: {e}")

    # Step 3: Auto-generate name if not provided
    agent_name = req.name or _generate_name(req.description)

    # Step 4: Build and save config
    config = {
        "name": agent_name,
        "tools": suggested_tools,
        "model": "gpt-4o-mini",
        "temperature": temperature,
        "system_prompt": system_prompt or f"You are {agent_name}, an AI assistant.",
        "max_iterations": max_iterations,
        "enable_memory": True,
    }

    result = agent_manager.create_agent(config)
    return result


def _suggest_tools(description: str, all_tools: list[str]) -> list[str]:
    """Use LLM to pick the best tools for the agent description."""
    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        prompt = f"""Given this agent description, select the most relevant tools from the list.
Return ONLY a JSON array of tool name strings. Pick 3-8 tools max.

Agent Description: {description}

Available Tools:
{chr(10).join(f"- {t}" for t in sorted(all_tools))}

Return JSON array only, e.g.: ["tool1", "tool2"]"""

        response = llm.invoke(prompt)
        import json as _json
        # Parse the JSON array from response
        text = response.content.strip()
        # Handle markdown code blocks
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        tools = _json.loads(text)
        # Validate tools exist
        return [t for t in tools if t in all_tools]
    except Exception:
        return []


def _generate_name(description: str) -> str:
    """Generate a clean agent name from description."""
    import re
    # Take first few meaningful words
    words = re.findall(r"[A-Za-z]+", description)
    if not words:
        return "CustomAgent"
    # Capitalize first 2-3 words
    name_words = [w.capitalize() for w in words[:3] if len(w) > 2]
    name = "".join(name_words) or "CustomAgent"
    # Append "Agent" if not already there
    if not name.lower().endswith("agent"):
        name += "Agent"
    return name


@app.delete("/api/agents/{name}")
def delete_agent(name: str):
    # Check if default
    agent = agent_manager.get_agent(name)
    if agent and agent.get("is_default"):
        raise HTTPException(403, "Cannot delete default agents")
    if not agent_manager.delete_agent(name):
        raise HTTPException(404, f"Agent '{name}' not found")
    return {"deleted": True}


# --- Chat (SSE Streaming) ---

@app.post("/api/agents/{name}/chat")
def chat_stream(name: str, req: ChatRequest):
    # Verify agent exists
    agent_config = agent_manager.get_agent(name)
    if agent_config is None:
        raise HTTPException(404, f"Agent '{name}' not found")

    def event_stream():
        agent = None
        try:
            agent = agent_manager.instantiate_agent(name)

            # Inject uploaded file paths into the message context
            upload_dir = _agent_upload_dir(name)
            uploaded_files = [f for f in upload_dir.iterdir() if f.is_file()] if upload_dir.exists() else []
            enriched_message = req.message
            if uploaded_files:
                file_listing = "\n".join(
                    f"- {f.name} → {f} ({f.suffix.lstrip('.') or 'unknown'}, {f.stat().st_size} bytes)"
                    for f in sorted(uploaded_files)
                )
                enriched_message = (
                    f"AVAILABLE FILES (use these EXACT file paths when calling tools):\n"
                    f"{file_listing}\n\n"
                    f"USER MESSAGE: {req.message}"
                )

            # Try streaming first (stream_mode="values" yields full state per step)
            streamed = False
            try:
                seen_msg_count = 0
                last_ai_content = ""

                for chunk in agent.stream(enriched_message):
                    # Handle error chunks from BaseAgent
                    if isinstance(chunk, dict) and "error" in chunk and "messages" not in chunk:
                        yield f"data: {json.dumps({'type': 'error', 'message': chunk['error']})}\n\n"
                        streamed = True
                        continue

                    messages = chunk.get("messages", [])
                    if not messages:
                        continue

                    # Process only NEW messages (stream_mode="values" sends full history)
                    new_messages = messages[seen_msg_count:]
                    seen_msg_count = len(messages)

                    for msg in new_messages:
                        msg_type = getattr(msg, "type", "")

                        # Skip human messages (user's own input)
                        if msg_type == "human":
                            continue

                        # AI message with tool calls
                        if msg_type == "ai" and hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                event = {
                                    "type": "tool_call",
                                    "name": tc.get("name", "unknown"),
                                    "args": tc.get("args", {}),
                                }
                                yield f"data: {json.dumps(event)}\n\n"
                                streamed = True
                            # Also send partial content if present
                            if msg.content and msg.content != last_ai_content:
                                last_ai_content = msg.content
                                yield f"data: {json.dumps({'type': 'token', 'content': msg.content})}\n\n"
                                streamed = True

                        # Tool result message
                        elif msg_type == "tool":
                            tool_name = getattr(msg, "name", "")
                            tool_content = str(msg.content)
                            event = {
                                "type": "tool_result",
                                "name": tool_name,
                                "content": tool_content[:2000],
                            }
                            yield f"data: {json.dumps(event)}\n\n"
                            streamed = True

                            # Detect HITL approval request
                            if tool_name == "gwdb_request_approval":
                                token_match = re.search(r'`((?:push|gwdb)-[^`]+)`', tool_content)
                                rows_match = re.search(r'\(([0-9,]+) rows\)', tool_content)
                                tables_match = re.search(r'Tables to create: (\d+)', tool_content)
                                if token_match:
                                    approval_event = {
                                        "type": "approval_required",
                                        "token": token_match.group(1),
                                        "row_count": rows_match.group(1) if rows_match else "?",
                                        "table_count": tables_match.group(1) if tables_match else "?",
                                    }
                                    yield f"data: {json.dumps(approval_event)}\n\n"

                        # AI content (final or intermediate)
                        elif msg_type == "ai" and msg.content:
                            if msg.content != last_ai_content:
                                last_ai_content = msg.content
                                yield f"data: {json.dumps({'type': 'token', 'content': msg.content})}\n\n"
                                streamed = True

            except Exception as stream_err:
                # If streaming failed and we got nothing, fall back to run()
                if not streamed:
                    print(f"[chat] stream() failed for '{name}': {stream_err}, falling back to run()")
                    try:
                        result = agent.run(enriched_message)
                        yield f"data: {json.dumps({'type': 'token', 'content': result})}\n\n"
                        streamed = True
                    except Exception as run_err:
                        yield f"data: {json.dumps({'type': 'error', 'message': str(run_err)})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'error', 'message': str(stream_err)})}\n\n"

            # If streaming yielded nothing (no AI response), fall back to run()
            if not streamed:
                print(f"[chat] stream() yielded no AI content for '{name}', falling back to run()")
                try:
                    result = agent.run(enriched_message)
                    yield f"data: {json.dumps({'type': 'token', 'content': result})}\n\n"
                except Exception as run_err:
                    yield f"data: {json.dumps({'type': 'error', 'message': str(run_err)})}\n\n"

            # Send metrics if available
            try:
                info = agent.get_info()
                cost_info = info.get("cost_tracking", {})
                if cost_info:
                    yield f"data: {json.dumps({'type': 'metrics', 'data': cost_info})}\n\n"
            except Exception:
                pass

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            print(f"[chat] Fatal error for '{name}': {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        finally:
            if agent:
                try:
                    agent.cleanup()
                except Exception:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- Agent Files (upload files for agent chat without needing a project) ---

AGENT_UPLOADS_DIR = Path((os.getenv("AGENTOS_AGENT_UPLOADS_DIR") or "").strip() or os.path.expanduser("~/.agent_os/agent_uploads"))


def _agent_upload_dir(agent_name: str) -> Path:
    d = AGENT_UPLOADS_DIR / agent_name
    d.mkdir(parents=True, exist_ok=True)
    return d


@app.post("/api/agents/{name}/files", status_code=201)
async def upload_agent_file(name: str, file: UploadFile = File(...)):
    """Upload a file for use in agent chat (no project required)."""
    if not agent_manager.get_agent(name):
        raise HTTPException(404, f"Agent '{name}' not found")

    dest_dir = _agent_upload_dir(name)
    filename = file.filename or "upload"
    dest = dest_dir / filename

    # Stream to disk
    with open(dest, "wb") as f:
        while chunk := await file.read(1024 * 64):
            f.write(chunk)

    return {
        "filename": filename,
        "filepath": str(dest),
        "file_size": dest.stat().st_size,
    }


@app.get("/api/agents/{name}/files")
def list_agent_files(name: str):
    """List files uploaded for agent chat."""
    dest_dir = _agent_upload_dir(name)
    files = []
    if dest_dir.exists():
        for f in sorted(dest_dir.iterdir()):
            if f.is_file():
                files.append({
                    "filename": f.name,
                    "filepath": str(f),
                    "file_size": f.stat().st_size,
                    "file_type": f.suffix.lstrip(".") or "unknown",
                })
    return {"files": files, "total": len(files)}


@app.delete("/api/agents/{name}/files/{filename:path}")
def delete_agent_file(name: str, filename: str):
    """Delete a file uploaded for agent chat."""
    dest_dir = _agent_upload_dir(name)
    target = dest_dir / filename
    if not target.exists() or not str(target.resolve()).startswith(str(dest_dir.resolve())):
        raise HTTPException(404, "File not found")
    target.unlink()
    return {"deleted": True}


@app.delete("/api/agents/{name}/files")
def clear_agent_files(name: str):
    """Clear all uploaded files for this agent."""
    dest_dir = _agent_upload_dir(name)
    count = 0
    if dest_dir.exists():
        for f in dest_dir.iterdir():
            if f.is_file():
                f.unlink()
                count += 1
    return {"cleared": count}


@app.get("/api/agents/{name}/files/download/{filename:path}")
def download_agent_file(name: str, filename: str):
    """Download an uploaded agent file."""
    dest_dir = _agent_upload_dir(name)
    target = dest_dir / filename
    if not target.exists() or not str(target.resolve()).startswith(str(dest_dir.resolve())):
        raise HTTPException(404, "File not found")
    return FileResponse(path=str(target), filename=target.name, media_type="application/octet-stream")


# --- Projects ---

@app.post("/api/projects", status_code=201)
def create_project(req: ProjectCreateRequest):
    # Verify agent exists
    if not agent_manager.get_agent(req.agent_name):
        raise HTTPException(404, f"Agent '{req.agent_name}' not found")
    return project_manager.create_project(req.name, req.description, req.agent_name)


@app.get("/api/projects")
def list_projects():
    projects = project_manager.list_projects()
    return {"projects": projects, "total": len(projects)}


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    project = project_manager.get_project(pid)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    if not project_manager.delete_project(pid):
        raise HTTPException(404, "Project not found")
    return {"deleted": True}


# --- Project Files ---

@app.post("/api/projects/{pid}/files", status_code=201)
async def upload_file(pid: str, file: UploadFile = File(...)):
    if not project_manager.get_project(pid):
        raise HTTPException(404, "Project not found")
    # Stream directly to disk — no full in-memory load
    result = await project_manager.add_file_streamed(pid, file.filename or "upload", file)
    return result


@app.get("/api/projects/{pid}/files")
def list_files(pid: str):
    files = project_manager.list_files(pid)
    return {"files": files, "total": len(files)}


@app.delete("/api/projects/{pid}/files/{fid}")
def delete_file(pid: str, fid: str):
    if not project_manager.delete_file(fid):
        raise HTTPException(404, "File not found")
    return {"deleted": True}


@app.delete("/api/projects/{pid}/files/by-name/{filename:path}")
def delete_file_by_name(pid: str, filename: str):
    """Delete a file by filename (works for both uploaded and generated files)."""
    project = project_manager.get_project(pid)
    if not project:
        raise HTTPException(404, "Project not found")
    project_dir = project_manager.PROJECTS_DIR / pid / "files"
    target = project_dir / filename
    if not target.exists() or not str(target.resolve()).startswith(str(project_dir.resolve())):
        raise HTTPException(404, "File not found")
    target.unlink()
    # Also remove DB record if it exists
    from db.database import get_db
    db = get_db()
    db.execute("DELETE FROM project_files WHERE project_id = ? AND filename = ?", (pid, filename))
    db.commit()
    return {"deleted": True}


@app.get("/api/projects/{pid}/files/all")
def list_all_files(pid: str):
    """List all files on disk (uploaded + agent-generated)."""
    if not project_manager.get_project(pid):
        raise HTTPException(404, "Project not found")
    files = project_manager.list_all_disk_files(pid)
    return {"files": files, "total": len(files)}


@app.get("/api/projects/{pid}/files/download/{filename:path}")
def download_file(pid: str, filename: str):
    """Download a project file by filename."""
    if not project_manager.get_project(pid):
        raise HTTPException(404, "Project not found")
    file_path = project_manager.get_file_path(pid, filename)
    if not file_path:
        raise HTTPException(404, "File not found")
    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/octet-stream",
    )


# --- Project Sessions ---

@app.post("/api/projects/{pid}/sessions", status_code=201)
def create_session(pid: str):
    if not project_manager.get_project(pid):
        raise HTTPException(404, "Project not found")
    return project_manager.create_session(pid)


@app.get("/api/projects/{pid}/sessions")
def list_sessions(pid: str):
    sessions = project_manager.list_sessions(pid)
    return {"sessions": sessions, "total": len(sessions)}


@app.patch("/api/projects/{pid}/sessions/{sid}")
def rename_session(pid: str, sid: str, req: dict):
    title = req.get("title", "").strip()
    if not title:
        raise HTTPException(400, "Title is required")
    result = project_manager.rename_session(sid, title)
    if not result:
        raise HTTPException(404, "Session not found")
    return result


@app.delete("/api/projects/{pid}/sessions/{sid}")
def delete_session(pid: str, sid: str):
    if not project_manager.delete_session(sid):
        raise HTTPException(404, "Session not found")
    return {"deleted": True}


@app.delete("/api/projects/{pid}/sessions")
def delete_all_sessions(pid: str):
    """Delete all chat sessions for a project."""
    if not project_manager.get_project(pid):
        raise HTTPException(404, "Project not found")
    count = project_manager.delete_all_sessions(pid)
    return {"deleted": count}


@app.get("/api/projects/{pid}/sessions/{sid}/messages")
def get_messages(pid: str, sid: str):
    messages = project_manager.get_messages(sid)
    return {"messages": messages, "total": len(messages)}


# --- Project Chat (SSE Streaming with Memory) ---

@app.post("/api/projects/{pid}/chat")
def project_chat_stream(pid: str, req: ProjectChatRequest):
    project = project_manager.get_project(pid)
    if not project:
        raise HTTPException(404, "Project not found")

    agent_name = project["agent_name"]
    agent_config = agent_manager.get_agent(agent_name)
    if not agent_config:
        raise HTTPException(404, f"Agent '{agent_name}' not found")

    def event_stream():
        agent = None
        try:
            # Get project memory and instantiate agent with it
            memory = get_project_memory(pid)
            pf_dir = str(project_manager.PROJECTS_DIR / pid / "files")
            agent = agent_manager.instantiate_agent_with_memory(agent_name, memory, project_files_dir=pf_dir)

            # Build memory-augmented messages
            from langchain_core.messages import SystemMessage, HumanMessage

            # ------------------------------------------------------------------
            # Context budget: keep total context under ~80K tokens (~320K chars)
            # to stay well within model limits and avoid 429 errors.
            # ------------------------------------------------------------------
            MAX_CONTEXT_CHARS = 300_000  # ~75K tokens
            MAX_HISTORY_TURNS = 10       # last N user+assistant pairs
            MAX_MSG_CHARS = 3_000        # truncate each historical message
            MAX_PROJECT_FILES = 50       # most recent files listed
            MAX_SEMANTIC_RESULTS = 5     # semantic search results
            MAX_SEMANTIC_CHARS = 500     # chars per semantic result

            # Get memory context
            context_parts = []

            # Tell the agent where to save/export files so the UI can find them
            project_files_dir = project_manager.PROJECTS_DIR / pid / "files"
            project_files_dir.mkdir(parents=True, exist_ok=True)
            context_parts.append(
                f"OUTPUT DIRECTORY (ALWAYS save/export files here so they appear in the UI):\n{project_files_dir}"
            )

            # Include file paths (uploaded + agent-generated) so agent tools can find them
            # Limit to most recent files to avoid token bloat
            all_disk_files = project_manager.list_all_disk_files(pid)
            if all_disk_files:
                # Take the most recent files up to the limit
                limited_files = all_disk_files[-MAX_PROJECT_FILES:]
                file_listing = "\n".join(
                    f"- {f['filename']} → {f['filepath']} ({f['file_type']}, {f['file_size']} bytes, source: {f['source']})"
                    for f in limited_files
                )
                if len(all_disk_files) > MAX_PROJECT_FILES:
                    file_listing += f"\n... and {len(all_disk_files) - MAX_PROJECT_FILES} older files (use file tools to list all)"
                context_parts.append(
                    f"PROJECT FILES — USE THESE EXACT PATHS (do NOT call directory_list, do NOT guess paths):\n{file_listing}"
                )

            # Note: conversation history is injected as actual HumanMessage/AIMessage
            # objects below, so we don't duplicate it as text in the system prompt.

            semantic_results = memory.search_semantic(req.message, limit=MAX_SEMANTIC_RESULTS)
            if semantic_results:
                knowledge = "\n\n".join(
                    f"[{r.metadata.get('filename', 'unknown')}]: {r.content[:MAX_SEMANTIC_CHARS]}"
                    for r in semantic_results
                )
                context_parts.append(f"RELEVANT KNOWLEDGE FROM UPLOADED FILES:\n{knowledge}")

            system_prompt = agent_config.get("system_prompt", f"You are {agent_name}.")
            system_prompt += """\n
CRITICAL RULES:
1. Do NOT create, save, or write files to disk unless the user EXPLICITLY asks to save, export, or download. Just analyze and respond in the chat.
2. Do NOT use the dataframe_visualize tool. It is disabled in this UI. For ALL visualizations (charts, plots, graphs), you MUST output chart data as a fenced code block with language "chart" containing valid JSON. This is the ONLY way charts render in this interface:

```chart
{"type":"bar","title":"Treatment Cost Distribution","xLabel":"Cost Range ($)","yLabel":"Number of Patients","data":[{"name":"$0-$500","count":4},{"name":"$500-$1000","count":10},{"name":"$1000-$2000","count":15},{"name":"$2000-$5000","count":19},{"name":"$5000+","count":25}]}
```

Supported chart types: bar, line, area, pie, scatter
- For bar/line/area/scatter: data items need "name" (x-axis) and one or more numeric keys for y-axis values
- For pie: data items need "name" and "value"
- For multi-series: use multiple numeric keys like {"name":"Jan","sales":100,"revenue":200}
- Always include "title". Include "xLabel" and "yLabel" when appropriate.

ABSOLUTELY MANDATORY — CHART DATA RULES:
- BEFORE creating any chart, you MUST first use tools (dataframe_describe, csv_process, dataframe_filter_rows, dataframe_group_aggregate, etc.) to read and compute the ACTUAL data from the file. NEVER guess or fabricate chart data.
- The "name" field and numeric values in chart data MUST come from REAL tool output. Copy exact values from tool results.
- NEVER use generic placeholders like "Cost 1", "Cost 2", "Category A", "Group 1", "Bucket 1" etc. This is STRICTLY FORBIDDEN.
- For scatter plots: each data point must have real numeric values from the dataset, e.g. {"name":"Patient 1","height":165.2,"weight":72.3}
- For distributions: use dataframe_group_aggregate or similar to compute bins first, then use the actual computed counts.
- For categorical data: use the actual category names from the dataset (e.g. "Aspirin", "Ibuprofen", "Male", "Female").
- If data has too many points (>20 for scatter, >15 for bar): sample or bin the data, but always use REAL values from tool output.

RESPONSE FORMAT: Always respond using rich Markdown formatting. Use **bold** for key values and important terms. Use tables for structured/tabular data. Use headings (##, ###) to organize sections. Use bullet points and numbered lists. Use `code` for file names, column names, and technical terms. Use > blockquotes for summaries or highlights. Make your responses visually clear and well-structured."""
            if context_parts:
                system_prompt += "\n\n" + "\n\n".join(context_parts)

            # Build message list: system prompt + prior conversation turns + current message
            from langchain_core.messages import AIMessage
            messages = [SystemMessage(content=system_prompt)]

            # Inject prior messages as structured HumanMessage/AIMessage pairs.
            # Only include the last N turns to prevent token explosion.
            # Long assistant responses (tool outputs, tables) are truncated.
            prior_db_msgs = project_manager.get_messages(req.session_id)

            # Keep only the most recent turns (each turn = 1 user + 1 assistant)
            if len(prior_db_msgs) > MAX_HISTORY_TURNS * 2:
                prior_db_msgs = prior_db_msgs[-(MAX_HISTORY_TURNS * 2):]

            for pm in prior_db_msgs:
                content = pm["content"] or ""
                # Truncate long messages (especially assistant responses with tool output)
                if len(content) > MAX_MSG_CHARS:
                    content = content[:MAX_MSG_CHARS] + f"\n... [truncated, {len(pm['content']):,} chars total]"
                if pm["role"] == "user":
                    messages.append(HumanMessage(content=content))
                elif pm["role"] == "assistant":
                    messages.append(AIMessage(content=content))

            messages.append(HumanMessage(content=req.message))

            # Safety check: estimate total context size and warn if large
            total_chars = sum(len(getattr(m, "content", "")) for m in messages)
            estimated_tokens = total_chars // 4  # rough ~4 chars/token
            print(f"[project_chat] session={req.session_id} | prior_msgs={len(prior_db_msgs)} | context_parts={len(context_parts)} | system_prompt_len={len(system_prompt)} | est_tokens={estimated_tokens:,}")

            # If still over budget after truncation, aggressively trim history
            if total_chars > MAX_CONTEXT_CHARS:
                print(f"[project_chat] WARNING: context {total_chars:,} chars > budget {MAX_CONTEXT_CHARS:,}. Trimming history.")
                # Remove oldest history messages (keep system + last user msg)
                while total_chars > MAX_CONTEXT_CHARS and len(messages) > 2:
                    removed = messages.pop(1)  # remove oldest after system message
                    total_chars -= len(getattr(removed, "content", ""))
                print(f"[project_chat] After trim: {total_chars:,} chars, {len(messages)} messages")

            # Save user message to DB
            project_manager.add_message(req.session_id, "user", req.message)
            memory.add_message("user", req.message)

            # Auto-title: if session is still "New Chat", derive title from first message
            existing_msgs = project_manager.get_messages(req.session_id)
            if len(existing_msgs) <= 1:  # only the message we just added
                auto_title = req.message.strip()[:60]
                if len(req.message.strip()) > 60:
                    auto_title += "..."
                project_manager.rename_session(req.session_id, auto_title)
                yield f"data: {json.dumps({'type': 'session_renamed', 'session_id': req.session_id, 'title': auto_title})}\n\n"

            # Stream via agent's internal graph
            streamed = False
            full_content = ""
            tool_calls_log = []
            try:
                # Skip all input messages (system + prior turns + current user msg)
                # so we only process NEW messages generated by the agent
                seen_msg_count = len(messages)
                last_ai_content = ""

                for chunk in agent.agent.stream({"messages": messages}, stream_mode="values"):
                    msgs = chunk.get("messages", [])
                    if not msgs:
                        continue

                    new_msgs = msgs[seen_msg_count:]
                    seen_msg_count = len(msgs)

                    for msg in new_msgs:
                        msg_type = getattr(msg, "type", "")

                        if msg_type in ("human", "system"):
                            continue

                        if msg_type == "ai" and hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                event = {
                                    "type": "tool_call",
                                    "name": tc.get("name", "unknown"),
                                    "args": tc.get("args", {}),
                                }
                                tool_calls_log.append(event)
                                yield f"data: {json.dumps(event)}\n\n"
                                streamed = True
                            raw_content = msg.content
                            # Gemini returns content as list of parts — flatten to string
                            if isinstance(raw_content, list):
                                raw_content = "\n".join(
                                    p.get("text", str(p)) if isinstance(p, dict) else str(p)
                                    for p in raw_content
                                )
                            if raw_content and raw_content != last_ai_content:
                                last_ai_content = raw_content
                                full_content = raw_content
                                yield f"data: {json.dumps({'type': 'token', 'content': raw_content})}\n\n"
                                streamed = True

                        elif msg_type == "tool":
                            tool_name = getattr(msg, "name", "")
                            tool_content = str(msg.content)
                            event = {
                                "type": "tool_result",
                                "name": tool_name,
                                "content": tool_content[:2000],
                            }
                            yield f"data: {json.dumps(event)}\n\n"
                            streamed = True

                            # Detect HITL approval request
                            if tool_name == "gwdb_request_approval":
                                token_match = re.search(r'`((?:push|gwdb)-[^`]+)`', tool_content)
                                rows_match = re.search(r'\(([0-9,]+) rows\)', tool_content)
                                tables_match = re.search(r'Tables to create: (\d+)', tool_content)
                                if token_match:
                                    approval_event = {
                                        "type": "approval_required",
                                        "token": token_match.group(1),
                                        "row_count": rows_match.group(1) if rows_match else "?",
                                        "table_count": tables_match.group(1) if tables_match else "?",
                                    }
                                    yield f"data: {json.dumps(approval_event)}\n\n"

                        elif msg_type == "ai" and msg.content:
                            raw_ai = msg.content
                            # Gemini returns content as list of parts — flatten to string
                            if isinstance(raw_ai, list):
                                raw_ai = "\n".join(
                                    p.get("text", str(p)) if isinstance(p, dict) else str(p)
                                    for p in raw_ai
                                )
                            if raw_ai != last_ai_content:
                                last_ai_content = raw_ai
                                full_content = raw_ai
                                yield f"data: {json.dumps({'type': 'token', 'content': raw_ai})}\n\n"
                                streamed = True

            except Exception as stream_err:
                if not streamed:
                    print(f"[project_chat] stream() failed: {stream_err}, falling back to run()")
                    try:
                        result = agent.run(req.message)
                        full_content = result
                        yield f"data: {json.dumps({'type': 'token', 'content': result})}\n\n"
                        streamed = True
                    except Exception as run_err:
                        yield f"data: {json.dumps({'type': 'error', 'message': str(run_err)})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'error', 'message': str(stream_err)})}\n\n"

            if not streamed:
                try:
                    result = agent.run(req.message)
                    full_content = result
                    yield f"data: {json.dumps({'type': 'token', 'content': result})}\n\n"
                except Exception as run_err:
                    yield f"data: {json.dumps({'type': 'error', 'message': str(run_err)})}\n\n"

            # Save assistant response to DB and memory
            if full_content:
                project_manager.add_message(
                    req.session_id, "assistant", full_content,
                    tool_calls=tool_calls_log if tool_calls_log else None,
                )
                memory.add_message("assistant", full_content)

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            print(f"[project_chat] Fatal error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        finally:
            if agent:
                try:
                    agent.cleanup()
                except Exception:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- Workflows ---

@app.get("/api/workflows")
def list_workflows():
    workflows = workflow_manager.list_workflows()
    return {"workflows": workflows, "total": len(workflows)}


# --- Geo API (Map View) ---
@app.get("/api/geo/files")
def api_list_geo_files():
    """List available GeoJSON output files from completed geo workflows."""
    from core.geo_api import list_geo_files
    files = list_geo_files()
    return {"files": files, "total": len(files)}


@app.get("/api/geo/serve")
def api_serve_geo_file(path: str = Query(..., description="Absolute path to GeoJSON file")):
    """Serve a GeoJSON file by absolute path (with security validation)."""
    from core.geo_api import serve_geo_file
    try:
        data = serve_geo_file(path)
        return data
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError:
        raise HTTPException(404, "File not found")
    except Exception as e:
        raise HTTPException(500, f"Error reading file: {e}")


GEO_UPLOADS_DIR = Path(os.path.expanduser("~/.agent_os/geo_uploads"))


@app.post("/api/geo/upload", status_code=201)
async def upload_geo_file(file: UploadFile = File(...)):
    """Upload a GeoJSON/JSON file directly for map viewing."""
    import json as _json

    filename = file.filename or "upload.geojson"
    ext = Path(filename).suffix.lower()
    if ext not in {".geojson", ".json"}:
        raise HTTPException(400, "Only .geojson and .json files are supported")

    # Read the file content
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(400, "File exceeds 50 MB limit")

    # Validate it's valid JSON and GeoJSON
    try:
        data = _json.loads(content)
    except _json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON file")

    geo_type = data.get("type", "") if isinstance(data, dict) else ""
    valid_types = {
        "FeatureCollection", "Feature", "Point", "MultiPoint",
        "LineString", "MultiLineString", "Polygon", "MultiPolygon",
        "GeometryCollection",
    }
    if geo_type not in valid_types:
        raise HTTPException(400, f"Not valid GeoJSON (type='{geo_type}')")

    # Save to disk so it can be re-loaded later
    GEO_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    dest = GEO_UPLOADS_DIR / filename
    with open(dest, "wb") as f:
        f.write(content)

    return data


@app.get("/api/workflow-templates")
def list_workflow_templates():
    """List all available workflow templates."""
    from core.workflow_templates import list_templates
    templates = list_templates()
    return {"templates": templates, "total": len(templates)}


@app.post("/api/workflows", status_code=201)
def create_workflow(req: WorkflowCreateRequest):
    graph = req.graph_json
    desc = req.description
    if req.template_id:
        from core.workflow_templates import get_template
        tmpl = get_template(req.template_id)
        if not tmpl:
            raise HTTPException(404, f"Template '{req.template_id}' not found")
        graph = graph or tmpl["graph_json"]
        desc = desc or tmpl["description"]
    wf = workflow_manager.create_workflow(req.name, desc, graph)
    return wf


@app.get("/api/workflows/{wid}")
def get_workflow(wid: str):
    wf = workflow_manager.get_workflow(wid)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    return wf


@app.put("/api/workflows/{wid}")
def update_workflow(wid: str, req: WorkflowUpdateRequest):
    wf = workflow_manager.update_workflow(wid, req.name, req.description, req.graph_json, req.status)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    # Return validation warnings (non-blocking) if graph was updated
    if req.graph_json:
        validation = workflow_manager.validate_workflow(req.graph_json)
        wf["validation"] = validation
    return wf


@app.post("/api/workflows/{wid}/validate")
def validate_workflow(wid: str):
    wf = workflow_manager.get_workflow(wid)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    return workflow_manager.validate_workflow(wf["graph_json"])


@app.delete("/api/workflows/{wid}")
def delete_workflow(wid: str):
    ok = workflow_manager.delete_workflow(wid)
    if not ok:
        raise HTTPException(404, "Workflow not found")
    return {"deleted": True}


WORKFLOW_UPLOADS_DIR = Path(os.path.expanduser("~/.agent_os/workflow_uploads"))


@app.post("/api/workflows/{wid}/upload", status_code=201)
async def upload_workflow_file(wid: str, file: UploadFile = File(...)):
    """Upload a file for use in a workflow run. Returns the server-side file path."""
    wf = workflow_manager.get_workflow(wid)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    dest_dir = WORKFLOW_UPLOADS_DIR / wid
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = file.filename or "upload"
    dest = dest_dir / filename

    with open(dest, "wb") as f:
        while chunk := await file.read(1024 * 64):
            f.write(chunk)

    return {
        "filename": filename,
        "filepath": str(dest),
        "file_size": dest.stat().st_size,
    }


@app.post("/api/workflows/{wid}/execute")
def execute_workflow(wid: str, req: WorkflowExecuteRequest):
    wf = workflow_manager.get_workflow(wid)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    run = workflow_manager.create_run(wid, req.input_text)

    def stream():
        import traceback
        try:
            for event in workflow_manager.compile_and_execute(wf, req.input_text, run["id"]):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/workflows/{wid}/runs")
def list_workflow_runs(wid: str):
    runs = workflow_manager.list_runs(wid)
    return {"runs": runs, "total": len(runs)}


@app.get("/api/workflows/{wid}/runs/{rid}")
def get_workflow_run(wid: str, rid: str):
    run = workflow_manager.get_run(rid)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@app.post("/api/workflows/{wid}/runs/{rid}/hitl-respond")
def hitl_respond(wid: str, rid: str, req: HITLResponseRequest):
    ok = workflow_manager.submit_hitl_response(rid, req.action, req.value, req.comment)
    if not ok:
        raise HTTPException(400, "Run is not paused or not found")
    return {"submitted": True}


# --- Tools ---

@app.get("/api/tools")
def list_tools():
    tools = tool_manager.list_tools()
    return {"tools": tools, "total": len(tools)}


@app.get("/api/tools/categories")
def list_categories():
    categories = tool_manager.list_categories()
    return {"categories": categories}


@app.get("/api/tools/{tool_name}/schema")
def get_tool_schema(tool_name: str):
    schema = tool_manager.get_tool_schema(tool_name)
    if not schema:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    return schema


@app.get("/api/tools/search")
def search_tools(q: str = Query(..., min_length=1)):
    results = tool_manager.search_tools(q)
    return {"tools": results, "total": len(results)}


# --- GWDB Session ---

@app.get("/api/gwdb/tables")
def gwdb_list_tables():
    """List all DataFrames loaded in the GWDB session store."""
    tables = gwdb_manager.list_loaded_tables()
    return {"tables": tables, "total": len(tables)}


@app.get("/api/gwdb/tables/{table_name}")
def gwdb_get_table(table_name: str):
    """Get detailed info about a loaded GWDB table."""
    info = gwdb_manager.get_table_info(table_name)
    if info is None:
        raise HTTPException(404, f"Table '{table_name}' not loaded")
    return info


@app.delete("/api/gwdb/tables/{table_name}")
def gwdb_clear_table(table_name: str):
    """Remove a table from the GWDB session store."""
    if not gwdb_manager.clear_table(table_name):
        raise HTTPException(404, f"Table '{table_name}' not loaded")
    return {"cleared": True, "table": table_name}


@app.delete("/api/gwdb/tables")
def gwdb_clear_all():
    """Clear all tables from the GWDB session store."""
    count = gwdb_manager.clear_all_tables()
    return {"cleared": count}


@app.get("/api/gwdb/push-status")
def gwdb_push_status():
    """Get GWDB push approval tokens and push history."""
    return gwdb_manager.get_approval_status()


# --- Stats (for dashboard) ---

@app.get("/api/stats")
def get_stats():
    agents = agent_manager.list_agents()
    tool_count = tool_manager.get_tool_count()
    categories = tool_manager.list_categories()
    projects = project_manager.list_projects()
    workflows = workflow_manager.list_workflows()
    return {
        "total_agents": len(agents),
        "total_tools": tool_count,
        "total_categories": len(categories),
        "total_projects": len(projects),
        "total_workflows": len(workflows),
        "default_agents": sum(1 for a in agents if a.get("is_default")),
        "custom_agents": sum(1 for a in agents if not a.get("is_default")),
    }


if __name__ == "__main__":
    # Startup diagnostics
    print(f"[startup] Python: {sys.executable}")
    print(f"[startup] Version: {sys.version}")
    try:
        import geopandas as _gpd
        print(f"[startup] geopandas: {_gpd.__version__}")
    except ImportError as e:
        print(f"[startup] geopandas: NOT AVAILABLE ({e})")

    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
