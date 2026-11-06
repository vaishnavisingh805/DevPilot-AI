"""Path Traversal and Sandbox Boundary Guardrail."""

from pathlib import Path
from typing import Tuple, Optional
from config.settings import settings
from core.schemas.guardrails import SecurityViolation, ViolationLevel


class PathGuardrail:
    """Enforces that file operations strictly remain within designated sandbox workspace."""

    def __init__(self, sandbox_root: Optional[Path] = None):
        self.sandbox_root = (sandbox_root or settings.SANDBOX_ROOT).resolve()

    def validate_path(self, target_path: Path) -> Tuple[bool, Optional[SecurityViolation]]:
        resolved = target_path.resolve()
        try:
            # Check if resolved path is relative to sandbox_root
            resolved.relative_to(self.sandbox_root)
            return True, None
        except ValueError:
            return False, SecurityViolation(
                rule_name="PathTraversalRule",
                severity=ViolationLevel.CRITICAL,
                details=f"Path traversal detected: '{target_path}' resolves outside sandbox '{self.sandbox_root}'",
                target_snippet=str(target_path),
            )


# Global singleton
path_guardrail = PathGuardrail()

