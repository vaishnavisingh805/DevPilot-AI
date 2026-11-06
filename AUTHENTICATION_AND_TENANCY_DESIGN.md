# DevPilot AI — Authentication Architecture & Multi-Tenancy Design

**Platform:** DevPilot AI — Autonomous Multi-Agent Software Engineering Platform  
**Document Classification:** Enterprise Identity Architecture & Tenancy Isolation Design  
**Version:** 1.0.0 (Post Phase 2.8 Hardening)  
**Target Environments:** Enterprise SaaS | Internal Engineering Portal | Single-Tenant & Multi-Tenant Deployments  

---

## 1. Architectural Overview & Design Philosophy

DevPilot AI adopts a **decoupled, perimeter-based authentication model**. Rather than embedding a brittle, custom identity provider inside the application container, DevPilot AI relies on modern enterprise standard patterns:
1. **Perimeter Authentication:** The reverse proxy / ingress gateway terminates TLS and negotiates user authentication with the corporate Identity Provider (IdP) via OpenID Connect (OIDC), OAuth 2.0, or SAML 2.0.
2. **Identity Propagation:** The ingress gateway validates the user's cryptographic token and forwards verified user identity, roles, and tenant claims downstream to DevPilot AI via standardized, tamper-evident HTTP headers.
3. **Internal RBAC & Governance:** The internal `core/auth` subsystem ingests these headers, resolves user permissions according to a strict Role-Based Access Control matrix, and enforces authorization checks before autonomous workflows, code modifications, or GitHub Pull Requests can be executed.

```mermaid
flowchart TD
    subgraph EnterpriseEdge["Enterprise Perimeter (Ingress)"]
        UserBrowser[Engineer Browser] -->|1. Unauthenticated Request| Gateway[Edge Gateway / Reverse Proxy]
        Gateway -->|2. OIDC Auth Redirect| IdP[Enterprise IdP: Okta / Google / Azure AD]
        IdP -->|3. ID Token / Claims| Gateway
    end

    subgraph HeaderInjection["Identity Propagation Tier"]
        Gateway -->|4. Injected Headers: X-Forwarded-User, Roles, Tenant| AuthMiddleware[core/auth/middleware.py]
    end

    subgraph InternalGovernance["Internal Authorization & Sandboxing"]
        AuthMiddleware --> RBAC[Role-Based Access Control Engine]
        RBAC --> PermCheck{Permission Verification}
        PermCheck -- Denied --> BlkAuth[BLOCKED_AUTH / PermissionDeniedError]
        PermCheck -- Granted --> Workflow[Autonomous Agent Workflow / HITL Sign-off]
        Workflow --> TenantSandbox[Isolated Tenant Sandbox: sandbox_workspace/tenants/{tenant_id}]
    end
```

---

## 2. Authentication Boundaries

The platform establishes three distinct security boundaries:

| Boundary | Responsible Component | Enforcement Mechanism | Failure Behavior |
| :--- | :--- | :--- | :--- |
| **1. Edge Ingress Boundary** | Ingress Gateway (NGINX / Cloudflare Access / AWS ALB / Google IAP) | TLS Termination, OIDC token exchange, cookie session verification. | HTTP 302 Redirect to IdP Login; unauthenticated requests cannot reach application. |
| **2. Identity Ingestion Boundary** | `core/auth/middleware.py` (`resolve_user_identity`) | Sanitization of `X-Forwarded-*` headers, session context mapping, and role extraction. | Falls back to restricted Viewer or development profile based on configuration. |
| **3. Action Authorization Boundary** | `PRPublisher`, `HITLGatekeeper`, `AutonomousEngineeringOrchestrator` | Verification of explicit fine-grained `Permission` enum before executing privileged actions. | Halts execution immediately; returns `status: "BLOCKED_AUTH"` without side effects. |

---

## 3. User Identity Propagation & Header Specification

When running behind an enterprise ingress gateway, DevPilot AI expects the following sanitized headers:

| Header Name | Type | Description | Example |
| :--- | :---: | :--- | :--- |
| `X-Forwarded-User` | `string` | Unique, immutable corporate user identifier (email or employee ID). | `sarah.chen@acme.corp` |
| `X-Forwarded-Email` | `string` | Validated corporate email address. | `sarah.chen@acme.corp` |
| `X-Forwarded-Roles` | `string` | Comma-separated list of group/role claims from the IdP. | `lead_engineer,architecture-reviewers` |
| `X-Tenant-ID` | `string` | Alphanumeric tenant partition identifier for multi-tenant deployments. | `acme-fintech` |

### Security Invariants:
- The reverse proxy must strip any inbound `X-Forwarded-*` headers originating from the public Internet to prevent header spoofing.
- In production, DevPilot AI containers must run within a private Docker/VPC network where only the trusted reverse proxy can establish connections.

---

## 4. Role-Based Access Control (RBAC) Matrix

