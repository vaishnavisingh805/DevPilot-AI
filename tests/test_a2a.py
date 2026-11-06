"""Tests for A2A Protocol and Communication Bus."""

import pytest
from core.a2a import A2AEnvelope, A2AMessageType, A2ABus


def test_a2a_envelope_integrity():
    envelope = A2AEnvelope(
        sender_id="CrewAI:Planner",
        sender_framework="crewai",
        recipient_id="GoogleADK:Coder",
        message_type=A2AMessageType.TASK_DELEGATION,
        payload={"task_id": "TSK-01", "instruction": "Write calculator function"}
    )
    assert envelope.verify_integrity() is True
    # Tampering test
    envelope.payload["instruction"] = "Tampered instruction!"
    assert envelope.verify_integrity() is False


def test_a2a_bus_point_to_point_dispatch():
    bus = A2ABus()

    def adk_coder_handler(msg: A2AEnvelope) -> A2AEnvelope:
        return A2AEnvelope(
            sender_id="GoogleADK:Coder",
            sender_framework="google_adk",
            recipient_id=msg.sender_id,
            correlation_id=msg.message_id,
            message_type=A2AMessageType.TASK_RESULT,
            payload={"status": "code_generated", "file": "src/calculator.py"}
        )

    bus.register_agent("GoogleADK:Coder", adk_coder_handler)

    request = A2AEnvelope(
        sender_id="CrewAI:Planner",
        sender_framework="crewai",
        recipient_id="GoogleADK:Coder",
        message_type=A2AMessageType.TASK_DELEGATION,
        payload={"task": "Implement feature"}
    )

    response = bus.dispatch(request)
    assert response is not None
    assert response.sender_id == "GoogleADK:Coder"
    assert response.correlation_id == request.message_id
    assert response.payload["status"] == "code_generated"
    assert len(bus.get_history()) == 2

