"""AST Code Safety Guardrail.

Performs static AST inspection on proposed Python code changes to detect
dangerous syscalls, unauthorized subprocess execution, or arbitrary eval/exec.
"""

import ast
from pathlib import Path
from typing import List, Tuple
from core.schemas.guardrails import SecurityViolation, ViolationLevel


DANGEROUS_CALLS = {
    "eval": "Arbitrary code evaluation (eval)",
    "exec": "Arbitrary code execution (exec)",
    "compile": "Dynamic code compilation",
    "__import__": "Dynamic unauthorized module import",
}

DANGEROUS_ATTRIBUTES = {
    ("os", "system"): "Unauthorized shell command execution (os.system)",
    ("os", "popen"): "Unauthorized shell pipe execution (os.popen)",
    ("subprocess", "Popen"): "Unauthorized process spawn (subprocess.Popen)",
    ("subprocess", "run"): "Unauthorized process execution (subprocess.run)",
    ("subprocess", "call"): "Unauthorized process execution (subprocess.call)",
    ("shutil", "rmtree"): "Recursive file system deletion (shutil.rmtree)",
    ("socket", "socket"): "Direct network socket creation",
}


class ASTSafetyScanner(ast.NodeVisitor):
    """Scans Python AST for dangerous function calls and malicious attributes."""

    def __init__(self, file_path: str = "unknown"):
        self.file_path = file_path
        self.violations: List[SecurityViolation] = []

    def visit_Call(self, node: ast.Call):
        # Check direct functions: eval, exec, etc.
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in DANGEROUS_CALLS:
                self.violations.append(SecurityViolation(
                    rule_name="DangerousFunctionRule",
                    severity=ViolationLevel.CRITICAL,
                    details=f"Forbidden function call: {DANGEROUS_CALLS[func_name]} in {self.file_path}",
                    line_number=node.lineno,
                ))

        # Check module.func calls: os.system, subprocess.run, etc.
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                module_name = node.func.value.id
                attr_name = node.func.attr
                key = (module_name, attr_name)
                if key in DANGEROUS_ATTRIBUTES:
                    self.violations.append(SecurityViolation(
                        rule_name="DangerousSyscallRule",
                        severity=ViolationLevel.CRITICAL,
                        details=f"Forbidden syscall: {DANGEROUS_ATTRIBUTES[key]} in {self.file_path}",
                        line_number=node.lineno,
                    ))

        self.generic_visit(node)


class ASTGuardrail:
    """Validator for static AST security verification."""

    def scan_code(self, code_str: str, file_path: str = "snippet.py") -> Tuple[bool, List[SecurityViolation]]:
        ext = Path(file_path).suffix.lower()
        if ext not in {".py", ".pyw"}:
            # For non-Python files (.ts, .tsx, .js, .jsx, .json, etc.), perform static pattern-based security checks
            violations: List[SecurityViolation] = []
            dangerous_patterns = [
                ("child_process.exec", "DangerousSyscallRule", "child_process execution detected"),
                ("child_process.spawn", "DangerousSyscallRule", "child_process spawn detected"),
                ("rm -rf /", "DangerousSyscallRule", "Destructive filesystem command detected"),
                ("eval(", "DangerousEvalRule", "Arbitrary code evaluation (eval) detected"),
            ]
            for pattern, rule_name, details in dangerous_patterns:
                if pattern in code_str:
                    violations.append(SecurityViolation(
                        rule_name=rule_name,
                        severity=ViolationLevel.CRITICAL,
                        details=f"{details} in {file_path}",
                        line_number=1,
                    ))
            passed = len(violations) == 0
            return passed, violations

        try:
            tree = ast.parse(code_str, filename=file_path)
        except SyntaxError as e:
            return False, [SecurityViolation(
                rule_name="SyntaxErrorRule",
                severity=ViolationLevel.CRITICAL,
                details=f"Python syntax error in {file_path}: {e.msg} at line {e.lineno}",
                line_number=e.lineno,
            )]

        scanner = ASTSafetyScanner(file_path=file_path)
        scanner.visit(tree)
        passed = all(v.severity != ViolationLevel.CRITICAL for v in scanner.violations)
        return passed, scanner.violations


# Global singleton
ast_guardrail = ASTGuardrail()

