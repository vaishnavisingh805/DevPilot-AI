"""Unit tests for Phase 2 CrewAI and Google ADK Agent integrations."""

import pytest
from core.schemas import DeveloperRequirement, TaskStatus
from core.blackboard import global_blackboard
from core.a2a import global_a2a_bus, A2AMessageType
from agents.crewai import CrewAIPlannerAgent, CrewAIManagerAgent, CrewAIAuditorAgent
from agents.google_adk import GoogleADKCoderAgent, GoogleADKTestGeneratorAgent, GoogleADKDebuggerAgent
from mcp_servers.repo_tool import mcp_repo_client


def test_crewai_planner_agent_plans_requirement():
    global_blackboard.reset()
    planner = CrewAIPlannerAgent()

    req = DeveloperRequirement(
        raw_prompt="Add standard_deviation to AdvancedCalculator with tests"
    )
    plan = planner.plan_requirement(req)

    assert plan is not None
    assert plan.requirement_id == req.id
    assert len(plan.tasks) >= 3
    assert global_blackboard.state.analysis is not None
    title_lower = global_blackboard.state.analysis.title.lower()
    assert "standard" in title_lower and ("deviation" in title_lower or "calculator" in title_lower)


def test_google_adk_coder_and_test_generator_via_a2a():
    global_blackboard.reset()
    # 1. Setup isolated sandbox
    sandbox_res = mcp_repo_client.create_sandbox("sample_repo")
    run_id = sandbox_res["run_id"]
    sandbox_path = sandbox_res["sandbox_path"]

    # 2. Instantiate agents
    planner = CrewAIPlannerAgent()
    manager = CrewAIManagerAgent()
    coder = GoogleADKCoderAgent()
    tester = GoogleADKTestGeneratorAgent()

    # 3. Manager delegates coding to Google ADK via A2A
    code_envelope = manager.delegate_task_to_adk(
        task_id="TSK-02-CODING",
        role="Coder",
        instruction="Implement standard_deviation",
        run_id=run_id,
        context={"sandbox_path": sandbox_path},
    )

    assert code_envelope is not None
    assert code_envelope.message_type == A2AMessageType.TASK_RESULT
    assert code_envelope.payload["status"] == "completed"

    # Verify Blackboard received the proposal
    assert len(global_blackboard.state.working_proposals) >= 1
    assert "src/calculator.py" in global_blackboard.state.active_patches

    # 4. Manager delegates testing to Google ADK via A2A
    test_envelope = manager.delegate_task_to_adk(
        task_id="TSK-03-TESTING",
        role="TestGenerator",
        instruction="Synthesize test suite and run pytest",
        run_id=run_id,
        context={"sandbox_path": sandbox_path},
    )

    assert test_envelope is not None
    assert test_envelope.payload["all_passed"] is True
    assert test_envelope.payload["passed"] >= 8  # 5 original + new standard deviation tests!

    # Verify Blackboard received test report
    assert len(global_blackboard.state.test_reports) >= 1
    assert global_blackboard.state.test_reports[-1].all_passed is True


def test_crewai_auditor_prepares_delivery():
    auditor = CrewAIAuditorAgent()
    delivery = auditor.audit_and_prepare_delivery()

    assert delivery is not None
    assert delivery.human_approved is False
    assert len(delivery.patches) >= 1
    assert global_blackboard.state.final_delivery is not None

