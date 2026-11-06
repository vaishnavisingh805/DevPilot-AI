"""CrewAI Manager Agent.

Coordinates task execution across agent frameworks using the A2A Protocol,
inspecting blackboard state, and routing tasks to Google ADK workers.
"""

from typing import Dict, Any, Optional
from crewai import Agent

from config.settings import settings
from config.models_config import get_llm_for_crewai
from core.schemas import TaskStatus, TaskFramework
from core.a2a import A2AEnvelope, A2AMessageType, global_a2a_bus
from core.blackboard import global_blackboard


class CrewAIManagerAgent:
    """CrewAI-powered Manager / Orchestration Agent."""

    def __init__(self, model_name: Optional[str] = None):
        self.agent_id = "CrewAI:ManagerAgent"
        self.framework = "crewai"
        self.model_name = model_name or settings.DEFAULT_MODEL
        self.llm = get_llm_for_crewai(self.model_name)

        self.crewai_agent = Agent(
            role="Engineering Manager & Multi-Agent Dispatcher",
            goal="Coordinate specialized agent execution, monitor blackboard state, and enforce protocol compliance.",
            backstory=(
                "You are an Engineering Manager who oversees autonomous software engineering teams. "
                "You dispatch work to Google ADK specialist agents via the A2A protocol and ensure "
                "continuous progress on the shared blackboard."
            ),
            llm=self.llm,
            verbose=False,
            allow_delegation=False,
        )

        global_a2a_bus.register_agent(self.agent_id, self.handle_a2a_message)

    def handle_a2a_message(self, envelope: A2AEnvelope) -> Optional[A2AEnvelope]:
        """Handles incoming A2A messages from Google ADK workers."""
        if envelope.message_type == A2AMessageType.TASK_RESULT:
            task_id = envelope.payload.get("task_id")
            status = envelope.payload.get("status", "completed")
            summary = envelope.payload.get("summary", "Task executed successfully")
            if task_id:
                global_blackboard.update_task_status(
                    task_id=task_id,
                    status=TaskStatus.COMPLETED if status == "completed" else TaskStatus.FAILED,
                    output_summary=summary,
                )
        return None

    def delegate_task_to_adk(
        self,
        task_id: str,
        role: str,
        instruction: str,
        run_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[A2AEnvelope]:
        """Dispatches an A2A task delegation envelope to Google ADK agent."""
        recipient_id = f"GoogleADK:{role}Agent"
        envelope = A2AEnvelope(
            sender_id=self.agent_id,
            sender_framework=self.framework,
            recipient_id=recipient_id,
            recipient_framework="google_adk",
            message_type=A2AMessageType.TASK_DELEGATION,
            payload={
                "task_id": task_id,
                "role": role,
                "instruction": instruction,
                "run_id": run_id,
                "context": context or {},
            },
        )
        global_blackboard.update_task_status(
            task_id=task_id,
            status=TaskStatus.IN_PROGRESS,
            output_summary=f"Delegated to {recipient_id} via A2A protocol",
        )
        return global_a2a_bus.dispatch(envelope)
