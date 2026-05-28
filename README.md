# NexusIQ — GraphRAG Investigation Workbench

An AI-powered investigation platform that combines a 3D knowledge graph with a multi-agent LLM workflow. Ask natural-language questions about your engineering data and get structured incident analysis powered by local Ollama models, Neo4j Aura, and ChromaDB.

![Next.js](https://img.shields.io/badge/Next.js-15.5-black)
![React](https://img.shields.io/badge/React-19.1-blue)
![TypeScript](https://img.shields.io/badge/TypeScript-5-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![Ollama](https://img.shields.io/badge/Ollama-local-orange)

---

## ✨ Features

- **3D Knowledge Graph** — WebGL-rendered entity graph with community detection, bloom effects, and node-click isolation
- **Multi-Agent Investigation** — LangGraph workflow with Graph, Incident, and Risk agents running in parallel
- **Hybrid Retrieval** — Neo4j graph traversal + ChromaDB vector search fused together
- **Local LLMs via Ollama** — Fully offline-capable; no OpenAI key required for investigation
- **Markdown Chat Responses** — Formatted output with headers, bullets, code blocks, and inline styles
- **Resizable Panels** — Drag-and-drop panel resizing for the 3-column layout
- **Stop / New Chat** — Cancel in-flight queries and clear session history

---

## 🏗️ Architecture

```
Browser (Next.js 15)
  ├── Left Panel  — InvestigationChat  →  POST /investigation/run  (SSE stream)
  ├── Center      — GraphVisualizer   →  GET  /graph/visualization
  └── Right Panel — Inspector / Timeline / Context

FastAPI Backend (port 8000)
  └── LangGraph Workflow
        classify → retrieve → plan
          ↳ DIRECT: synthesize
          ↳ FULL:   graph_agent + incident_agent + risk_agent → synthesize

Data Sources
  ├── Neo4j Aura      — graph relationships
  └── ChromaDB Cloud  — vector embeddings
```

---

## 🚀 Quick Start

### Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Node.js | 18+ | Frontend |
| pnpm | 8+ | Package manager |
| Python | 3.11+ | Backend |
| Ollama | latest | Local LLM inference |

---

### 1 — Clone & install frontend

```bash
git clone https://github.com/kangggchan/NexusIQ.git
cd NexusIQ

pnpm install
```

---

### 2 — Install Ollama and pull models

**Install Ollama** (macOS / Linux):
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Or download the desktop app from [ollama.com](https://ollama.com).

**Pull the required models:**
```bash
# Orchestrator + incident analysis
ollama pull llama3.1:8b

# Graph topology + risk assessment
ollama pull qwen2.5:7b

# Text embeddings (for ChromaDB retrieval)
ollama pull nomic-embed-text
```

**Verify Ollama is running:**
```bash
curl http://localhost:11434/api/tags
# Should return a JSON list of installed models
```

> Ollama starts automatically on macOS after installation. On Linux, run `ollama serve` in a separate terminal if it's not running.

---

### 3 — Set up the Python backend

```bash
# Create a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install backend dependencies
pip install -r backend/requirements.txt
```

---

### 4 — Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Ollama (usually no changes needed)
OLLAMA_HOST=http://localhost:11434
OLLAMA_BACKEND_URL=http://localhost:8000

# Neo4j Aura — create a free instance at console.neo4j.io
NEO4J_URI=neo4j+s://<instance-id>.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<your-neo4j-password>
NEO4J_DATABASE=neo4j

# ChromaDB Cloud — create a free tenant at trychroma.com
CHROMA_CLOUD_HOST=<region>.gcp.trychroma.com
CHROMA_API_KEY=<your-chroma-api-key>
CHROMA_TENANT=<your-tenant-id>
CHROMA_DATABASE=nexusiq
```

> `OPENAI_API_KEY` is only needed if you use the legacy GraphRAG CLI indexing pipeline. The investigation workflow runs entirely on Ollama.

---

### 5 — Start the backend

```bash
# Make sure your venv is active
source .venv/bin/activate

# Start FastAPI with hot-reload
python -m uvicorn backend.main:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

Test it:
```bash
curl http://localhost:8000/investigation/health
```

---

### 6 — Start the frontend

In a **new terminal**:

```bash
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000).

---

## 🤖 Ollama Model Configuration

The backend assigns specific models to each agent. You can override them in `.env`:

```env
MODEL_ORCHESTRATOR=llama3.1:8b    # classify, plan, synthesize
MODEL_GRAPH=qwen2.5:7b            # graph topology analysis
MODEL_INCIDENT=llama3.1:8b        # incident timeline reconstruction
MODEL_RISK=qwen2.5:7b             # cascading failure risk assessment
MODEL_EMBEDDING=nomic-embed-text  # ChromaDB vector search
```

**Minimum hardware for default models:**
- llama3.1:8b → ~6 GB VRAM / 8 GB RAM
- qwen2.5:7b → ~5 GB VRAM / 7 GB RAM
- nomic-embed-text → ~300 MB

**Lighter alternatives** (for machines with less RAM):
```bash
ollama pull llama3.2:3b    # faster, less accurate
ollama pull qwen2.5:3b
```
Then set `MODEL_ORCHESTRATOR=llama3.2:3b` etc. in `.env`.

---

## 📁 Project Structure

```
graphrag-workbench/
├── app/                        # Next.js App Router
│   ├── page.tsx               # Main 3-panel layout
│   └── api/                   # Next.js API routes (corpus, data)
├── backend/                    # FastAPI backend
│   ├── main.py                # App entry point
│   ├── config.py              # Settings from .env
│   ├── agents/                # Graph / Incident / Risk agents
│   ├── services/              # Ollama, embedding, model router
│   ├── investigation/         # LangGraph workflow
│   │   └── workflow.py        # classify→retrieve→plan→synthesize
│   └── api/routes/            # FastAPI route handlers
├── retrieval/                  # Hybrid retrieval layer
│   └── retrieval/             # Neo4j + ChromaDB hybrid retriever
├── components/                 # React components
│   ├── GraphVisualizer.tsx    # 3D WebGL graph
│   ├── nexusiq/               # Investigation-specific UI
│   │   ├── InvestigationChat.tsx
│   │   ├── IncidentTimeline.tsx
│   │   ├── ContextExplorer.tsx
│   │   └── ServiceInspector.tsx
│   └── ui/                    # shadcn/ui primitives
├── data/                       # Sample NexusIQ dataset
├── prompts/                    # LLM prompt templates
├── settings.yaml               # GraphRAG CLI config (legacy indexing)
├── .env.example                # Environment variable template
└── backend/requirements.txt   # Python dependencies
```

---

## 🛠️ Development

### Run both services together (two terminals)

**Terminal 1 — Backend:**
```bash
source .venv/bin/activate
python -m uvicorn backend.main:app --reload --port 8000
```

**Terminal 2 — Frontend:**
```bash
npm run dev
```

### Build for production

```bash
pnpm build
pnpm start
```

---

## 🐛 Troubleshooting

**Ollama connection refused**
```bash
# Check if Ollama is running
curl http://localhost:11434
# If not: start it
ollama serve
```

**Model not found error**
```bash
# List installed models
ollama list
# Pull missing model
ollama pull llama3.1:8b
```

**Backend fails to start — Neo4j/ChromaDB connection error**
- Verify credentials in `.env` match your cloud console
- Neo4j Aura free instances pause after inactivity — resume them at [console.neo4j.io](https://console.neo4j.io)

**Slow responses (>2 min per query)**
- Normal for first inference after model load — Ollama caches models in memory after first use
- Consider switching to smaller models (3B instead of 8B) in `.env`
- Ensure no other GPU-heavy processes are running

**Graph not rendering**
- Check `/graph/visualization` returns data: `curl http://localhost:8000/graph/visualization`
- Verify Neo4j instance is active and contains nodes

**Frontend TypeScript errors**
```bash
pnpm build   # shows all type errors
```

---

## 📋 Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| RAM | 8 GB | 16 GB |
| VRAM (GPU) | 6 GB | 12 GB |
| Storage | 10 GB free | SSD |
| Node.js | 18.x | 22.x |
| Python | 3.11 | 3.11 |

WebGL 2.0 support required for 3D visualization (Chrome 90+, Firefox 88+, Safari 14+, Edge 90+).
