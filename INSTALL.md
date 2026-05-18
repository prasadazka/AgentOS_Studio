# AgentOS-Studio — Installation Guide

Complete setup guide for installing AgentOS-Studio on a new system.

---

## ⚠️ IMPORTANT: Before You Transfer

Your current `.env` file contains **real API keys**. Before transferring:

1. **DO NOT** commit `.env` files to git or share them publicly
2. Either:
   - Transfer them through a secure channel (encrypted USB, password manager), OR
   - Set up fresh API keys on the new machine

The keys currently in [backend/.env](backend/.env):
- `OPENAI_API_KEY` (sk-proj-...)
- `GOOGLE_API_KEY` (AQ.Ab8...)

If exposed, **rotate these keys immediately** at the provider dashboards.

---

## Prerequisites

Install these on the new system first:

| Software | Version | Download |
|----------|---------|----------|
| **Python** | 3.11 or 3.12 | https://www.python.org/downloads/ |
| **Node.js** | 18 or higher | https://nodejs.org/ |
| **Git** | Latest | https://git-scm.com/ |

**Verify installations:**

```powershell
python --version    # Should show 3.11+ or 3.12+
node --version      # Should show v18+ or v20+
npm --version       # Should show 9+ or 10+
```

---

## Project Structure

The project has **two interdependent folders** that must be transferred together:

```
AAF/                              ← Parent folder (any name works)
├── AgentOS/                      ← Core framework (REQUIRED dependency)
│   ├── agent_os/
│   ├── pyproject.toml
│   └── .env                      ← LLM API keys for the framework
│
└── AgentOS-Studio/               ← The Studio (UI + API)
    ├── backend/
    │   ├── core/
    │   ├── db/
    │   ├── main.py
    │   ├── requirements.txt
    │   └── .env                  ← LLM API keys for the studio
    └── frontend/
        ├── src/
        ├── package.json
        └── .env.local            ← Backend API URL
```

> **Important:** `AgentOS-Studio/backend/main.py` uses a relative path to find the AgentOS core:
> `agent_os_path = Path(__file__).parent.parent.parent / "AgentOS"`
> Both folders must sit side-by-side under the same parent directory.

---

## Step 1: Transfer the Files

Copy the entire `AAF` folder (or whatever your parent folder is named) to the new system. Methods:

**Option A — Zip and copy:**
```powershell
# On old system (PowerShell)
Compress-Archive -Path "e:\AZKASHINE\AAF" -DestinationPath "AAF.zip"

# Copy AAF.zip to new system, then unzip there
Expand-Archive -Path "AAF.zip" -DestinationPath "C:\YourPath\"
```

**Option B — Git (recommended for ongoing work):**
```powershell
# Initialize git in the AAF folder, push to a private repo
# DO NOT push .env files — add to .gitignore first
```

**Files to EXCLUDE from transfer (regenerated on new system):**
- `node_modules/` (will be reinstalled by `npm install`)
- `__pycache__/` (auto-generated)
- `*.egg-info/` (auto-generated)
- `~/.agent_os/` (user data folder — copy separately if you want existing projects/agents)

---

## Step 2: Install AgentOS Core Framework

The Studio depends on the AgentOS framework. Install it first:

```powershell
cd C:\YourPath\AAF\AgentOS
pip install -e .
```

The `-e` flag installs it in **editable mode**, so changes to the source are picked up automatically.

**Optional extras** (install only what you need):

```powershell
# Geospatial features (R-tree indexing, GeoJSON)
pip install -e ".[geo]"

# All data tools (pandas, polars, duckdb, openpyxl, matplotlib)
pip install -e ".[data_all]"

# Vector databases (Qdrant, Weaviate, FAISS)
pip install -e ".[vector_all]"

# Everything
pip install -e ".[all]"
```

---

## Step 3: Set Up Backend

```powershell
cd C:\YourPath\AAF\AgentOS-Studio\backend

# Install Python dependencies
pip install -r requirements.txt

# Create .env file (if not transferred)
# Copy this template and fill in your API keys
```

**Create `backend/.env`:**

```env
OPENAI_API_KEY=sk-your-openai-key-here
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key-here
GOOGLE_API_KEY=your-google-key-here
AGENT_OS_CONFIG_DIR=~/.agent_os/configs/agents
```

**Get API keys from:**
- OpenAI: https://platform.openai.com/api-keys
- Anthropic: https://console.anthropic.com/settings/keys
- Google AI: https://aistudio.google.com/apikey

> You only need keys for the providers you'll use. If you only have OpenAI, agents using Claude or Gemini won't work — but the rest will.

---

## Step 4: Set Up Frontend

```powershell
cd C:\YourPath\AAF\AgentOS-Studio\frontend

# Install Node dependencies (this takes a few minutes)
npm install
```

