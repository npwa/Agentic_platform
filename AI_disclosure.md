## AI-Assistance Disclosure

I used Claude (chat) and Claude Code throughout this project: for architecting the
semantic layer and agent graph, scaffolding the ingestion scripts, implementing the
LangGraph planner-executor-validator loop, and reviewing the README and this repo's
structure before pushing. I would not have gotten a working agentic pipeline — vector
store, knowledge graph, and a real branching state machine — running on local hardware in
this timeframe without it.

That didn't make this a hands-off exercise. I've spent years designing, installing, and
supporting DevOps systems and infrastructure for engineering organizations of up to 70
people — training teams on process, documenting it, and leading smaller groups through
execution. That background is exactly what I leaned on here: working around network and
site-access constraints, deciding what does and doesn't belong in a public repo, and not
taking a tool's self-report of its own work at face value.

Concretely, I didn't just accept Claude Code's summary that the retry and rollback
branches were "verified end to end" — I read `tools.py`, `graph.py`, and `run.py` myself,
ran the graph directly, and then deliberately broke validation to force the retry path and
exhausted the retry budget to force rollback, rather than trusting that a past run
happened to exercise them. I also checked what was committed in git versus what was
described — confirming through the pushed repo itself that `.gitignore` was doing its job
on the private PDFs and generated artifacts. Some files that were only referenced as their
license did not explicitly permit redistribution.

I also treat the design as a work in progress, not a finished claim. The planner currently
produces a real plan via the LLM, but the executor doesn't yet branch on it — it runs a
fixed tool sequence regardless of what the plan says. That's a simplification, not an
oversight, it's the next thing I intend to fix: having the executor actually parse and act
on the plan's steps.

I see this the same way I've seen every prior generation of engineering tooling: a tool
that makes me faster and catches more, not a replacement for judgment about what's
correct, what's safe to ship, and what's still a gap. Using every available tool to
design, verify, and document a working system isn't a shortcut — it's the job.
