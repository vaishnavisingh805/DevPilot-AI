"""Unit tests for Phase 1 Pydantic Schemas."""

import pytest
from core.schemas import (
    DeveloperRequirement,
    RequirementAnalysis,
    AcceptanceCriterion,
    ExecutionPlan,
    TaskItem,
    TaskFramework,
    TaskStatus,
    CodeChangeProposal,
    FilePatch,
    TestResultReport,
    TestResultItem,
    SecurityAuditReport,
    ProvenanceRecord,
)


def test_developer_requirement_validation():
    req = DeveloperRequirement(
        raw_prompt="Add standard_deviation function to AdvancedCalculator with full unit tests"
    )
    assert req.id.startswith("REQ-")
    assert "standard_deviation" in req.raw_prompt


def test_requirement_analysis_structure():
    ac = AcceptanceCriterion(
        id="AC-1",
        description="standard_deviation returns correct population std dev for [2, 4, 4, 4, 5, 5, 7, 9]"
    )
    analysis = RequirementAnalysis(
        requirement_id="REQ-001",
        title="Implement Standard Deviation",
        problem_statement="Calculator lacks dispersion metrics",
        acceptance_criteria=[ac]
    )
    assert analysis.requirement_id == "REQ-001"
    assert len(analysis.acceptance_criteria) == 1
    assert analysis.acceptance_criteria[0].id == "AC-1"


def test_execution_plan_framework_assignment():
    task1 = TaskItem(
        id="TSK-1",
        title="Plan Architecture",
        description="Breakdown requirement into subtasks",
        assigned_framework=TaskFramework.CREWAI,
        assigned_role="Planner"
    )
    task2 = TaskItem(
        id="TSK-2",
        title="Generate Implementation",
        description="Write standard_deviation method",
        assigned_framework=TaskFramework.GOOGLE_ADK,
        assigned_role="Coder",
        dependencies=["TSK-1"]
    )
    plan = ExecutionPlan(
        requirement_id="REQ-001",
        strategy_summary="Sequential implementation with test validation",
        tasks=[task1, task2]
    )
    assert len(plan.tasks) == 2
    assert plan.tasks[0].assigned_framework == TaskFramework.CREWAI
    assert plan.tasks[1].assigned_framework == TaskFramework.GOOGLE_ADK


def test_code_change_proposal_and_patch():
    patch = FilePatch(
        file_path="src/calculator.py",
        modified_content="def standard_deviation(): pass",
        justification="Implements standard deviation feature"
    )
    proposal = CodeChangeProposal(
        task_id="TSK-2",
        author_agent="Google-ADK-CoderAgent",
        patches=[patch]
    )
    assert proposal.proposal_id.startswith("CCP-")
    assert len(proposal.patches) == 1


def test_provenance_cryptographic_hash():
    record = ProvenanceRecord(
        step_id="STEP-1",
        parent_step_id=None,
        agent_id="CrewAI-Planner",
        framework="crewai",
        action_type="plan",
        input_payload_hash="abc123hash",
        output_payload_hash="def456hash",
        state_version=1
    )
    record.record_hash = record.compute_hash()
    assert len(record.record_hash) == 64  # SHA-256 hex digest length

