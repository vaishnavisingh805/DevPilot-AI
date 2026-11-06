"""A2A (Agent-to-Agent) Protocol Message Envelope and Schema."""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class A2AMessageType(str, Enum):
    """Standard message types under the A2A specification."""
    TASK_DELEGATION = "TASK_DELEGATION"
    TASK_RESULT = "TASK_RESULT"
    REPLAN_REQUEST = "REPLAN_REQUEST"
    QUERY_STATE = "QUERY_STATE"
    STATE_BROADCAST = "STATE_BROADCAST"
    APPROVAL_REQUEST = "APPROVAL_REQUEST"
    APPROVAL_DECISION = "APPROVAL_DECISION"
    TOOL_PROXY_REQUEST = "TOOL_PROXY_REQUEST"
    TOOL_PROXY_RESPONSE = "TOOL_PROXY_RESPONSE"
    ERROR = "ERROR"


class A2AEnvelope(BaseModel):
    """The canonical Agent-to-Agent communication packet."""
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender_id: str = Field(..., description="e.g. CrewAI:PlannerAgent")
    sender_framework: str = Field(..., description="'crewai', 'google_adk', 'system', 'blackboard'")
    recipient_id: str = Field(..., description="e.g. GoogleADK:CoderAgent or '*' for broadcast")
    recipient_framework: Optional[str] = Field(default=None)
    message_type: A2AMessageType = Field(default=A2AMessageType.TASK_DELEGATION)
    correlation_id: Optional[str] = Field(
        default=None,
        description="ID of request message this is responding to"
    )
    conversation_id: str = Field(default="global-session")
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    signature: str = Field(default="", description="Cryptographic SHA256 checksum for provenance")

    def model_post_init(self, __context: Any) -> None:
        if not self.signature:
            self.signature = self.compute_signature()

    def compute_signature(self) -> str:
        """Compute message content integrity signature."""
        raw = f"{self.message_id}:{self.sender_id}:{self.recipient_id}:{self.message_type.value}:{json.dumps(self.payload, sort_keys=True)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def verify_integrity(self) -> bool:
        """Check if message payload has not been tampered with."""
        return self.signature == self.compute_signature()

