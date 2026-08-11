#!/usr/bin/env python3
"""Run the planner -> executor -> validator agent graph on the demo task
and print the resulting state trace.

Usage:
    python -m agent.run
"""

from agent.graph import build_graph

TASK = (
    "Given the ev6 floorplan power trace, identify the functional unit with the "
    "highest peak power draw and draft a short summary of its thermal risk, "
    "grounded in the relevant packaging/datasheet guidance."
)


def main() -> None:
    app = build_graph()
    initial_state = {
        "task": TASK,
        "plan": "",
        "facts": {},
        "context": [],
        "draft": "",
        "validation": {},
        "retries": 0,
        "status": "in_progress",
    }

    final_state = app.invoke(initial_state)

    print("=== plan ===")
    print(final_state["plan"])
    print("\n=== facts ===")
    print(final_state["facts"])
    print("\n=== validation ===")
    print(final_state["validation"], f"(retries used: {final_state['retries']})")
    print("\n=== status ===")
    print(final_state["status"])
    print("\n=== draft ===")
    print(final_state["draft"])


if __name__ == "__main__":
    main()
