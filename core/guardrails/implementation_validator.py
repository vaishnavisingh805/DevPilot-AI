"""Implementation Quality and Requirement Alignment Validator.

Enforces that proposed code changes represent genuine, requirement-driven
software implementations rather than empty diffs, comment injections,
or synthetic metadata exports.
"""

import ast
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from core.schemas.code_changes import FilePatch


class ImplementationValidator:
    """Rigorous validator ensuring code changes represent authentic feature implementations."""

    METADATA_PATTERNS = [
        re.compile(r"devpilotFeature_[a-zA-Z0-9_]+", re.IGNORECASE),
        re.compile(r"devpilot_feature_[a-zA-Z0-9_]+", re.IGNORECASE),
        re.compile(r"_devpilot_managed", re.IGNORECASE),
        re.compile(r"_devpilot_update_id", re.IGNORECASE),
        re.compile(r"DevPilotAI-Autonomous-Patch", re.IGNORECASE),
        re.compile(r"implemented_and_verified", re.IGNORECASE),
    ]

    @staticmethod
    def _strip_comments_and_whitespace(code: str, file_path: str) -> str:
        """Strips comments and whitespace according to file language."""
        ext = Path(file_path).suffix.lower() if file_path else ""

        if ext in {".py", ".pyw"}:
            # Strip python comments and docstrings
            no_comments = re.sub(r"#.*", "", code)
            no_docstrings = re.sub(r'(""".*?"""|\'\'\'.*?\'\'\')', "", no_comments, flags=re.DOTALL)
            return re.sub(r"\s+", "", no_docstrings)

        if ext in {".ts", ".tsx", ".js", ".jsx"}:
            # Strip JS/TS single line and block comments
            no_single = re.sub(r"//.*", "", code)
            no_block = re.sub(r"/\*.*?\*/", "", no_single, flags=re.DOTALL)
            return re.sub(r"\s+", "", no_block)

        return re.sub(r"\s+", "", code)

    def validate_patch_quality(
        self,
        file_path: str,
        original_code: str,
        modified_code: str,
        unified_diff: str = "",
    ) -> Tuple[bool, str]:
        """Validates that a patch modifies functional logic rather than comments or metadata."""
        # 1. Non-empty check
        if not modified_code.strip():
            return False, "EMPTY_PATCH: Proposed modified content is completely empty."

        if original_code.strip() and original_code.strip() == modified_code.strip():
            return False, "NO_OP_PATCH: Proposed code is identical to original code; zero functional change."

        # 2. Comment-only check
        stripped_orig = self._strip_comments_and_whitespace(original_code, file_path)
        stripped_mod = self._strip_comments_and_whitespace(modified_code, file_path)

        if original_code.strip() and stripped_orig == stripped_mod:
            return False, "COMMENT_ONLY_PATCH: Code change only adds or modifies comments/docstrings with zero functional statements."

        # 3. Metadata-only check
        for pattern in self.METADATA_PATTERNS:
            if pattern.search(modified_code):
                # Check if the diff primarily consists of this metadata injection
                diff_added_lines = [
                    line[1:].strip() for line in unified_diff.splitlines()
                    if line.startswith("+") and not line.startswith("+++")
                ]
                # If any added line contains the metadata pattern, verify if real functional code exists
                metadata_lines = [l for l in diff_added_lines if pattern.search(l)]
                if metadata_lines:
                    # Check if all added non-empty lines are metadata or comments
                    functional_added = [
                        l for l in diff_added_lines
                        if l and not l.startswith("//") and not l.startswith("/*") and not l.startswith("*") and not pattern.search(l)
                    ]
                    # If added lines only contain metadata declaration
                    if not functional_added or len(functional_added) < 2:
                        return False, "METADATA_ONLY_PATCH: Code change only injects synthetic metadata export/constant instead of functional feature implementation."

        # 4. Check for fake constant exports (e.g. export const devpilotFeature... = { ... })
        if "export const devpilotFeature" in modified_code or "def devpilot_feature_" in modified_code:
            return False, "METADATA_ONLY_PATCH: Detected synthetic devpilotFeature constant injection."

        return True, "VALID_PATCH"

    def validate_requirement_alignment(
        self,
        requirement_prompt: str,
        patches: Dict[str, FilePatch],
        acceptance_criteria: Optional[List[Any]] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Verifies that the patched files and symbols address the specific requirements."""
        if not patches:
            return False, {
                "is_aligned": False,
                "error": "NO_PATCHES: No active patches available for requirement validation.",
                "details": {},
            }

        prompt_lower = requirement_prompt.lower()
        validation_details: Dict[str, Any] = {}
        violations: List[str] = []

        # 1. Target file relevance check
        # If prompt specifically targets a component or module, verify at least one patch touches relevant files
        expected_components = re.findall(r"([\w\-]+(?:\.tsx|\.ts|\.jsx|\.js|\.py))", requirement_prompt)
        if expected_components:
            patched_file_names = [Path(p).name for p in patches.keys()]
            matched = any(
                comp.lower() in [f.lower() for f in patched_file_names]
                or any(comp.lower().split(".")[0] in f.lower() for f in patched_file_names)
                for comp in expected_components
            )
            if not matched:
                violations.append(
                    f"UNRELATED_FILE_MODIFICATION: Requirement targets {expected_components}, but patches only modify {patched_file_names}."
                )

        combined_code = "\n".join(p.modified_content for p in patches.values())

        # 2. Login Page / Form Validation Domain Checks
        is_login_req = any(w in prompt_lower for w in ["login", "signin", "auth", "credential"])
        if is_login_req:
            # Check Password Visibility Toggle
            has_pw_kw = "password" in prompt_lower or "pw" in prompt_lower
            has_toggle_kw = any(w in prompt_lower for w in ["toggle", "visibility", "show password", "show/hide", "hide password"])
            if has_pw_kw and has_toggle_kw:
                has_visibility_state = bool(
                    re.search(r"(showpassword|ispasswordvisible|passwordvisible|showpass)", combined_code, re.IGNORECASE)
                )
                has_type_switch = bool(
                    re.search(r"type\s*=\s*\{\s*(?:showpassword|ispasswordvisible|passwordvisible|showpass)\s*\?\s*['\"]text['\"]\s*:\s*['\"]password['\"]\s*\}", combined_code, re.IGNORECASE)
                    or re.search(r"type\s*=\s*\{\s*!?(?:showpassword|ispasswordvisible|passwordvisible|showpass)\s*\?\s*['\"]password['\"]\s*:\s*['\"]text['\"]\s*\}", combined_code, re.IGNORECASE)
                    or ("type={showPassword" in combined_code or "type={isPasswordVisible" in combined_code)
                )
                validation_details["password_visibility_state"] = has_visibility_state
                validation_details["password_type_toggle"] = has_type_switch

                if not has_visibility_state:
                    violations.append("MISSING_CRITERION: Password visibility state (e.g. showPassword) is not implemented.")
                if not has_type_switch:
                    violations.append("MISSING_CRITERION: Dynamic password input type switching (text vs password) is not implemented.")

            # Check Email Validation
            if "email" in prompt_lower and ("valid" in prompt_lower or "check" in prompt_lower):
                has_email_check = bool(
                    re.search(r"(\S+@\S+\.\S+|\.includes\(['\"]@['\"]\)|emailRegex|validateEmail)", combined_code)
                    or re.search(r"(email|mail).*?(valid|test|regex|pattern|empty)", combined_code, re.IGNORECASE)
                )
                validation_details["email_validation"] = has_email_check
                if not has_email_check:
                    violations.append("MISSING_CRITERION: Email format or syntax validation is not implemented.")

            # Check Required-field / Empty Submit Validation
            if "validation" in prompt_lower or "empty" in prompt_lower or "required" in prompt_lower:
                has_field_check = bool(
                    re.search(r"(!email|!password|\.trim\(\)|email\.length|password\.length)", combined_code)
                    or re.search(r"(error|errorMessage|setError|alert)", combined_code, re.IGNORECASE)
                )
                validation_details["required_field_validation"] = has_field_check
                if not has_field_check:
                    violations.append("MISSING_CRITERION: Required-field validation / empty submission error handling is not implemented.")

            # Check Authentication Preservation
            has_auth_preserved = bool(
                re.search(r"(handleSubmit|onSubmit|signIn|login|authenticate)", combined_code, re.IGNORECASE)
            )
            validation_details["auth_preserved"] = has_auth_preserved
            if not has_auth_preserved:
                violations.append("REGRESSION_DETECTED: Core authentication submission workflow was removed or broken.")

        # 3. Calculator Domain Checks
        is_calc_req = "standard_deviation" in prompt_lower or "calculator" in prompt_lower
        if is_calc_req:
            has_std_method = "def standard_deviation" in combined_code
            has_math_sqrt = "math.sqrt" in combined_code or "** 0.5" in combined_code
            has_sample_param = "sample" in combined_code
            has_value_error = "ValueError" in combined_code

            validation_details["standard_deviation_method"] = has_std_method
            validation_details["mathematical_sqrt"] = has_math_sqrt
            validation_details["sample_parameter"] = has_sample_param
            validation_details["value_error_handling"] = has_value_error

            if not has_std_method:
                violations.append("MISSING_CRITERION: standard_deviation method is not implemented.")
            if not has_math_sqrt:
                violations.append("MISSING_CRITERION: Mathematical standard deviation variance/square root calculation missing.")

        is_aligned = (len(violations) == 0)
        return is_aligned, {
            "is_aligned": is_aligned,
            "violations": violations,
            "details": validation_details,
        }


implementation_validator = ImplementationValidator()

