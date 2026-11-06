"""Agent-to-Agent (A2A) Protocol Package."""

from core.a2a.envelope import A2AEnvelope, A2AMessageType
from core.a2a.bus import A2ABus, global_a2a_bus

__all__ = ["A2AEnvelope", "A2AMessageType", "A2ABus", "global_a2a_bus"]

