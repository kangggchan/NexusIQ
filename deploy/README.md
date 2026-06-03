# Deployment Layout

This project keeps container deployment files in one place:

- `deploy/docker/frontend/Dockerfile`
- `deploy/docker/backend/Dockerfile`

## Build Images

Run from project root:

```bash
docker build -f deploy/docker/frontend/Dockerfile -t graphrag-frontend:latest .
docker build -f deploy/docker/backend/Dockerfile -t graphrag-backend:latest .
```

## Google Cloud Run (example)

1. Build and push images to Artifact Registry.
2. Deploy backend first (it needs Vertex AI access via ADC / service account).
3. Deploy frontend and set `BACKEND_URL` to the backend Cloud Run URL.

```bash
# Example variables
PROJECT_ID=<your-gcp-project>
REGION=us-central1
REPO=graphrag

# Tag images
docker tag graphrag-backend:latest ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/graphrag-backend:latest
docker tag graphrag-frontend:latest ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/graphrag-frontend:latest

# Push images
docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/graphrag-backend:latest
docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/graphrag-frontend:latest

# Deploy backend (service account must have roles/aiplatform.user)
gcloud run deploy graphrag-backend \
  --image ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/graphrag-backend:latest \
  --region ${REGION} \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION}"

# Deploy frontend (replace BACKEND_URL with URL from previous command output)
BACKEND_URL=https://graphrag-backend-xxxxx.a.run.app

gcloud run deploy graphrag-frontend \
  --image ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/graphrag-frontend:latest \
  --region ${REGION} \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars BACKEND_URL=${BACKEND_URL}
```

## Required Backend Env Vars

Set these in Cloud Run for the backend service (use Secret Manager for sensitive values):

| Variable | Description | Example |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | GCP project ID for Vertex AI | `my-project-123` |
| `GOOGLE_CLOUD_LOCATION` | Vertex AI region | `us-central1` |
| `MODEL_ORCHESTRATOR` | Orchestrator agent model | `gemini-2.5-flash` |
| `MODEL_GRAPH` | Graph analysis agent model | `gemini-2.5-flash` |
| `MODEL_INCIDENT` | Incident agent model | `gemini-2.5-flash` |
| `MODEL_RISK` | Risk agent model | `gemini-2.5-pro` |
| `MODEL_EMBEDDING` | Embedding model | `text-embedding-005` |
| `NEO4J_URI` | Neo4j Aura connection URI | `neo4j+s://xxxx.databases.neo4j.io` |
| `NEO4J_USERNAME` | Neo4j username | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j password | *(use Secret Manager)* |
| `NEO4J_DATABASE` | Neo4j database name | `neo4j` |
| `CHROMA_CLOUD_HOST` | ChromaDB Cloud host | `api.trychroma.com` |
| `CHROMA_API_KEY` | ChromaDB API key | *(use Secret Manager)* |
| `CHROMA_TENANT` | ChromaDB tenant | `default_tenant` |
| `CHROMA_DATABASE` | ChromaDB database | `nexusiq` |

## Service Account Permissions

The Cloud Run backend service account needs:

- `roles/aiplatform.user` — Vertex AI model inference
- `roles/ml.viewer` — (optional) list Vertex AI models

## Health Endpoints

- `GET /health` — liveness probe
- `GET /health/gemini` — Vertex AI connectivity check
- `GET /models/status` — configured agent models

