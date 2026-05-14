"""Unit tests for routing functions in src/workflow.py.

Pure logic — no DB, no LLM, no mocks needed.
"""

from langgraph.types import Send

from src.workflow import (
    END,
    route_after_aggregate,
    route_after_interview_schedule,
    route_after_offer_recruiter,
    route_after_recruiter,
    route_after_scorecard,
)


class TestRouteAfterRecruiter:
    def test_rejected_returns_end(self):
        state = {"stage": "rejected", "candidate_id": 1, "candidate_name": "Alice", "approvals": {}, "clock_day": 0}
        result = route_after_recruiter(state)
        assert result is END

    def test_approved_sends_to_all_three_approvals(self):
        state = {"stage": "approvals", "candidate_id": 42, "candidate_name": "Alice", "approvals": {}, "clock_day": 1}
        result = route_after_recruiter(state)
        assert isinstance(result, list)
        assert len(result) == 3
        node_names = {s.node for s in result}
        assert node_names == {"approval_hm", "approval_cfo", "approval_legal"}

    def test_approved_sends_correct_candidate_id(self):
        state = {"stage": "approvals", "candidate_id": 99, "candidate_name": "Bob", "approvals": {}, "clock_day": 0}
        result = route_after_recruiter(state)
        for send in result:
            assert isinstance(send, Send)
            assert send.arg["candidate_id"] == 99


class TestRouteAfterAggregate:
    def test_rejected_returns_end(self):
        assert route_after_aggregate({"stage": "rejected"}) is END

    def test_interview_routes_to_interview_schedule(self):
        assert route_after_aggregate({"stage": "interview"}) == "interview_schedule"

    def test_other_stage_returns_end(self):
        # partial approvals or unexpected stage → END
        assert route_after_aggregate({"stage": "approvals"}) is END
        assert route_after_aggregate({}) is END


class TestRouteAfterInterviewSchedule:
    def test_rejected_returns_end(self):
        assert route_after_interview_schedule({"stage": "rejected"}) is END

    def test_accepted_routes_to_scorecard(self):
        assert route_after_interview_schedule({"stage": "interview"}) == "interview_scorecard"

    def test_any_non_rejected_routes_to_scorecard(self):
        assert route_after_interview_schedule({}) == "interview_scorecard"


class TestRouteAfterScorecard:
    def test_rejected_returns_end(self):
        assert route_after_scorecard({"stage": "rejected"}) is END

    def test_passed_routes_to_offer_generate(self):
        assert route_after_scorecard({"stage": "offer"}) == "offer_generate"

    def test_non_rejected_routes_to_offer_generate(self):
        assert route_after_scorecard({}) == "offer_generate"


class TestRouteAfterOfferRecruiter:
    def test_rejected_returns_end(self):
        assert route_after_offer_recruiter({"stage": "rejected"}) is END

    def test_approved_routes_to_candidate_decision(self):
        assert route_after_offer_recruiter({"stage": "offer"}) == "offer_candidate_decision"

    def test_non_rejected_routes_to_candidate_decision(self):
        assert route_after_offer_recruiter({}) == "offer_candidate_decision"
