"""Authentication Middleware and Identity Extraction Engine.

Extracts authenticated user context from enterprise ingress reverse-proxy headers
(e.g., OAuth2-Proxy, Cloudflare Access, AWS ALB OIDC, Google Cloud IAP)
or local developer sessions, enforcing authorization checks at critical boundaries.
"""

from typing import Dict, Any, Optional, Tuple
from core.auth.models import UserIdentity, UserRole, Permission


class PermissionDeniedError(Exception):
    """Raised when an authenticated user attempts an action exceeding their assigned role."""
    def __init__(self, user_id: str, role: UserRole, required_permission: Permission):
        super().__init__(
            f"Access Denied: User '{user_id}' with role '{role.value}' lacks required permission '{required_permission.value}'."
        )
        self.user_id = user_id
        self.role = role
        self.required_permission = required_permission


def resolve_user_identity(
    headers: Optional[Dict[str, str]] = None,
    session_state: Optional[Dict[str, Any]] = None,
) -> UserIdentity:
    """Extracts and resolves user identity from forwarded HTTP headers or local session context.
    
    Supported Proxy Headers:
    - User ID: X-Forwarded-User, X-Auth-Request-User, X-Goog-Authenticated-User-Email
    - Email: X-Forwarded-Email, X-Auth-Request-Email
    - Role / Groups: X-Forwarded-Roles, X-Auth-Request-Roles, X-Forwarded-Groups
    - Tenant: X-Tenant-ID
    """
    normalized_headers: Dict[str, str] = {}
    if headers:
        normalized_headers = {k.lower(): v for k, v in headers.items()}

    # 1. Inspect enterprise reverse-proxy forwarded headers
    user_id = (
        normalized_headers.get("x-forwarded-user")
        or normalized_headers.get("x-auth-request-user")
        or normalized_headers.get("x-goog-authenticated-user-email")
    )
    email = (
        normalized_headers.get("x-forwarded-email")
        or normalized_headers.get("x-auth-request-email")
        or (user_id if user_id and "@" in user_id else "developer@enterprise.local")
    )
    roles_header = (
        normalized_headers.get("x-forwarded-roles")
        or normalized_headers.get("x-auth-request-roles")
        or normalized_headers.get("x-forwarded-groups", "")
    )
    tenant_id = normalized_headers.get("x-tenant-id", "default")

    if user_id:
        # Determine role from forwarded headers
        assigned_role = UserRole.CONTRIBUTOR
        roles_str = roles_header.lower()
        if "admin" in roles_str:
            assigned_role = UserRole.ADMIN
        elif "lead" in roles_str or "architect" in roles_str:
            assigned_role = UserRole.LEAD_ENGINEER
        elif "viewer" in roles_str:
            assigned_role = UserRole.VIEWER

        return UserIdentity(
            user_id=user_id,
            email=email,
            display_name=user_id.split("@")[0].replace(".", " ").title(),
            role=assigned_role,
            tenant_id=tenant_id,
            authenticated_via="reverse_proxy_header",
        )

    # 2. Inspect active local session state
    if session_state and "current_user" in session_state:
        stored = session_state["current_user"]
        if isinstance(stored, UserIdentity):
            return stored
        if isinstance(stored, dict):
            return UserIdentity(**stored)

    # 3. Development Fallback (Local standalone environment)
    return UserIdentity(
        user_id="local_developer",
        email="developer@devpilot.local",
        display_name="Local Developer",
        role=UserRole.LEAD_ENGINEER,
        tenant_id="default",
        authenticated_via="local_development_fallback",
    )


def enforce_permission(user: UserIdentity, permission: Permission) -> None:
    """Validates that user possesses the required permission or raises PermissionDeniedError."""
    if not user.has_permission(permission):
        raise PermissionDeniedError(
            user_id=user.user_id,
            role=user.role,
            required_permission=permission,
        )


def check_permission(user: UserIdentity, permission: Permission) -> Tuple[bool, Optional[str]]:
    """Evaluates permission and returns a boolean status with error explanation if denied."""
    if user.has_permission(permission):
        return True, None
    return False, f"User '{user.user_id}' with role '{user.role.value}' lacks '{permission.value}' permission."

