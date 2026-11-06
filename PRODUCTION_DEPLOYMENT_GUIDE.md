# DevPilot AI — Production Operations & Deployment Guide

**Platform:** DevPilot AI — Autonomous Multi-Agent Software Engineering Platform  
**Workspace:** `D:\MultiAgent-Software-Engineering`  
**Document Classification:** Production Operations & Infrastructure Deployment Manual  
**Version:** 1.0.0 (Post Phase 2.8 Hardening)  
**Target Environments:** Enterprise VPC | Single-Host Docker Compose | Cloud Run / AWS ECS  

---

## 1. System Requirements & Prerequisites

### 1.1 Compute & Storage Specifications
- **CPU:** 4+ cores (recommended for concurrent agent tasks, AST parsing, and sandboxed pytest execution).
- **RAM:** Minimum 8 GB (16 GB recommended for concurrent multi-model inference and ChromaDB vector caching).
- **Disk:** 20 GB SSD storage (accommodates ephemeral repository clones, vector embeddings, and SQLite WAL logs).

### 1.2 Operating System & Tooling
- **OS:** Ubuntu 22.04 LTS / 24.04 LTS, Debian 12, or Windows Server 2022.
- **Container Engine:** Docker Engine 24.0+ and Docker Compose v2.20+.
- **Reverse Proxy:** NGINX 1.24+ (provided via container).
- **Network Ingress:** Open inbound ports `80` (HTTP) and `443` (HTTPS). Internal application port `8501` must remain quarantined on internal bridge networks.

---

## 2. Production Topology & Architecture

```
                  +----------------------------------------------+
                  |               Internet / VPN                 |
                  +----------------------------------------------+
                                         |
                                  HTTPS (Port 443)
                                         v
                  +----------------------------------------------+
                  |           Ingress Tier: NGINX                |
                  |  - TLS 1.2 / 1.3 Termination                 |
                  |  - 301 HTTP -> HTTPS Enforced Redirect        |
                  |  - Security Headers: HSTS, CSP, X-Frame       |
                  |  - Streamlit WebSocket Proxying              |
                  |  - 50MB Max Upload Limit                     |
                  +----------------------------------------------+
                                         |
                            HTTP (Internal Port 8501)
                                         v
                  +----------------------------------------------+
                  |       Application Container (USER appuser)   |
                  |  - UID / GID: 10001                          |
                  |  - Non-root unprivileged process             |
                  |  - Read-only source code in /app             |
                  |  - Writable runtime: /app/sandbox_workspace  |
                  +----------------------------------------------+
                         |                              |
                         v                              v
            +--------------------------+  +--------------------------+
            |  SQLite Database (WAL)   |  |   ChromaDB Vector Store  |
            |  - experiments.db        |  |   - sandbox_workspace/   |
            |  - 5,000ms busy timeout  |  |     chromadb/            |
            |  - Atomic transactions   |  |                          |
            +--------------------------+  +--------------------------+
```

---

## 3. Step-by-Step Deployment Procedure

### Step 3.1: Repository Clone & Workspace Setup

```bash
# 1. Clone repository to enterprise host
git clone <enterprise-repo-url> /opt/devpilot-ai
cd /opt/devpilot-ai

# 2. Ensure persistent runtime directory exists with non-root ownership
mkdir -p sandbox_workspace/runs sandbox_workspace/sample_repo sandbox_workspace/tenants
sudo chown -R 10001:10001 sandbox_workspace
sudo chmod -R 775 sandbox_workspace
```

### Step 3.2: Production Environment Configuration

Create `/opt/devpilot-ai/.env.production` based on `.env.example`:

```ini
# ============================================================================
# LLM Provider Credentials
# ============================================================================
# Google Cloud Vertex AI or AI Studio Tier-1 Pay-As-You-Go Key (300+ RPM)
GEMINI_API_KEY=AIzaSy...your_production_key...
OPENAI_API_KEY=

# Execution Configuration
EXECUTION_MODE=live
DEFAULT_MODEL=gemini-3.8-flash
TEMPERATURE=0.2

# ============================================================================
# GitHub Integration
# ============================================================================
# Corporate Bot Account Personal Access Token (PAT) with 'repo' scope
GITHUB_TOKEN=ghp_...your_bot_token...
GITHUB_API_BASE_URL=https://api.github.com

# ============================================================================
# Governance, Security & Sandboxing
# ============================================================================
REQUIRE_HUMAN_APPROVAL=true
AUTO_APPROVE_IN_TESTS=false
ENABLE_PROMPT_INJECTION_CHECK=true
ENABLE_AST_SECURITY_SCAN=true
RESTRICT_FILE_OPERATIONS_TO_SANDBOX=true
MAX_TOOL_TIMEOUT_SECONDS=30

# ============================================================================
# Observability
# ============================================================================
LOG_LEVEL=INFO
ENABLE_PROVENANCE_LOGGING=true
```

> [!IMPORTANT]
> Restrict file permissions on the production environment file:
> `chmod 600 /opt/devpilot-ai/.env.production`

---

### Step 3.3: TLS / SSL Certificate Provisioning

> [!WARNING]
> Do not claim TLS is active until tested with real certificates in a deployment environment. Fake or self-signed certificates must never be used in customer-facing production.

