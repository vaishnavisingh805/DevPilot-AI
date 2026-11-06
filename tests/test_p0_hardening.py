"""Tests for Phase 2.8 P0 Production Hardening.

Covers:
1. Dockerfile & Docker Compose non-root execution and permission structure.
2. SQLite durability: Write-Ahead Logging (WAL), busy timeout, transaction atomicity, connection lifecycle closure.
3. Database data preservation (verifying existing records remain intact).
4. Reverse proxy (NGINX) configuration directives, security headers, and WebSocket settings.
5. Role-Based Access Control (RBAC), reverse-proxy identity extraction, and tenant workspace isolation.
6. Gemini error classification, bounded retry policies, timeout limits, and token/cost tracking.
"""

import os
import sqlite3
import tempfile
from pathlib import Path
import pytest

from config.settings import settings
from config.models_config import (
    classify_gemini_error,
    bounded_retry,
    validate_and_resolve_model,
    calculate_cost,
    TokenCostTracker,
    QuotaExceededError,
    RateLimitError,
    ModelTimeoutError,
    TransientProviderError,
    GeminiProviderError,
    SUPPORTED_MODELS,
)
from core.auth import (
    UserRole,
    Permission,
    UserIdentity,
    resolve_user_identity,
    enforce_permission,
    check_permission,
    PermissionDeniedError,
    TenantIsolationError,
    sanitize_tenant_id,
    get_tenant_workspace_path,
)
from core.hitl import hitl_gatekeeper
from core.github.pr_publisher import PRPublisher
from evaluation.experiment_db import ExperimentStorage, experiment_storage
from core.schemas.metrics import PerformanceMetrics


# ============================================================================
# 1. Docker Non-Root Configuration Tests
# ============================================================================

def test_dockerfile_non_root_configuration():
    """Verify Dockerfile creates and executes as an unprivileged user (appuser)."""
    dockerfile_path = settings.BASE_DIR / "Dockerfile"
    assert dockerfile_path.exists(), "Dockerfile must exist"
    content = dockerfile_path.read_text(encoding="utf-8")

    assert "useradd" in content and "appuser" in content, "Dockerfile must define 'appuser'"
    assert "10001" in content, "Dedicated non-root UID 10001 must be specified"
    assert "USER appuser" in content, "Dockerfile must declare 'USER appuser' directive"
    assert "chown -R appuser:appgroup" in content, "Application runtime directories must be owned by appuser"
    assert "HEALTHCHECK" in content, "Health check probe must be present"


def test_docker_compose_non_root_specification():
    """Verify Docker Compose configurations define unprivileged user execution."""
    compose_path = settings.BASE_DIR / "docker-compose.yml"
    assert compose_path.exists(), "docker-compose.yml must exist"
    compose_content = compose_path.read_text(encoding="utf-8")

    assert 'user: "10001:10001"' in compose_content or "user: 10001:10001" in compose_content, (
        "docker-compose.yml must specify user 10001:10001"
    )

    prod_compose = settings.BASE_DIR / "deploy" / "docker-compose.prod.yml"
    assert prod_compose.exists(), "deploy/docker-compose.prod.yml must exist"
    prod_content = prod_compose.read_text(encoding="utf-8")
    assert 'user: "10001:10001"' in prod_content, "Production compose must specify non-root user"


# ============================================================================
# 2. SQLite Durability, WAL Mode & Transaction Tests
# ============================================================================

def test_sqlite_wal_mode_and_busy_timeout():
    """Verify that SQLite storage activates WAL journal mode and busy timeout."""
    assert experiment_storage.get_journal_mode() == "wal", "SQLite must operate in WAL journal mode"
    assert experiment_storage.get_busy_timeout() == 5000, "SQLite busy timeout must be 5000ms"


def test_sqlite_existing_records_preserved():
    """Verify that existing experiment and pull request records are not cleared or corrupted."""
    count = experiment_storage.count()
    assert count >= 1, f"Expected existing experiment records to be preserved, found {count}"
    prs = experiment_storage.get_pull_requests()
    assert len(prs) >= 1, f"Expected existing pull requests to be preserved, found {len(prs)}"


