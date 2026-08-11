"""The agent graph: planner -> executor -> validator, with a retry edge back
to the executor on a failed validation and a rollback edge once retries are
exhausted.

State is explicit (a TypedDict) and every field is inspectable after a run,
which is the point of building this on LangGraph instead of a bare LLM
call: the control flow (who ran, in what order, with what facts) is the
artifact, not just the final text.
"""

from typing import Literal, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from agent.tools import get_peak_power_unit, get_unit_material, retrieve_context

MODEL = "qwen2.5:7b-instruct-q4_K_M"
OLLAMA_BASE_URL = "http://localhost:11434/v1"
MAX_RETRIES = 2


class AgentState(TypedDict):
    task: str
    plan: str
    facts: dict
    context: list[dict]
    draft: str
    validation: dict
    retries: int
    status: str


def _llm(temperature: float = 0.2) -> ChatOpenAI:
    return ChatOpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama", model=MODEL, temperature=temperature)


def planner(state: AgentState) -> dict:
    prompt = (
        "You are the planning node of an engineering assistant. Given the task below, "
        "write a short numbered plan (3-5 steps) for how to answer it using: a power-trace "
        "lookup tool, a part->material knowledge graph lookup tool, and a datasheet search "
        "tool. Do not answer the task itself, only plan.\n\nTask: " + state["task"]
    )
    response = _llm(temperature=0.0).invoke(prompt)
    return {"plan": response.content}


def executor(state: AgentState) -> dict:
    facts = state.get("facts") or {}
    if not facts:
        peak = get_peak_power_unit()
        material = get_unit_material(peak["unit"])
        facts = {**peak, "material": material}

    context = state.get("context") or retrieve_context(
        f"{facts['material']} thermal resistance package moisture sensitivity junction temperature"
    )

    feedback = ""
    if state.get("validation") and not state["validation"].get("passed", True):
        feedback = (
            "\n\nYour previous draft failed validation for these reasons: "
            + "; ".join(state["validation"]["issues"])
            + ". Fix them in this revision."
        )

    context_block = "\n".join(f"- ({c['source']} p.{c['page']}) {c['text'][:300]}" for c in context)
    prompt = (
        "You are the executor node. Following the plan below, draft a short (4-6 sentence) "
        "thermal-risk summary for the given floorplan unit. You MUST state the unit name and "
        "its material verbatim, report its peak power in watts, and cite at least one "
        "supporting datasheet by its filename in parentheses.\n\n"
        f"Plan:\n{state['plan']}\n\n"
        f"Facts: unit={facts['unit']}, material={facts['material']}, "
        f"peak_power={facts['peak_power']:.2f}W, avg_power={facts['avg_power']:.2f}W\n\n"
        f"Supporting datasheet excerpts:\n{context_block}"
        f"{feedback}"
    )
    response = _llm(temperature=0.2).invoke(prompt)
    return {"facts": facts, "context": context, "draft": response.content}


def validator(state: AgentState) -> dict:
    draft = state["draft"].lower()
    facts = state["facts"]
    issues = []

    if facts["unit"].lower() not in draft:
        issues.append(f"draft does not mention the unit name '{facts['unit']}'")
    if facts["material"].lower() not in draft:
        issues.append(f"draft does not mention the material '{facts['material']}'")
    if not any(c["source"].lower() in draft for c in state["context"]):
        issues.append("draft does not cite any of the retrieved datasheet sources by filename")

    passed = not issues
    retries = state.get("retries", 0)
    return {
        "validation": {"passed": passed, "issues": issues},
        "retries": retries if passed else retries + 1,
    }


def route_after_validation(state: AgentState) -> Literal["retry", "rollback", "approved"]:
    if state["validation"]["passed"]:
        return "approved"
    if state["retries"] > MAX_RETRIES:
        return "rollback"
    return "retry"


def rollback(state: AgentState) -> dict:
    return {
        "status": "failed",
        "draft": (
            "[rolled back after exhausting retries] Unresolved validation issues: "
            + "; ".join(state["validation"]["issues"])
        ),
    }


def approve(state: AgentState) -> dict:
    return {"status": "approved"}


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("planner", planner)
    graph.add_node("executor", executor)
    graph.add_node("validator", validator)
    graph.add_node("rollback", rollback)
    graph.add_node("approve", approve)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "executor")
    graph.add_edge("executor", "validator")
    graph.add_conditional_edges(
        "validator",
        route_after_validation,
        {"retry": "executor", "rollback": "rollback", "approved": "approve"},
    )
    graph.add_edge("rollback", END)
    graph.add_edge("approve", END)

    return graph.compile()
