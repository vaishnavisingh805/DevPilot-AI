"""Live Gemini Integration Tests for CrewAI and Google ADK.

Verifies:
1. Real CrewAI Crew.kickoff() execution with Gemini.
2. Real Google ADK Runner execution with Gemini.
3. Live A2A message envelope transfer and non-repudiation between frameworks.
4. Shared Blackboard updates from both frameworks.
"""

import os
import pytest
from config.settings import settings
from core.schemas import DeveloperRequirement, RequirementAnalysis, TaskStatus
from core.blackboard import global_blackboard
from core.a2a import global_a2a_bus, A2AMessageType, A2AEnvelope
from agents.crewai import CrewAIPlannerAgent, CrewAIManagerAgent
from agents.google_adk import GoogleADKCoderAgent
from mcp_servers.repo_tool import mcp_repo_client


@pytest.fixture(autouse=True)
def check_gemini_key():
    if not settings.GEMINI_API_KEY:
        pytest.skip("GEMINI_API_KEY is not configured in .env; skipping live API tests.")


def test_real_crewai_planner_kickoff():
    """Verify CrewAI Planner executes real Crew.kickoff() and returns structured RequirementAnalysis."""
    global_blackboard.reset()
    planner = CrewAIPlannerAgent()

    req = DeveloperRequirement(
        raw_prompt="Implement standard_deviation(numbers, sample=False) method in AdvancedCalculator with unit tests."
    )

    plan = planner.plan_requirement(req)

    assert plan is not None
    assert plan.requirement_id == req.id
    assert len(plan.tasks) >= 3

    # Verify real blackboard update
    analysis = global_blackboard.state.analysis
    assert analysis is not None
    assert isinstance(analysis, RequirementAnalysis)
    assert len(analysis.acceptance_criteria) >= 2
    assert analysis.title != ""

    # Verify real token usage was captured from Gemini
    assert planner.last_token_usage is not None
    assert planner.last_token_usage.get("total_tokens", 0) > 0


def test_real_google_adk_runner_code_generation():
    """Verify Google ADK Coder executes real Runner.run() and produces valid code patch."""
    global_blackboard.reset()
    sandbox = mcp_repo_client.create_sandbox("sample_repo")
    run_id = sandbox["run_id"]

    coder = GoogleADKCoderAgent()
    proposal = coder.implement_changes(
        run_id=run_id,
        task_id="TSK-02-CODING",
        instruction="Add standard_deviation(numbers, sample=False) method to AdvancedCalculator.",
        context={"analysis": {"acceptance_criteria": [{"id": "AC-1", "description": "Calculate population and sample std dev"}]}},
    )

    assert proposal is not None
    assert len(proposal.patches) >= 1
    assert "standard_deviation" in proposal.patches[0].modified_content

    # Verify blackboard received proposal
    assert len(global_blackboard.state.working_proposals) >= 1
    assert "src/calculator.py" in global_blackboard.state.active_patches

    # Verify real token usage from ADK Runner
    assert coder.last_token_usage is not None
    assert coder.last_token_usage.get("total_tokens", 0) > 0


def test_real_live_a2a_transfer():
    """Verify A2A message transmission between real CrewAI Manager and Google ADK Coder."""
    global_blackboard.reset()
    global_a2a_bus.clear()

    sandbox = mcp_repo_client.create_sandbox("sample_repo")
    run_id = sandbox["run_id"]

    manager = CrewAIManagerAgent()
    coder = GoogleADKCoderAgent()

    # Dispatch A2A delegation from CrewAI Manager to Google ADK Coder
    envelope_resp = manager.delegate_task_to_adk(
        task_id="TSK-A2A-TEST",
        role="Coder",
        instruction="Add standard_deviation method to calculator",
        run_id=run_id,
        context={"sandbox_path": sandbox["sandbox_path"]},
    )

    assert envelope_resp is not None
    assert envelope_resp.message_type == A2AMessageType.TASK_RESULT
    assert envelope_resp.sender_id == "GoogleADK:CoderAgent"
    assert envelope_resp.recipient_id == "CrewAI:ManagerAgent"
    assert envelope_resp.verify_integrity() is True

    # Verify A2A history contains both request and response envelopes
    history = global_a2a_bus.get_history()
    assert len(history) >= 2
    assert history[0].message_type == A2AMessageType.TASK_DELEGATION
    assert history[1].message_type == A2AMessageType.TASK_RESULT

