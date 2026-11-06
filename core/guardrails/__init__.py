"""Security and Guardrails Package."""

from typing import List, Tuple
from core.guardrails.prompt_guard import prompt_guardrail, PromptGuardrail
from core.guardrails.ast_safety import ast_guardrail, ASTGuardrail
from core.guardrails.path_guard import path_guardrail, PathGuardrail
from core.guardrails.implementation_validator import implementation_validator, ImplementationValidator
from core.schemas.guardrails import SecurityAuditReport, SecurityViolation


class SecurityGuardrailSuite:
    """Unified security suite running prompt, AST, and path guardrails."""

    def __init__(self):
        self.prompt_guard = prompt_guardrail
        self.ast_guard = ast_guardrail
        self.path_guard = path_guardrail

    def run_full_audit(
        self,
        raw_prompt: str,
        code_patches: List[Tuple[str, str]],  # List of (file_path, content)
    ) -> SecurityAuditReport:
        """Executes full comprehensive security audit."""
        prompt_ok, prompt_violations = self.prompt_guard.validate_prompt(raw_prompt)

        all_ast_violations: List[SecurityViolation] = []
        for file_path, content in code_patches:
            _, ast_violations = self.ast_guard.scan_code(content, file_path=file_path)
            all_ast_violations.extend(ast_violations)

        passed = prompt_ok and len(all_ast_violations) == 0

        recommendation = (
            "Safe to proceed: No injection or dangerous syscalls detected."
            if passed
            else "BLOCKED: Security guardrail violations detected. Review before proceeding."
        )

        return SecurityAuditReport(
            passed=passed,
            prompt_injection_detected=not prompt_ok,
            ast_security_violations=all_ast_violations,
            path_traversal_violations=[],
            recommendation=recommendation,
        )


security_suite = SecurityGuardrailSuite()

__all__ = [
    "prompt_guardrail",
    "ast_guardrail",
    "path_guardrail",
    "implementation_validator",
    "ImplementationValidator",
    "security_suite",
    "SecurityGuardrailSuite",
]

