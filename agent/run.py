#!/usr/bin/env python3
"""Run the planner -> executor -> validator -> human_approval -> write_report
agent graph on the demo task, pausing on the interrupt for a CLI y/n
confirmation before anything is written to disk.

Usage:
    python -m agent.run
"""

import uuid

from langgraph.types import Command

from agent.graph import build_graph

TASK = (
    "Given the ev6 floorplan power trace, identify the functional unit with the "
    "highest peak power draw and draft a short summary of its thermal risk, "
    "grounded in the relevant packaging/datasheet guidance."
)


def print_trace(state: dict) -> None:
    print("=== plan ===")
    print(state["plan"])
    print("\n=== facts ===")
    print(state["facts"])
    print("\n=== validation ===")
    print(state["validation"], f"(retries used: {state['retries']})")
    print("\n=== draft ===")
    print(state["draft"])


def main() -> None:
    app = build_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state = {
        "task": TASK,
        "plan": "",
        "facts": {},
        "context": [],
        "draft": "",
        "validation": {},
        "retries": 0,
        "status": "in_progress",
        "approved": None,
        "report_path": None,
    }

    result = app.invoke(initial_state, config=config)

    if "__interrupt__" in result:
        print_trace(app.get_state(config).values)
        answer = input("\nApprove this draft for writing to disk? [y/N] ").strip().lower()
        result = app.invoke(Command(resume=answer == "y"), config=config)

    print("\n=== status ===")
    print(result["status"])
    if result.get("report_path"):
        print(f"Report written to {result['report_path']}")


if __name__ == "__main__":
    main()
