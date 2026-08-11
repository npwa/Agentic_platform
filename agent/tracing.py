"""Langfuse wiring: load LANGFUSE_* credentials from the repo-root .env and
expose a single CallbackHandler instance for the graph's LLM calls to share.

Requires the self-hosted stack in langfuse/ to be running (see README.md
step 5) and LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY in .env to match the
project langfuse/.env auto-provisioned.
"""

from pathlib import Path

from dotenv import load_dotenv
from langfuse.langchain import CallbackHandler

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

langfuse_handler = CallbackHandler()
