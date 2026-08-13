# Agentic Platform Proof of Concept – Purpose Summary

This repository is a constrained proof-of-concept of an agentic AI
system: a graph-based orchestration with explicit state and control
flow, human-in-the-loop boundaries, observability, evaluation gates,
and configuration treated as code.

The domain is semiconductor packaging and thermal analysis. Public
data is ingested into a dual semantic layer. PDFs are chunked,
embedded with a local model, and stored in a persistent Chroma
collection. Structured relationships (floorplan parts → materials →
simulation runs) are captured as nodes and relationships in a managed
Neo4j Aura Free graph database, written via idempotent `MERGE`
ingestion. Deterministic tools query these stores so that every fact
the agent uses is computed.

The core runtime is a LangGraph StateGraph whose nodes implement a
classic planner → executor → validator loop. State is an explicit
TypedDict that records the task, plan, retrieved facts, context
snippets, draft text, validation results, retry count, approval
decision, and final report path. Conditional edges enforce branching:
a failed validation either retries the executor (up to a configurable
limit) or rolls back to a failed terminal state. After successful
validation an interrupt node pauses execution and requires an explicit
human yes/no decision before any side-effect—writing a dated Markdown
report to disk—can occur. This realizes the “clear autonomy boundaries
and human-in-the-loop controls” preferred qualification.

Observability will be provided by a self-hosted Langfuse stack
(docker-compose) that captures every LLM call, tool invocation, and
latency/cost signal as a single trace. Prompt templates, model name,
retry limits, and retrieval parameters live in a version-controlled
YAML file so that changes are auditable and do not require code
edits. A GitHub Actions workflow is planned with a deterministic
pytest suite on every push; the tests exercise peak-power extraction,
graph lookups, validator logic, routing branches, and report writing
without needing a live model or external services. This will supply a
minimal but real continuous-evaluation gate.

Hardware constraints (10 GB VRAM) force the use of a quantized 7B
model via Ollama. I had to accept that generation quality is not the
strongest link and therefore invested in control flow, data plumbing,
observability, and regression gates instead. The result is a runnable
local platform that illustrates how agentic systems can be made
reliable, inspectable, and governable.

The project remains marked work-in-progress; setup instructions are
still incomplete and multi-agent coordination, production CI/CD for
agent configurations, and enterprise integration patterns are left for
future iteration. Even in its current form it furnishes concrete,
inspectable evidence of the architectural patterns an enterprise
agentic platform needs.
