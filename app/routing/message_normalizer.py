from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedMessage:
    raw: str
    lowered: str
    stripped: str
    collapsed: str


def normalize_message(message: str) -> NormalizedMessage:
    stripped = message.strip()
    lowered = stripped.lower()
    collapsed = lowered.replace(" ", "")
    return NormalizedMessage(
        raw=message,
        lowered=lowered,
        stripped=stripped,
        collapsed=collapsed,
    )