**Create `frontend/.env.local`:**

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## Step 5: Run the Application

You need **two terminals** open simultaneously — one for backend, one for frontend.

### Terminal 1 — Backend

```powershell
cd C:\YourPath\AAF\AgentOS-Studio\backend
python main.py
```

Expected output:
```
[startup] Python: C:\Python311\python.exe
[startup] Version: 3.11.x ...
[startup] geopandas: 0.14.x  (or NOT AVAILABLE)
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

Backend is now at: **http://localhost:8000**
API docs at: **http://localhost:8000/api/docs**

### Terminal 2 — Frontend

```powershell
cd C:\YourPath\AAF\AgentOS-Studio\frontend
npm run dev
```

Expected output:
```
▲ Next.js 14.2.35
- Local:        http://localhost:3000
✓ Ready in 2.5s
```

Frontend is now at: **http://localhost:3000**

Open `http://localhost:3000` in your browser.

---

## Step 6: Verify Everything Works

Quick checklist:

- [ ] Open http://localhost:3000 — Dashboard loads
- [ ] Click **Agents** — list of default agents appears
- [ ] Click any agent → **Chat** — try sending "hello"
- [ ] If response streams back → ✅ everything is working
- [ ] If you get an API key error → check your `.env` file

---

## Common Issues & Fixes

### Backend: `ModuleNotFoundError: No module named 'agent_os'`

The Studio can't find the AgentOS core framework.

**Fix:**
- Verify folder structure: `AAF/AgentOS/` and `AAF/AgentOS-Studio/` must be siblings
- Re-run `pip install -e .` in the AgentOS folder

### Backend: `ModuleNotFoundError: No module named 'geopandas'`

Geospatial features are optional. Either:
- Skip them (most features still work), OR
- Install: `pip install geopandas shapely rtree pyproj`

### Frontend: `npm install` fails

Try:
```powershell
# Clear cache and retry
npm cache clean --force
rm -rf node_modules
rm package-lock.json
npm install
```

### Backend port 8000 already in use

```powershell
# Find what's using port 8000
netstat -ano | findstr :8000
# Kill the process or change port in main.py (last line: port=8000)
```

### CORS errors in browser

The backend allows `localhost:3000` only by default. If your frontend runs on a different port, edit [backend/main.py:42](backend/main.py#L42):

```python
allow_origins=["http://localhost:3000", "http://localhost:YOUR_PORT"],
```

### "401 Unauthorized" or LLM API errors

- Check that the API keys in `.env` are correct and active
- Verify you have billing/credits set up at the provider
- Test the key directly: https://platform.openai.com/playground

---

## Where Your Data Lives

The Studio stores user data in your home directory:

| Path | What's there |
|------|-------------|
| `~/.agent_os/studio.db` | SQLite database (projects, sessions, messages, workflows) |
| `~/.agent_os/configs/agents/` | Custom agent YAML configurations |
| `~/.agent_os/projects/{id}/files/` | Uploaded files per project |
| `~/.agent_os/projects/{id}/memory/` | Vector embeddings for semantic search |
| `~/.agent_os/agent_uploads/{name}/` | Files uploaded for direct agent chat |
| `~/.agent_os/workflow_uploads/{wid}/` | Files uploaded for workflows |

> On Windows, `~` resolves to `C:\Users\YourUsername\`

**To migrate existing projects:** Copy the entire `~/.agent_os/` folder from the old machine to the new one (after running the Studio at least once on the new machine to create the directory structure).

---

## Production Deployment Notes

For dev/personal use, the steps above are sufficient. For production:

1. **Don't run `python main.py` directly** — use a proper ASGI server with workers:
   ```powershell
   uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
   ```

2. **Build frontend for production:**
   ```powershell
   cd frontend
   npm run build
   npm start
   ```

3. **Use a reverse proxy** (Nginx, Caddy) to serve frontend + proxy `/api/*` to backend

4. **Add HTTPS** — never run production on plain HTTP

5. **Tighten CORS** — replace `localhost:3000` with your actual domain

6. **Implement authentication** — the current Studio has no login (see the commercialization plan in [CLAUDE.md](CLAUDE.md))

---

## Summary — Quick Commands

```powershell
# One-time setup
cd C:\YourPath\AAF\AgentOS && pip install -e .
cd C:\YourPath\AAF\AgentOS-Studio\backend && pip install -r requirements.txt
cd C:\YourPath\AAF\AgentOS-Studio\frontend && npm install

# Every time you want to run
# Terminal 1:
cd C:\YourPath\AAF\AgentOS-Studio\backend && python main.py

# Terminal 2:
cd C:\YourPath\AAF\AgentOS-Studio\frontend && npm run dev

# Browser: http://localhost:3000
```
