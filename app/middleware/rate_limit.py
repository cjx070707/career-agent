"""Rate limiting configuration via slowapi.

/chat and /chat/sync are the only LLM-backed endpoints — each call costs
DashScope quota. Limit per IP to prevent a single client from exhausting
the API budget.

Limits (tunable via env):
  - /chat (SSE streaming): 20 req/minute
  - /chat/sync:            20 req/minute
  - everything else:       no limit (static data, DB reads)
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=[])

CHAT_LIMIT = "20/minute"