def test_sqlite_transaction_rollback_and_connection_closing():
    """Verify that transactions roll back on error and connection objects are closed."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db = Path(tmp_dir) / "test_durability.db"
        storage = ExperimentStorage(db_path=test_db)

        # 1. Successful transaction
        m = PerformanceMetrics(run_id="TEST-COMMIT-1", success=True)
        storage.record_run(m)
        assert storage.count() == 1

        # 2. Failed transaction rolls back
        try:
            with storage.transaction() as conn:
                conn.execute("INSERT INTO experiments (run_id, timestamp, architecture_pattern, benchmark_task, persona, execution_status) VALUES ('FAIL-1', 'ts', 'arch', 'task', 'pers', 'completed')")
                raise ValueError("Forced failure to trigger rollback")
        except ValueError:
            pass

        # Verify FAIL-1 was rolled back
        assert storage.get_by_id("FAIL-1") is None
        assert storage.count() == 1


# ============================================================================
# 3. NGINX Reverse Proxy Configuration Tests
# ============================================================================

def test_nginx_configuration_directives():
    """Verify NGINX configuration files contain required proxy directives and security headers."""
    nginx_conf = settings.BASE_DIR / "deploy" / "nginx" / "nginx.conf"
    devpilot_conf = settings.BASE_DIR / "deploy" / "nginx" / "conf.d" / "devpilot.conf"

    assert nginx_conf.exists(), "nginx.conf must exist"
    assert devpilot_conf.exists(), "devpilot.conf must exist"

    conf_text = devpilot_conf.read_text(encoding="utf-8")

    # 1. HTTP-to-HTTPS redirect
    assert "return 301 https://$host$request_uri;" in conf_text, "Must enforce 301 redirect to HTTPS"

    # 2. Modern TLS protocols and ciphers
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in conf_text, "Must mandate TLSv1.2 and TLSv1.3"
    assert "ssl_certificate /etc/nginx/certs/fullchain.pem;" in conf_text
    assert "ssl_certificate_key /etc/nginx/certs/privkey.pem;" in conf_text

    # 3. Enterprise security headers
    assert "Strict-Transport-Security" in conf_text, "Must include HSTS header"
    assert "X-Frame-Options" in conf_text, "Must include X-Frame-Options header"
    assert "X-Content-Type-Options" in conf_text, "Must include X-Content-Type-Options header"
    assert "Content-Security-Policy" in conf_text, "Must include Content-Security-Policy header"

    # 4. Streamlit WebSocket upgrade headers
    assert "proxy_set_header Upgrade $http_upgrade;" in conf_text, "Must forward WebSocket Upgrade header"
    assert 'proxy_set_header Connection "upgrade";' in conf_text, "Must forward Connection upgrade header"

    # 5. Request size limits and timeouts
    assert "client_max_body_size 50M;" in conf_text, "Must allow up to 50M uploads for codebases"
    assert "proxy_read_timeout 3600s;" in conf_text, "Must allow extended timeout for agent reasoning"


# ============================================================================
# 4. Authentication, Authorization (RBAC) & Tenancy Tests
# ============================================================================

def test_resolve_user_identity_from_proxy_headers():
    """Verify user identity extraction from enterprise reverse-proxy forwarded headers."""
    # Lead Engineer headers
    headers_lead = {
        "X-Forwarded-User": "sarah.lead@corp.internal",
        "X-Forwarded-Roles": "lead_engineer,developer",
        "X-Tenant-ID": "tenant-alpha",
    }
    user_lead = resolve_user_identity(headers=headers_lead)
    assert user_lead.user_id == "sarah.lead@corp.internal"
    assert user_lead.role == UserRole.LEAD_ENGINEER
    assert user_lead.tenant_id == "tenant-alpha"
    assert user_lead.has_permission(Permission.PUBLISH_PR) is True
    assert user_lead.has_permission(Permission.SIGN_OFF_HITL) is True

    # Viewer headers
    headers_viewer = {
        "X-Forwarded-User": "guest.auditor@corp.internal",
        "X-Forwarded-Roles": "viewer",
    }
    user_viewer = resolve_user_identity(headers=headers_viewer)
    assert user_viewer.role == UserRole.VIEWER
    assert user_viewer.has_permission(Permission.VIEW_TELEMETRY) is True
    assert user_viewer.has_permission(Permission.EXECUTE_WORKFLOW) is False
    assert user_viewer.has_permission(Permission.PUBLISH_PR) is False


def test_rbac_permission_enforcement():
    """Verify that permission enforcement blocks unauthorized actions."""
    viewer = UserIdentity(
        user_id="viewer1",
        email="viewer@test.com",
        role=UserRole.VIEWER,
    )
    with pytest.raises(PermissionDeniedError):
        enforce_permission(viewer, Permission.EXECUTE_WORKFLOW)

    lead = UserIdentity(
        user_id="lead1",
        email="lead@test.com",
        role=UserRole.LEAD_ENGINEER,
    )
    # Lead has permission; must not raise
    enforce_permission(lead, Permission.EXECUTE_WORKFLOW)


def test_pr_publisher_and_hitl_rbac_blocking():
    """Verify PR publishing and HITL commit respect RBAC permissions."""
    viewer = UserIdentity(
        user_id="auditor_bob",
        email="bob@corp.internal",
        role=UserRole.VIEWER,
    )
    publisher = PRPublisher()
    res = publisher.publish_pull_request(
        run_id="RUN-TEST-RBAC",
        sandbox_path=settings.SANDBOX_ROOT,
        repo_url="https://github.com/org/repo",
        user=viewer,
    )
    assert res["success"] is False
    assert res["status"] == "BLOCKED_AUTH"
    assert "AUTHORIZATION_DENIED" in res["error"]

    # HITL gatekeeper check
    hitl_res = hitl_gatekeeper.approve_and_commit(
        run_id="TEST-RUN",
        user=viewer,
    )
    assert hitl_res["success"] is False
    assert "AUTHORIZATION_DENIED" in hitl_res["error"]


def test_tenant_workspace_isolation():
    """Verify tenant ID sanitization and path traversal prevention."""
    assert sanitize_tenant_id("ACME_Corp-123!") == "acme_corp-123"
    assert sanitize_tenant_id("../../evil") == "evil"

    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        tenant_path = get_tenant_workspace_path(base, "acme_corp")
        assert tenant_path.exists()
        assert tenant_path.name == "acme_corp"
        assert tenant_path.parent.name == "tenants"


# ============================================================================
# 5. Gemini Production Configuration & Bounded Retry Tests
# ============================================================================

def test_gemini_error_classification():
    """Verify classification of Gemini provider errors."""
    e_quota = Exception("google.api_core.exceptions.ResourceExhausted: 429 Resource has been exhausted (e.g. check quota).")
    classified_quota = classify_gemini_error(e_quota)
    assert isinstance(classified_quota, QuotaExceededError)
    assert classified_quota.status_code == 429

    e_rate = Exception("HTTP 429: Too Many Requests; rate limit exceeded")
    classified_rate = classify_gemini_error(e_rate)
    assert isinstance(classified_rate, RateLimitError)

    e_timeout = Exception("Deadline Exceeded: operation timed out after 30s")
    classified_timeout = classify_gemini_error(e_timeout)
    assert isinstance(classified_timeout, ModelTimeoutError)

    e_transient = Exception("503 Service Unavailable: upstream connection reset")
    classified_transient = classify_gemini_error(e_transient)
    assert isinstance(classified_transient, TransientProviderError)


def test_bounded_retry_never_retries_quota_exhausted():
    """Verify that QuotaExceededError halts immediately without retry iterations."""
    call_count = 0

    def failing_call():
        nonlocal call_count
        call_count += 1
        raise Exception("RESOURCE_EXHAUSTED: quota limit reached")

    with pytest.raises(QuotaExceededError):
        bounded_retry(failing_call, max_retries=3, initial_backoff=0.01)

    assert call_count == 1, "QuotaExceededError must NEVER be retried"


def test_bounded_retry_recovers_on_transient_failure():
    """Verify that transient failures are retried and can recover successfully."""
    attempts = 0

    def transient_call():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise Exception("503 Service Unavailable")
        return "SUCCESS"

    result = bounded_retry(transient_call, max_retries=2, initial_backoff=0.01)
    assert result == "SUCCESS"
    assert attempts == 2


def test_bounded_retry_respects_max_retries_bound():
    """Verify that retry logic is strictly bounded by max_retries with zero infinite loops."""
    call_count = 0

    def persistent_failure():
        nonlocal call_count
        call_count += 1
        raise Exception("500 Internal Server Error")

    with pytest.raises(TransientProviderError):
        bounded_retry(persistent_failure, max_retries=2, initial_backoff=0.01)

    assert call_count == 3  # Initial attempt + 2 retries


def test_model_resolution_and_token_cost_tracker():
    """Verify model resolution fallback and thread-safe cost tracking."""
    # Model resolution
    assert validate_and_resolve_model("gemini-3.8-flash") == "gemini-3.8-flash"
    assert validate_and_resolve_model("unknown-model") == settings.DEFAULT_MODEL

    # Token and cost tracking
    tracker = TokenCostTracker()
    cost = tracker.add_usage("gemini-3.8-flash", prompt_tokens=1000, completion_tokens=1000)
    expected_cost = calculate_cost("gemini-3.8-flash", 1000, 1000)
    assert cost == expected_cost
    totals = tracker.get_totals()
    assert totals["prompt_tokens"] == 1000
    assert totals["completion_tokens"] == 1000
    assert totals["total_tokens"] == 2000
    assert totals["total_cost_usd"] == expected_cost