#### Option A: Let's Encrypt with Certbot (Public Domains)

```bash
# 1. Create certificate directories
mkdir -p deploy/certs
sudo chmod 700 deploy/certs

# 2. Issue certificates using standalone certbot
sudo certbot certonly --standalone \
  -d devpilot.yourdomain.com \
  --email security@yourdomain.com \
  --agree-tos \
  --no-eff-email

# 3. Symlink / copy fullchain and privkey to deployment volume
sudo cp /etc/letsencrypt/live/devpilot.yourdomain.com/fullchain.pem deploy/certs/fullchain.pem
sudo cp /etc/letsencrypt/live/devpilot.yourdomain.com/privkey.pem deploy/certs/privkey.pem
sudo chmod 644 deploy/certs/fullchain.pem
sudo chmod 600 deploy/certs/privkey.pem
```

#### Option B: Corporate Public Key Infrastructure (Internal VPC)
If deploying within a corporate intranet, request an X.509 certificate signed by your corporate Certificate Authority (CA):
- Place certificate chain in `deploy/certs/fullchain.pem`.
- Place private key in `deploy/certs/privkey.pem`.

---

### Step 3.4: Launching Production Services

Deploy the container stack using the hardened production Docker Compose definition:

```bash
cd /opt/devpilot-ai/deploy

# Build and start services in detached mode
docker compose -f docker-compose.prod.yml --env-file ../.env.production up -d --build
```

### Step 3.5: Health Check & Verification

Verify the running containers:

```bash
# 1. Check container status
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Expected Output:
# devpilot_nginx_gateway    Up (healthy)    0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
# devpilot_core_system      Up (healthy)    8501/tcp

# 2. Test internal health endpoint
curl -k -f https://localhost/_stcore/health

# Expected Output:
# ok
```

---

## 4. SQLite WAL Mode Operations & Backup Procedures

### 4.1 WAL Mode Verification
Verify that the database is operating in Write-Ahead Logging mode:

```bash
docker exec -it devpilot_core_system python -c \
  "from evaluation.experiment_db import experiment_storage; print('Journal:', experiment_storage.get_journal_mode())"

# Expected Output:
# Journal: wal
```

### 4.2 Live Hot Backups
Because SQLite is operating in WAL mode, backups can be taken without locking or stopping the application using SQLite's online vacuum/backup API:

```bash
# Automated nightly backup script
BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
docker exec devpilot_core_system sqlite3 /app/sandbox_workspace/experiments.db \
  ".backup '/app/sandbox_workspace/experiments_backup_${BACKUP_DATE}.db'"

# Verify backup integrity
docker exec devpilot_core_system sqlite3 /app/sandbox_workspace/experiments_backup_${BACKUP_DATE}.db \
  "PRAGMA integrity_check;"
```

---

## 5. Troubleshooting & Operational Runbooks

### 5.1 Quota Exhaustion (HTTP 429) Handling
- **Symptom:** Logs report `API Quota Exhausted: RESOURCE_EXHAUSTED`.
- **Cause:** Free-tier Gemini API key has exceeded 15 RPM.
- **Resolution:**
  1. The system automatically halts the active task and prevents infinite retry loops.
  2. In `.env.production`, replace `GEMINI_API_KEY` with an enterprise Tier-1 key.
  3. Restart the core container: `docker compose -f docker-compose.prod.yml restart multiagent-se`.

### 5.2 Permission Denied in Sandbox Workspace
- **Symptom:** Container logs show `PermissionError: [Errno 13] Permission denied: '/app/sandbox_workspace/...'`.
- **Cause:** Host directory ownership does not match `appuser` (UID `10001`).
- **Resolution:**
  ```bash
  sudo chown -R 10001:10001 /opt/devpilot-ai/sandbox_workspace
  sudo chmod -R 775 /opt/devpilot-ai/sandbox_workspace
  ```

### 5.3 WebSocket Connection Drops
- **Symptom:** Streamlit displays "Connecting..." or reloads constantly.
- **Cause:** Reverse proxy did not forward the WebSocket upgrade headers.
- **Resolution:**
  - Verify that `deploy/nginx/conf.d/devpilot.conf` includes:
    ```nginx
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_http_version 1.1;
    ```
  - Ensure `proxy_read_timeout` is set to `3600s`.

---

## 6. Staging Verification & Launch Runbooks

### 6.1 Local Workstation Launch (Direct Python)
```powershell
# 1. Activate virtual environment
.\.venv\Scripts\Activate.ps1

# 2. Run automated test suite
python -m pytest tests/test_p0_hardening.py tests/test_dashboard.py -v

# 3. Launch interactive SaaS dashboard
streamlit run dashboard/app.py --server.port 8501
```

### 6.2 Staging Container Stack Verification
```bash
# 1. Build and launch services in staging mode
docker compose -f deploy/docker-compose.prod.yml up -d --build

# 2. Probe health endpoint through NGINX
curl -k -f https://localhost/_stcore/health

# 3. Confirm non-root execution inside container
docker exec devpilot_core_system id
# Expected: uid=10001(appuser) gid=10001(appgroup)

# 4. Confirm SQLite WAL mode active
docker exec devpilot_core_system python -c \
  "from evaluation.experiment_db import experiment_storage; print(experiment_storage.get_journal_mode())"
# Expected: wal
```


