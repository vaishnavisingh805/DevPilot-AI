"""Tests for Shared Blackboard Architecture."""

import pytest
from core.blackboard import SharedBlackboard, BlackboardEvent
from core.schemas import DeveloperRequirement, RequirementAnalysis, AcceptanceCriterion


def test_blackboard_initialization():
    bb = SharedBlackboard()
    assert bb.version == 0
    assert bb.state.requirement is None


def test_blackboard_post_requirement_and_event():
    events = []
    bb = SharedBlackboard()
    bb.subscribe(lambda evt: events.append(evt))

    req = DeveloperRequirement(raw_prompt="Implement matrix multiplication")
    bb.post_requirement(req)

    assert bb.version == 1
    assert bb.state.requirement.raw_prompt == "Implement matrix multiplication"
    assert len(events) == 1
    assert events[0].event_type == "REQUIREMENT_POSTED"
    assert events[0].section == "requirement"


def test_blackboard_post_analysis():
    bb = SharedBlackboard()
    analysis = RequirementAnalysis(
        requirement_id="REQ-123",
        title="Matrix Multiplication",
        problem_statement="Need high performance dot products",
        acceptance_criteria=[
            AcceptanceCriterion(id="AC-1", description="Support 2x2 and 3x3 matrices")
        ]
    )
    bb.post_analysis(analysis)
    assert bb.version == 1
    assert bb.state.analysis.title == "Matrix Multiplication"
    assert len(bb.state.analysis.acceptance_criteria) == 1


def test_blackboard_recovery_cycle_increment():
    bb = SharedBlackboard()
    c1 = bb.increment_recovery_cycle()
    c2 = bb.increment_recovery_cycle()
    assert c1 == 1
    assert c2 == 2
    assert bb.state.failure_recovery_cycles == 2

