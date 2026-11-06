"""Enterprise Role-Based Access Control (RBAC) and Identity Models.

Defines decoupled user identity, role hierarchies, and permission primitives
compatible with enterprise reverse-proxy identity propagation (OIDC/OAuth2/SAML)
without coupling to a specific external identity vendor.
"""

from enum import Enum
from typing import Set, Dict, Any, Optional
from pydantic import BaseModel, Field


class UserRole(str, Enum):
    """User access tiers in an enterprise software engineering organization."""
    ADMIN = "admin"
    LEAD_ENGINEER = "lead_engineer"
    CONTRIBUTOR = "contributor"
    VIEWER = "viewer"


class Permission(str, Enum):
    """Fine-grained operational permissions within DevPilot AI."""
    EXECUTE_WORKFLOW = "execute_workflow"
    SIGN_OFF_HITL = "sign_off_hitl"
    PUBLISH_PR = "publish_pr"
    CONFIGURE_REPOSITORY = "configure_repository"
    VIEW_TELEMETRY = "view_telemetry"
    EXPORT_METRICS = "export_metrics"
    ADMIN_SETTINGS = "admin_settings"


# Role-to-Permissions Mapping
ROLE_PERMISSIONS: Dict[UserRole, Set[Permission]] = {
    UserRole.ADMIN: {
        Permission.EXECUTE_WORKFLOW,
        Permission.SIGN_OFF_HITL,
        Permission.PUBLISH_PR,
        Permission.CONFIGURE_REPOSITORY,
        Permission.VIEW_TELEMETRY,
        Permission.EXPORT_METRICS,
        Permission.ADMIN_SETTINGS,
    },
    UserRole.LEAD_ENGINEER: {
        Permission.EXECUTE_WORKFLOW,
        Permission.SIGN_OFF_HITL,
        Permission.PUBLISH_PR,
        Permission.CONFIGURE_REPOSITORY,
        Permission.VIEW_TELEMETRY,
        Permission.EXPORT_METRICS,
    },
    UserRole.CONTRIBUTOR: {
        Permission.EXECUTE_WORKFLOW,
        Permission.CONFIGURE_REPOSITORY,
        Permission.VIEW_TELEMETRY,
        Permission.EXPORT_METRICS,
    },
    UserRole.VIEWER: {
        Permission.VIEW_TELEMETRY,
        Permission.EXPORT_METRICS,
    },
}


class UserIdentity(BaseModel):
    """Authenticated user profile propagated through enterprise proxy headers or session state."""
    user_id: str = Field(..., description="Unique immutable user identifier (e.g. employee ID or sub claim)")
    email: str = Field(..., description="Corporate email address")
    display_name: str = Field(default="", description="User display name")
    role: UserRole = Field(default=UserRole.CONTRIBUTOR, description="Assigned RBAC role")
    tenant_id: str = Field(default="default", description="Multi-tenant partition identifier")
    authenticated_via: str = Field(default="proxy_header", description="Authentication mechanism")
    extra_claims: Dict[str, Any] = Field(default_factory=dict, description="Additional claims from ID token")

    def has_permission(self, permission: Permission) -> bool:
        """Evaluates whether the user holds the requested fine-grained permission."""
        allowed = ROLE_PERMISSIONS.get(self.role, set())
        return permission in allowed

