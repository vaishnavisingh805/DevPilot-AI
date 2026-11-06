"""Authentication, Authorization, and Multi-Tenancy Subsystem."""

from core.auth.models import (
    UserRole,
    Permission,
    ROLE_PERMISSIONS,
    UserIdentity,
)
from core.auth.middleware import (
    PermissionDeniedError,
    resolve_user_identity,
    enforce_permission,
    check_permission,
)
from core.auth.tenancy import (
    TenantIsolationError,
    TenantContext,
    sanitize_tenant_id,
    get_tenant_workspace_path,
)

__all__ = [
    "UserRole",
    "Permission",
    "ROLE_PERMISSIONS",
    "UserIdentity",
    "PermissionDeniedError",
    "resolve_user_identity",
    "enforce_permission",
    "check_permission",
    "TenantIsolationError",
    "TenantContext",
    "sanitize_tenant_id",
    "get_tenant_workspace_path",
]

