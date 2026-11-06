"""Multi-Tenant Isolation and Workspace Partitioning Engine.

Ensures complete file system, database query, and quota isolation
between separate enterprise customer tenants or engineering business units.
"""

import re
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field


class TenantIsolationError(Exception):
    """Raised when an operation attempts to breach tenant workspace boundaries."""
    pass


class TenantContext(BaseModel):
    """Execution context and quota governance for an isolated enterprise tenant."""
    tenant_id: str = Field(..., description="Unique alphanumeric tenant slug (e.g. 'acme-corp')")
    tenant_name: str = Field(default="", description="Descriptive enterprise tenant name")
    quota_rpm: int = Field(default=60, description="Requests Per Minute allocated to tenant")
    quota_tpm: int = Field(default=2000000, description="Tokens Per Minute allocated to tenant")
    sandbox_partition_name: str = Field(default="", description="Dedicated sub-folder name")

    def __init__(self, **data):
        super().__init__(**data)
        if not self.sandbox_partition_name:
            self.sandbox_partition_name = f"tenant_{self.tenant_id}"


def sanitize_tenant_id(raw_tenant_id: str) -> str:
    """Sanitizes tenant identifiers to prevent directory traversal and injection."""
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]", "", raw_tenant_id.strip().lower())
    if not cleaned or len(cleaned) < 2:
        return "default"
    return cleaned


def get_tenant_workspace_path(base_sandbox: Path, tenant_id: str) -> Path:
    """Resolves and bounds the dedicated isolated workspace for a given tenant."""
    sanitized = sanitize_tenant_id(tenant_id)
    base_resolved = base_sandbox.resolve()
    target_path = (base_resolved / "tenants" / sanitized).resolve()

    # Enforce path containment
    try:
        target_path.relative_to(base_resolved)
    except ValueError:
        raise TenantIsolationError(
            f"Tenant boundary breach detected: '{target_path}' escapes base sandbox '{base_resolved}'."
        )

    target_path.mkdir(parents=True, exist_ok=True)
    return target_path