DevPilot AI defines four hierarchical user roles and fine-grained permissions in [`core/auth/models.py`](file:///d:/MultiAgent-Software-Engineering/core/auth/models.py):

| Fine-Grained Permission | Admin | Lead Engineer | Contributor | Viewer |
| :--- | :---: | :---: | :---: | :---: |
| `EXECUTE_WORKFLOW` (Trigger multi-agent autonomous engineering) | **YES** | **YES** | **YES** | NO |
| `CONFIGURE_REPOSITORY` (Connect repos & index RAG codebases) | **YES** | **YES** | **YES** | NO |
| `SIGN_OFF_HITL` (Approve code changes and commit to repository) | **YES** | **YES** | NO | NO |
| `PUBLISH_PR` (Create and publish remote GitHub Pull Requests) | **YES** | **YES** | NO | NO |
| `VIEW_TELEMETRY` (Inspect Blackboard, logs, diffs, and metrics) | **YES** | **YES** | **YES** | **YES** |
| `EXPORT_METRICS` (Download CSV / JSON evaluation reports) | **YES** | **YES** | **YES** | **YES** |
| `ADMIN_SETTINGS` (System-wide configuration, secrets, quotas) | **YES** | NO | NO | NO |

### Guardrail Integration:
- **Pull Request Publishing:** `PRPublisher.publish_pull_request(..., user=user)` verifies that `user.has_permission(Permission.PUBLISH_PR) == True`. Unauthorized attempts are rejected with `BLOCKED_AUTH`.
- **Human Gatekeeper Approval:** `HITLGatekeeper.approve_and_commit(..., user=user)` verifies that `user.has_permission(Permission.SIGN_OFF_HITL) == True`. Non-lead contributors cannot sign off on code.

---

## 5. Multi-Tenancy Isolation Architecture

To support multi-tenant SaaS or multi-departmental corporate deployments, DevPilot AI implements workspace and quota partitioning:

```
sandbox_workspace/
├── blackboard_state.json      (Global state)
├── experiments.db             (ACID database with tenant_id indexes)
└── tenants/
    ├── tenant_acme_corp/      (Strictly isolated directory)
    │   ├── repos/             (Tenant cloned codebases)
    │   └── runs/              (Tenant execution sandboxes)
    └── tenant_fintech_labs/
        ├── repos/
        └── runs/
```

### 5.1 Directory Containment & Path Traversal Defense
- `core/auth/tenancy.py` implements `sanitize_tenant_id()`, stripping non-alphanumeric characters.
- `get_tenant_workspace_path(base_sandbox, tenant_id)` enforces strict relative path containment using `target_path.relative_to(base_resolved)`. Any attempt to traverse out of the sandbox raises `TenantIsolationError`.

### 5.2 Database Partitioning Strategy
- In single-database multi-tenant setups, the `experiments` and `pull_requests` tables incorporate a `tenant_id TEXT NOT NULL DEFAULT 'default'` column.
- Queries are filtered with `WHERE tenant_id = ?`, ensuring tenants cannot view each other's metrics or Pull Request records.

---

## 6. External Identity Provider Integration Options

To activate production single sign-on, choose one of the following recommended architectures:

### Option 1: Google Cloud Identity-Aware Proxy (IAP)
- **Best for:** Google Cloud / Cloud Run / GKE enterprise deployments.
- **Mechanism:** Google IAP authenticates users against Google Workspace or Cloud Identity and sets HTTP header:
  `X-Goog-Authenticated-User-Email: accounts.google.com:user@enterprise.com`
- **DevPilot AI Compatibility:** Automatically recognized by `core/auth/middleware.py`.
- **Required External Setup:**
  1. Enable Cloud Identity-Aware Proxy in GCP Console.
  2. Configure OAuth Consent Screen with corporate domain.
  3. Grant `IAP-secured Web App User` role to corporate IAM groups.

### Option 2: AWS Application Load Balancer (ALB) with OIDC
- **Best for:** AWS ECS / EKS enterprise deployments.
- **Mechanism:** AWS ALB performs OIDC handshake with Okta, Microsoft Entra ID, or Amazon Cognito, forwarding:
  `x-amzn-oidc-identity: user-id-claim`
  `x-amzn-oidc-data: signed-jwt-claims`
- **Required External Setup:**
  1. Create ALB HTTPS Listener with rule: `Authenticate: OIDC`.
  2. Register Client ID and Secret from Okta / Microsoft Entra.
  3. Map ALB forward action to DevPilot AI target group.

### Option 3: Cloudflare Access / Zero Trust
- **Best for:** Multi-cloud or on-premises edge deployments without VPN.
- **Mechanism:** Cloudflare Edge authenticates user via corporate SSO and injects:
  `Cf-Access-Authenticated-User-Email: user@enterprise.com`
- **Required External Setup:**
  1. Add DevPilot AI as an Access Application in Cloudflare Zero Trust dashboard.
  2. Define Access Policies (e.g., Allow `*@yourcompany.com`).
  3. Enable CORS and header pass-through.

### Option 4: Self-Hosted OAuth2-Proxy (Any Kubernetes or Docker Stack)
- **Best for:** Air-gapped on-premises deployments using Keycloak, Okta, or GitLab.
- **Mechanism:** An unprivileged sidecar container (`oauth2-proxy/oauth2-proxy:latest`) intercepts incoming traffic, handles OIDC session cookies, and forwards `X-Forwarded-User` and `X-Forwarded-Roles` to NGINX.
- **Configuration Snippet (`oauth2-proxy.cfg`):**
  ```ini
  http_address = "0.0.0.0:4180"
  upstreams = ["http://devpilot_nginx_gateway:80"]
  provider = "oidc"
  oidc_issuer_url = "https://keycloak.enterprise.local/realms/engineering"
  client_id = "devpilot-ai"
  client_secret = "..."
  cookie_secure = true
  pass_user_headers = true
  pass_authorization_header = true
  ```

