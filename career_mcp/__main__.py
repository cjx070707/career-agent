"""Run stdio MCP server. Requires Python >= 3.10 and `pip install mcp`.

Usage (from repository root so `app` resolves):

    python3.11 -m career_mcp

Cursor MCP config example (see README MCP section).
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from career_mcp.server import build_mcp

    build_mcp().run(transport="stdio")


if __name__ == "__main__":
    main()
