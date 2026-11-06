"""Prompt and Persona Variations Specification and Configurations.

Supports measurable, empirical comparisons between distinct engineering personas:
1. Strict-Architect: High architectural rigor, defensive validation, exhaustive edge-case tests.
2. Balanced-Engineer: Standard clean architecture, balanced error handling and test coverage.
3. Permissive-Prototyper: Minimal functional implementation, rapid velocity, concise logic.
"""

from enum import Enum
from typing import Dict, Any, Union
from pydantic import BaseModel, Field


class PersonaType(str, Enum):
    STRICT_ARCHITECT = "Strict-Architect"
    BALANCED_ENGINEER = "Balanced-Engineer"
    PERMISSIVE_PROTOTYPER = "Permissive-Prototyper"


class PersonaConfig(BaseModel):
    """Configuration definition for an agent persona."""
    persona_type: PersonaType
    title: str
    description: str
    system_instruction_modifier: str
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    validation_rigor: str = "standard"  # 'high', 'standard', 'low'
    acceptance_criteria_depth: str = "detailed"


PERSONA_CONFIGS: Dict[PersonaType, PersonaConfig] = {
    PersonaType.STRICT_ARCHITECT: PersonaConfig(
        persona_type=PersonaType.STRICT_ARCHITECT,
        title="Strict Principal Architect",
        description=(
            "Prioritizes high structural rigor, comprehensive defensive type/input validation, "
            "zero tolerance for missing edge cases (empty collections, invalid types, boundary values), "
            "and exhaustive unit test matrices."
        ),
        system_instruction_modifier=(
            "Apply strict enterprise engineering standards. All methods must have full type annotations, "
            "defensive guards checking input types and empty inputs, clear docstrings documenting parameters "
            "and exceptions. Generate comprehensive unit tests covering nominal cases, boundary conditions, "
            "and all expected exceptions."
        ),
        temperature=0.1,
        validation_rigor="high",
        acceptance_criteria_depth="exhaustive",
    ),
    PersonaType.BALANCED_ENGINEER: PersonaConfig(
        persona_type=PersonaType.BALANCED_ENGINEER,
        title="Balanced Senior Software Engineer",
        description=(
            "Balances architectural rigor, algorithmic precision, code readability, "
            "and pragmatic test suites covering normal operations and standard edge conditions."
        ),
        system_instruction_modifier=(
            "Apply balanced clean code practices. Implement clean, readable, modular logic with standard docstrings "
            "and type annotations. Provide unit tests covering expected use cases and basic error conditions."
        ),
        temperature=0.2,
        validation_rigor="standard",
        acceptance_criteria_depth="standard",
    ),
    PersonaType.PERMISSIVE_PROTOTYPER: PersonaConfig(
        persona_type=PersonaType.PERMISSIVE_PROTOTYPER,
        title="Permissive Rapid Prototyper",
        description=(
            "Prioritizes implementation velocity and concise minimal code to deliver functional "
            "features quickly without overhead."
        ),
        system_instruction_modifier=(
            "Implement the core feature directly with minimal required code. Focus on functional correctness "
            "and concise logic. Keep tests straightforward and targeted directly to core requirement functionality."
        ),
        temperature=0.4,
        validation_rigor="low",
        acceptance_criteria_depth="minimal",
    ),
}


def get_persona(persona_input: Union[str, PersonaType, None]) -> PersonaConfig:
    """Resolves string or PersonaType to PersonaConfig."""
    if isinstance(persona_input, PersonaType):
        return PERSONA_CONFIGS[persona_input]
    if isinstance(persona_input, str):
        for pt, cfg in PERSONA_CONFIGS.items():
            if pt.value.lower() == persona_input.lower() or cfg.title.lower() == persona_input.lower():
                return cfg
    return PERSONA_CONFIGS[PersonaType.BALANCED_ENGINEER]

