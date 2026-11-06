"""Callback functions and event stream observers."""

import logging
from datetime import datetime, timezone
from typing import Callable, List, Dict, Any, Optional

from core.blackboard import BlackboardEvent, global_blackboard
from core.a2a import A2AEnvelope, global_a2a_bus
from core.schemas import SecurityViolation

logger = logging.getLogger("ObservabilityCallbacks")


class PipelineCallbackEvent:
    """Telemetry item emitted across agent, blackboard, tool, and guardrail lifecycle."""
    def __init__(
        self,
        event_name: str,
        category: str,
        details: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.timestamp = datetime.now(timezone.utc)
        self.event_name = event_name
        self.category = category  # 'agent', 'blackboard', 'a2a', 'tool', 'guardrail', 'hitl'
        self.details = details
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "event_name": self.event_name,
            "category": self.category,
            "details": self.details,
            "metadata": self.metadata,
        }


class SystemCallbackManager:
    """Unified callback registry monitoring multi-agent execution, intermediate outputs, and errors."""

    def __init__(self):
        self._listeners: List[Callable[[PipelineCallbackEvent], None]] = []
        self._event_stream: List[PipelineCallbackEvent] = []

        # Connect to Blackboard and A2A Bus
        global_blackboard.subscribe(self._on_blackboard_event)
        global_a2a_bus.add_listener(self._on_a2a_event)

    def subscribe(self, listener: Callable[[PipelineCallbackEvent], None]) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[PipelineCallbackEvent], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def emit(self, event: PipelineCallbackEvent) -> None:
        self._event_stream.append(event)
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception as e:
                logger.warning(f"Error in callback listener: {e}")

    def get_stream(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._event_stream]

    def clear(self) -> None:
        self._event_stream.clear()

    # --- Standard Hook Methods ---

    def on_pipeline_start(self, run_id: str, requirement_prompt: str) -> None:
        self.emit(PipelineCallbackEvent(
            event_name="PIPELINE_START",
            category="pipeline",
            details=f"Pipeline run {run_id} started: {requirement_prompt[:80]}",
            metadata={"run_id": run_id, "prompt": requirement_prompt},
        ))

    def on_agent_start(self, agent_id: str, framework: str, task_title: str) -> None:
        self.emit(PipelineCallbackEvent(
            event_name="AGENT_START",
            category="agent",
            details=f"[{framework.upper()}] {agent_id} began: {task_title}",
            metadata={"agent_id": agent_id, "framework": framework, "task_title": task_title},
        ))

    def on_agent_finish(self, agent_id: str, framework: str, summary: str) -> None:
        self.emit(PipelineCallbackEvent(
            event_name="AGENT_FINISH",
            category="agent",
            details=f"[{framework.upper()}] {agent_id} completed: {summary}",
            metadata={"agent_id": agent_id, "framework": framework, "summary": summary},
        ))

    def on_agent_error(self, agent_id: str, framework: str, error_message: str) -> None:
        self.emit(PipelineCallbackEvent(
            event_name="AGENT_ERROR",
            category="agent",
            details=f"[{framework.upper()}] {agent_id} error: {error_message}",
            metadata={"agent_id": agent_id, "framework": framework, "error": error_message},
        ))

    def on_tool_start(self, tool_name: str, args: Dict[str, Any]) -> None:
        self.emit(PipelineCallbackEvent(
            event_name="TOOL_START",
            category="tool",
            details=f"MCP Tool '{tool_name}' invoked",
            metadata={"tool_name": tool_name, "args": args},
        ))

    def on_tool_end(self, tool_name: str, result_summary: str) -> None:
        self.emit(PipelineCallbackEvent(
            event_name="TOOL_END",
            category="tool",
            details=f"MCP Tool '{tool_name}' returned: {result_summary}",
            metadata={"tool_name": tool_name, "summary": result_summary},
        ))

    def on_guardrail_check(self, rule_name: str, passed: bool, details: str) -> None:
        self.emit(PipelineCallbackEvent(
            event_name="GUARDRAIL_CHECK",
            category="guardrail",
            details=f"Guardrail '{rule_name}' {'PASSED' if passed else 'VIOLATED'}: {details}",
            metadata={"rule_name": rule_name, "passed": passed, "details": details},
        ))

    def on_hitl_event(self, action: str, details: str) -> None:
        self.emit(PipelineCallbackEvent(
            event_name="HITL_EVENT",
            category="hitl",
            details=f"Human Gatekeeper: {action} - {details}",
            metadata={"action": action, "details": details},
        ))

    # --- Internal Bridges ---

    def _on_blackboard_event(self, bb_event: BlackboardEvent) -> None:
        self.emit(PipelineCallbackEvent(
            event_name="BLACKBOARD_UPDATE",
            category="blackboard",
            details=f"Blackboard v{bb_event.state_version} [{bb_event.section}]: {bb_event.details}",
            metadata=bb_event.to_dict(),
        ))

    def _on_a2a_event(self, envelope: A2AEnvelope) -> None:
        self.emit(PipelineCallbackEvent(
            event_name="A2A_ENVELOPE",
            category="a2a",
            details=f"A2A [{envelope.message_type.value}] {envelope.sender_id} -> {envelope.recipient_id}",
            metadata={"message_id": envelope.message_id, "type": envelope.message_type.value},
        ))


# Global Callback Manager
callback_manager = SystemCallbackManager()

