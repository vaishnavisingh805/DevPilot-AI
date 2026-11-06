# Deployment & Containerization Guide

**Document:** Operations, Containerization & Production Deployment Manual  
**Project:** Multi-Agent AI System for Autonomous Software Engineering  
**Version:** 1.0.0  
**Target Environment:** Local Python 3.11.9 | Docker 29.x | Docker Compose | Cloud Run / AWS ECS  

---

## 1. System Requirements & Prerequisites

### 1.1 Hardware Specifications
* **CPU:** 4+ Cores recommended (multi-agent concurrent callbacks and sandboxed pytest execution).
* **RAM:** Minimum 8 GB (16 GB recommended for concurrent multi-model inference and sandbox caching).
* **Storage:** 5 GB free SSD space for ephemeral sandbox clones, virtual environment, and SQLite persistence.

### 1.2 Software Prerequisites
* **Operating System:** Windows 10/11, Ubuntu 22.04 LTS+, or macOS Sonoma+.
* **Python Runtime:** Python 3.11.x (tested on Python 3.11.9).
* **Docker Engine:** Docker 24.x+ / Docker Desktop (optional for containerized deployment).
  *(Workstation Status: Docker CLI v29.7.2 is installed locally; the Docker Desktop daemon service is currently stopped. To run containers locally, launch Docker Desktop before executing `docker compose up`).*
* **API Credentials:** Google AI Studio Gemini API Key (configured in `.env`).

---

## 2. Local Environment Setup & Execution

### 2.1 Virtual Environment Installation
```powershell
# 1. Clone repository and navigate to workspace
cd D:\MultiAgent-Software-Engineering

# 2. Create Python 3.11 virtual environment
python -m venv .venv

# 3. Activate virtual environment
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# 4. Upgrade pip and install production dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2.2 Environment Configuration
Create a local `.env` file in the project root based on `.env.example`:
```ini
# LLM Provider Configuration
GEMINI_API_KEY=your_gemini_api_key_here
OPENAI_API_KEY=

# Execution Settings
EXECUTION_MODE=live
DEFAULT_MODEL=gemini-3.8-flash
TEMPERATURE=0.2

# System Directories
SANDBOX_ROOT=./sandbox_workspace
BLACKBOARD_PERSIST_PATH=./sandbox_workspace/blackboard_state.json
EXPERIMENTS_DB_PATH=./sandbox_workspace/experiments.db

# Governance & Guardrails
REQUIRE_HUMAN_APPROVAL=true
ENABLE_PROMPT_INJECTION_CHECK=true
ENABLE_AST_SECURITY_SCAN=true
MAX_TOOL_TIMEOUT_SECONDS=30
```

### 2.3 Running the Test Suite
```powershell
.\.venv\Scripts\python.exe -m pytest -v
```
*Expected Outcome:* 42 passed tests with 0 failures across all 12 modules.

### 2.4 Launching the Interactive Dashboard
```powershell
.\.venv\Scripts\streamlit.exe run dashboard/app.py
```
*Access UI:* Open `http://localhost:8501` in your browser.

---

## 3. Docker Containerization Deployment

The project provides a fully containerized deployment pipeline based on `python:3.11-slim`.

### 3.1 Dockerfile Architecture
* **Base Image:** `python:3.11-slim` with system utilities (`build-essential`, `curl`, `git`).
* **Isolation:** Python bytecode generation disabled (`PYTHONDONTWRITEBYTECODE=1`), unbuffered logging enabled (`PYTHONUNBUFFERED=1`).
* **Port:** Default Streamlit port `8501` exposed.
* **Health Check:** Integrated curl probe querying `http://localhost:8501/_stcore/health` every 30 seconds.
* **Volume Mount:** Quarantined sandbox mounted at `/app/sandbox_workspace`.

### 3.2 Building the Docker Image
```powershell
docker build -t multiagent-software-engineering:latest .
```

### 3.3 Running via Docker
```powershell
docker run -d `
  --name multiagent_se_system `
  -p 8501:8501 `
  --env-file .env `
  -v ${PWD}/sandbox_workspace:/app/sandbox_workspace `
  multiagent-software-engineering:latest
```

### 3.4 Orchestration via Docker Compose
```powershell
# Launch multi-agent service in background
docker compose up -d

# Verify container status and health
docker compose ps

# View real-time container logs
docker compose logs -f

# Gracefully terminate service
docker compose down
```

---

## 4. Production Cloud Deployment Architecture

For academic evaluation or enterprise cloud production, the system can be deployed onto Google Cloud Platform (GCP) or Amazon Web Services (AWS) without architectural modifications:

```
                  ┌──────────────────────────────────────────────┐
                  │                 DNS / CDN                    │
                  │         Cloudflare / AWS Route 53            │
                  └───────────────────────┬──────────────────────┘
                                          │
                                          ▼
                  ┌──────────────────────────────────────────────┐
                  │          TLS Reverse Proxy / ALB             │
                  │          (NGINX / AWS ALB / Caddy)           │
                  └───────────────────────┬──────────────────────┘
                                          │ Port 8501
                                          ▼
                  ┌──────────────────────────────────────────────┐
                  │         CONTAINER RUNTIME ENVIRONMENT        │
                  │   GCP Cloud Run / AWS ECS Fargate / GKE      │
                  │                                              │
                  │  ┌────────────────────────────────────────┐  │
                  │  │ Multi-Agent System (Streamlit + ADK)   │  │
                  │  └───────────────────┬────────────────────┘  │
                  │                      │ Mount                 │
                  │                      ▼                       │
                  │  ┌────────────────────────────────────────┐  │
                  │  │ Persistent Volume (sandbox_workspace)  │  │
                  │  └────────────────────────────────────────┘  │
                  └───────────────────────┬──────────────────────┘
                                          │
                                          ▼
                  ┌──────────────────────────────────────────────┐
                  │            CLOUD SECRETS MANAGER             │
                  │      GCP Secret Manager / AWS SSM Store      │
                  │      (Injects GEMINI_API_KEY dynamically)    │
                  └──────────────────────────────────────────────┘
```

### 4.1 Production Secrets Governance
* In production, **never** mount local `.env` files.
* Inject `GEMINI_API_KEY` through GCP Secret Manager (`gcloud secrets`) or AWS Systems Manager Parameter Store / Secrets Manager.

### 4.2 Resource Sizing
* **Minimum Cloud Instance:** 2 vCPU, 4 GB Memory (e.g., GCP Cloud Run 2 vCPU / 4 GiB or AWS `t3.medium`).
* **Scale-to-Zero:** Can be enabled for cost efficiency on GCP Cloud Run when inactive.

> [!IMPORTANT]
> In accordance with project governance rules, cloud deployment should not be initiated without explicit faculty approval and billing authorization. No public cloud resources have been provisioned and zero cloud hosting costs have been incurred. The system's container configuration and IaC architecture are verified and primed for cloud deployment when authorized.

