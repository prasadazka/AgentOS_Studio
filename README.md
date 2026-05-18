# AgentOS Studio

Visual studio for building, managing, and operating AI agents — a Next.js frontend on top of a FastAPI backend that uses the bundled `agent_os` library for agent orchestration, tools, memory, and workflows.

## Repository Layout

```
.
├── agent_os/           # Python library: agents, tools, memory, workflows, CLI
├── pyproject.toml      # agent_os package metadata
├── backend/            # FastAPI app (imports agent_os)
│   ├── main.py
│   ├── core/           # agent_manager, project_manager, workflow_manager, ...
│   ├── db/             # SQLite layer
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/           # Next.js 14 (App Router) + Tailwind
│   ├── src/
│   ├── package.json
│   └── Dockerfile
├── cloudbuild.yaml     # GCP Cloud Build → Cloud Run pipeline
├── .gcloudignore
└── .env.example
```

## Quick Start (Local)

### 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ..                                   # installs agent_os in editable mode
pip install -r requirements.txt
cp ../.env.example .env                             # fill in keys
uvicorn main:app --reload --port 8000
```

API docs at <http://localhost:8000/api/docs>.

### 2. Frontend

```bash
cd frontend
npm install
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm run dev
```

UI at <http://localhost:3000>.

## GCP Deployment (Cloud Run)

This repo ships a Cloud Build pipeline that builds both images, pushes to Artifact Registry, and deploys two Cloud Run services.

### One-time GCP setup

```bash
# Set your project
gcloud config set project YOUR_PROJECT_ID

# Enable APIs
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com

# Artifact Registry repo for images
gcloud artifacts repositories create agentos \
  --repository-format=docker \
  --location=us-central1

# Store secrets
echo -n "sk-..."   | gcloud secrets create openai-api-key --data-file=-
echo -n "AIza..."  | gcloud secrets create google-api-key --data-file=-

# Give Cloud Build's service account access to Secret Manager & Cloud Run
PROJECT_NUMBER=$(gcloud projects describe YOUR_PROJECT_ID --format='value(projectNumber)')
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/run.admin"
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### Deploy

First deploy (backend only — we need its URL for the frontend build):

```bash
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=_BACKEND_URL=https://placeholder.invalid
```

Grab the backend URL, then rebuild the frontend pointing at it:

```bash
BACKEND_URL=$(gcloud run services describe agentos-backend \
  --region=us-central1 --format='value(status.url)')

gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=_BACKEND_URL=${BACKEND_URL}
```

### Continuous deploy

Connect this repo to Cloud Build triggers on push to `main`:

```bash
gcloud builds triggers create github \
  --repo-name=AgentOS_Studio \
  --repo-owner=prasadazka \
  --branch-pattern=^main$ \
  --build-config=cloudbuild.yaml
```

## Notes

- `agent_os` is bundled in this repo as a sibling package — the backend imports it directly. There is no separate publish step.
- Data files (SQLite DBs, CSVs, JSON exports) are intentionally **not** committed. The backend creates them on first run.
- Secrets must come from Secret Manager in production; never commit `.env`.
- The `NEXT_PUBLIC_API_URL` is baked into the Next.js bundle at build time, so the frontend image is environment-specific.
