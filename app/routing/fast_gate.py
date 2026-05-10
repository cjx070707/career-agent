"""Fast Gate — Tier 1 hard-rule router.

Intercepts pure chitchat/greetings before they enter the full ReAct loop,
saving 3-8s of LLM latency for messages that don't need tool use.

Decision logic:
  - Message length ≤ 15 chars AND matches a chitchat pattern → is_chitchat=True
  - Everything else → is_chitchat=False → proceed to ReAct

Intentionally conservative: false negatives (miss a greeting → goes to ReAct)
are harmless. False positives (treat a career query as chitchat) would be bad,
so the length cap + explicit patterns keep precision high.
"""
import re
from dataclasses import dataclass

# Patterns are anchored full-match; all must be ≤ 15 chars to even be checked.
_CHITCHAT_PATTERNS = [
    # Greetings
    r"(你好|您好|hi|hello|hey|嗨|哈喽|早|晚上好|下午好|早上好)[!！。.~～]*",
    # Thanks
    r"(谢谢|谢了|感谢|多谢|thanks|thank\s*you|thx)[!！。.~～]*",
    # Acknowledgements
    r"(好的|好|ok|okay|嗯|明白|收到|了解|知道了|好哒)[!！。.~～]*",
    # Farewells
    r"(再见|拜拜|bye|goodbye|晚安|先这样)[!！。.~～]*",
    # Filler
    r"(哈哈|哈哈哈|😄|😊|👍|🙏)+",
]

_COMPILED = [re.compile(f"^{p}$", re.IGNORECASE) for p in _CHITCHAT_PATTERNS]

_MAX_CHITCHAT_LEN = 15  # chars; longer messages always go to ReAct


@dataclass
class GateDecision:
    is_chitchat: bool
    reason: str  # for trace logging


def fast_gate(message: str) -> GateDecision:
    """Return GateDecision indicating whether the message is pure chitchat."""
    msg = message.strip()

    if len(msg) > _MAX_CHITCHAT_LEN:
        return GateDecision(is_chitchat=False, reason="too_long")

    for pattern in _COMPILED:
        if pattern.match(msg):
            return GateDecision(is_chitchat=True, reason="chitchat_pattern")

    return GateDecision(is_chitchat=False, reason="no_pattern_match")
