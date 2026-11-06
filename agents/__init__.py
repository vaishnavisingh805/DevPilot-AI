"""Multi-Agent Framework Package (CrewAI & Google ADK)."""

from agents.crewai import (
    CrewAIPlannerAgent,
    CrewAIManagerAgent,
    CrewAIAuditorAgent,
)
from agents.google_adk import (
    GoogleADKCoderAgent,
    GoogleADKTestGeneratorAgent,
    GoogleADKDebuggerAgent,
)

__all__ = [
    "CrewAIPlannerAgent",
    "CrewAIManagerAgent",
    "CrewAIAuditorAgent",
    "GoogleADKCoderAgent",
    "GoogleADKTestGeneratorAgent",
    "GoogleADKDebuggerAgent",
]

