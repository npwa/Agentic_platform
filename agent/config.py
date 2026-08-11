"""Load agent tunables and prompt templates from the version-controlled
config.yaml, so changing a prompt or a retry/model setting doesn't require
touching graph.py.
"""

from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

with open(_CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)

MODEL = CONFIG["model"]["name"]
OLLAMA_BASE_URL = CONFIG["model"]["ollama_base_url"]
MAX_RETRIES = CONFIG["validator"]["max_retries"]
EMBED_MODEL = CONFIG["retrieval"]["embed_model"]
RETRIEVAL_K = CONFIG["retrieval"]["k"]
PROMPTS = CONFIG["prompts"]
