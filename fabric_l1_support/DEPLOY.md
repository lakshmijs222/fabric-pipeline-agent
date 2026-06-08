# Deploying the Fabric L1 Support Bot

This app is containerized so it runs **identically on your machine and in the cloud** —
no "works on my laptop" surprises. The bot runs continuously; a container platform
keeps it alive 24/7 and restarts it on crash.

## What's in the box
- **One Docker image** (`Dockerfile`) containing the bot + dashboard code.
- **`docker-compose.yml`** runs it as two services from that one image:
  - `bot` → `python main.py` (the polling/diagnose/heal loop)
  - `dashboard` → Streamlit UI on port **8503**
- Shared named volumes (`fabric-data`, `fabric-logs`) so the dashboard reads the
  audit log the bot writes, and state survives restarts.

## Run it anywhere with Docker

```bash
cd fabric_l1_support

# 1. Make sure .env has your real credentials (AZURE_*, ANTHROPIC_API_KEY, etc.)
#    Copy the template if needed:  cp .env.example .env

# 2. Build and start both services
docker compose up --build -d

# 3. Open the dashboard
#    http://localhost:8503

# Follow logs / stop
docker compose logs -f bot
docker compose down
```

That's the same image you'd ship to any cloud.

## Going to the cloud (production)

The container is the portable foundation. To run it as a real 24/7 service:

| Platform | How |
|----------|-----|
| **Azure Container Apps** (recommended — matches your Fabric/Azure stack) | Push the image to Azure Container Registry, create a Container App per service. Continuous, auto-restart, scale-to-zero. |
| **AWS ECS / Fargate** | Push to ECR, run as a service. |
| **Render / Railway / Fly.io** | Point at this repo; they build the Dockerfile and host it with a public URL. |

### Production hardening (recommended next steps)
1. **Secrets** → move from `.env` to the platform's secret store
   (Azure Key Vault + Managed Identity), so no credentials live in files.
2. **State persistence** → the bot keeps `processed_runs` and retry counts
   **in memory**; on restart they reset. For production, back these (and the
   audit log) with a managed database (e.g. Azure Database for PostgreSQL)
   instead of the local volume.
3. **CI/CD** → a GitHub Actions workflow to build the image and deploy on every
   push, so `git push` ships a new version automatically.

> Note: the **migration/** project is a set of one-time setup scripts, not a
> hosted service — it is not part of this deployment.
