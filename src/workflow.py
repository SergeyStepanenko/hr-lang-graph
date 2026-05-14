"""LangGraph recruiting workflow with interrupt() for human-in-the-loop."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.constants import Send
from langgraph.graph import END, StateGraph
from langgraph.types import Command

from src import nodes

CHECKPOINT_DB = "data/checkpoints.db"

HUMAN_NODES = {
    "recruiter_review": "recruiter",
    "approval_hm": "hm",
    "approval_cfo": "cfo",
    "approval_legal": "legal",
    "interview_schedule": "candidate",
    "interview_scorecard": "interviewer",
    "offer_recruiter_review": "recruiter",
    "offer_candidate_decision": "candidate",
}


class RecruitingState(TypedDict, total=False):
    candidate_id: int
    job_id: int
    cv_text: str
    stage: str
    candidate_name: str
    candidate_email: str | None
    no_contact: bool
    score: dict
    summary: str
    approvals: dict[str, str]
    approval_results: Annotated[list[dict], operator.add]
    interview: str
    interview_score: str
    offer_text: str
    clock_day: int
    last_action_day: int


def route_after_recruiter(state: RecruitingState) -> list[Send] | str:
    if state.get("stage") == "rejected":
        return END
    return [
        Send("approval_hm", {
            "candidate_id": state["candidate_id"],
            "candidate_name": state.get("candidate_name", ""),
            "approvals": state.get("approvals", {}),
            "clock_day": state.get("clock_day", 0),
        }),
        Send("approval_cfo", {
            "candidate_id": state["candidate_id"],
            "candidate_name": state.get("candidate_name", ""),
            "approvals": state.get("approvals", {}),
            "clock_day": state.get("clock_day", 0),
        }),
        Send("approval_legal", {
            "candidate_id": state["candidate_id"],
            "candidate_name": state.get("candidate_name", ""),
            "approvals": state.get("approvals", {}),
            "clock_day": state.get("clock_day", 0),
        }),
    ]


def route_after_aggregate(state: RecruitingState) -> str:
    if state.get("stage") == "rejected":
        return END
    if state.get("stage") == "interview":
        return "interview_schedule"
    return END


def route_after_interview_schedule(state: RecruitingState) -> str:
    if state.get("stage") == "rejected":
        return END
    return "interview_scorecard"


def route_after_scorecard(state: RecruitingState) -> str:
    if state.get("stage") == "rejected":
        return END
    return "offer_generate"


def route_after_offer_recruiter(state: RecruitingState) -> str:
    if state.get("stage") == "rejected":
        return END
    return "offer_candidate_decision"


def build_graph() -> StateGraph:
    builder = StateGraph(RecruitingState)

    builder.add_node("intake", nodes.intake)
    builder.add_node("score_cv", nodes.score_cv)
    builder.add_node("recruiter_review", nodes.recruiter_review)
    builder.add_node("approval_hm", nodes.approval_hm)
    builder.add_node("approval_cfo", nodes.approval_cfo)
    builder.add_node("approval_legal", nodes.approval_legal)
    builder.add_node("aggregate_approvals", nodes.aggregate_approvals)
    builder.add_node("interview_schedule", nodes.interview_schedule)
    builder.add_node("interview_scorecard", nodes.interview_scorecard)
    builder.add_node("offer_generate", nodes.offer_generate)
    builder.add_node("offer_recruiter_review", nodes.offer_recruiter_review)
    builder.add_node("offer_candidate_decision", nodes.offer_candidate_decision)

    builder.set_entry_point("intake")
    builder.add_edge("intake", "score_cv")
    builder.add_edge("score_cv", "recruiter_review")

    builder.add_conditional_edges("recruiter_review", route_after_recruiter,
                                  ["approval_hm", "approval_cfo", "approval_legal"])

    builder.add_edge("approval_hm", "aggregate_approvals")
    builder.add_edge("approval_cfo", "aggregate_approvals")
    builder.add_edge("approval_legal", "aggregate_approvals")

    builder.add_conditional_edges("aggregate_approvals", route_after_aggregate,
                                  {"interview_schedule": "interview_schedule", END: END})
    builder.add_conditional_edges("interview_schedule", route_after_interview_schedule,
                                  {"interview_scorecard": "interview_scorecard", END: END})
    builder.add_conditional_edges("interview_scorecard", route_after_scorecard,
                                  {"offer_generate": "offer_generate", END: END})
    builder.add_edge("offer_generate", "offer_recruiter_review")
    builder.add_conditional_edges("offer_recruiter_review", route_after_offer_recruiter,
                                  {"offer_candidate_decision": "offer_candidate_decision", END: END})
    builder.add_edge("offer_candidate_decision", END)

    return builder


_checkpointer = None
_compiled = None


def get_checkpointer() -> SqliteSaver:
    global _checkpointer
    if _checkpointer is None:
        import sqlite3
        from pathlib import Path

        path = Path(CHECKPOINT_DB)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
        _checkpointer = SqliteSaver(conn)
    return _checkpointer


def get_graph():
    global _compiled
    if _compiled is None:
        builder = build_graph()
        _compiled = builder.compile(checkpointer=get_checkpointer())
    return _compiled


def create_studio_graph():
    """Entry point for LangGraph Studio (langgraph dev). Uses in-memory checkpointer."""
    from langgraph.checkpoint.memory import MemorySaver
    return build_graph().compile(checkpointer=MemorySaver())


def start_workflow(candidate_id: int, job_id: int, cv_text: str, thread_id: str) -> dict:
    graph = get_graph()
    config = {
        "configurable": {"thread_id": thread_id},
        "run_name": f"CV Submit — candidate #{candidate_id}",
        "metadata": {"candidate_id": candidate_id, "job_id": job_id, "thread_id": thread_id},
    }
    initial = RecruitingState(
        candidate_id=candidate_id,
        job_id=job_id,
        cv_text=cv_text,
        stage="intake",
        clock_day=0,
    )
    result = graph.invoke(initial, config=config)
    return result


def resume_workflow(
    thread_id: str,
    decision: str,
    comment: str = "",
    resume_map: dict | None = None,
    node_name: str = "action",
    candidate_name: str = "",
) -> dict:
    """Resume workflow after interrupt.

    For single interrupt: pass decision + comment.
    For multiple interrupts: pass resume_map {interrupt_id: {decision, comment}}.
    """
    graph = get_graph()

    label = candidate_name or thread_id[:8]
    config = {
        "configurable": {"thread_id": thread_id},
        "run_name": f"{label} — {node_name}: {decision}",
        "metadata": {"thread_id": thread_id, "decision": decision, "node": node_name},
    }

    if resume_map:
        result = graph.invoke(Command(resume=resume_map), config=config)
    else:
        result = graph.invoke(Command(resume={"decision": decision, "comment": comment}), config=config)

    return result


def get_workflow_state(thread_id: str) -> dict | None:
    graph = get_graph()
    config = {"configurable": {"thread_id": thread_id}}
    try:
        snapshot = graph.get_state(config)
        if snapshot and snapshot.values:
            pending = []
            interrupts = []

            if snapshot.tasks:
                for t in snapshot.tasks:
                    if hasattr(t, "interrupts") and t.interrupts:
                        pending.append(t.name)
                        for intr in t.interrupts:
                            interrupts.append({
                                "id": intr.id if hasattr(intr, "id") else None,
                                "value": intr.value if hasattr(intr, "value") else None,
                                "node": t.name,
                            })
                    elif hasattr(t, "name") and t.name:
                        if not any(i["node"] == t.name for i in interrupts):
                            pending.append(t.name)

            # Filter out approval interrupts already recorded in approval_results
            completed_approvers = {
                r["approver"] for r in snapshot.values.get("approval_results", [])
            }
            interrupts = [
                i for i in interrupts
                if not (
                    i["node"].startswith("approval_")
                    and i["node"].replace("approval_", "") in completed_approvers
                )
            ]
            pending = [
                p for p in pending
                if not (
                    p.startswith("approval_")
                    and p.replace("approval_", "") in completed_approvers
                )
            ]

            if not pending and snapshot.next:
                pending = list(snapshot.next)

            return {
                "values": snapshot.values,
                "next": pending,
                "interrupts": interrupts,
            }
    except Exception:
        pass
    return None
