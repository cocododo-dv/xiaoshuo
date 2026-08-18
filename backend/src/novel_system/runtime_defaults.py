from __future__ import annotations


# Long-context local models can legitimately take several minutes, but an
# unlimited read blocks a synchronous worker forever when an upstream accepts
# the connection and never produces a response. Authors may still explicitly
# choose 0 to disable the ceiling for a known local runtime.
DEFAULT_LLM_TIMEOUT_SECONDS = 900.0
