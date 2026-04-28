from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any

ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET = ROOT / "dataset.jsonl"
DEFAULT_OUT_DIR = ROOT / "reports"
RUN_EVAL = ROOT / "run_eval.py"


def _run_eval(
    *,
    base_url: str,
    dataset: Path,
    out_dir: Path,
    loop_enabled: bool,
) -> Dict[str, Any]:
    env = os.environ.copy()
    env["AGENT_ENABLE_OBSERVE_LOOP"] = "1" if loop_enabled else "0"
    label = "loop_on" if loop_enabled else "baseline_loop_off"
    start = time.perf_counter()
    proc = subprocess.run(
        [
            sys.executable,
            str(RUN_EVAL),
            "--base-url",
            base_url,
            "--dataset",
            str(dataset),
            "--out-dir",
            str(out_dir / label),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    report_path = out_dir / label / "latest.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        "label": label,
        "exit_code": proc.returncode,
        "elapsed_ms": elapsed_ms,
        "summary": report.get("summary", {}),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare baseline vs loop eval results.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args(argv)

    dataset = Path(args.dataset).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline = _run_eval(
        base_url=args.base_url,
        dataset=dataset,
        out_dir=out_dir,
        loop_enabled=False,
    )
    loop_on = _run_eval(
        base_url=args.base_url,
        dataset=dataset,
        out_dir=out_dir,
        loop_enabled=True,
    )

    baseline_pass = float(baseline["summary"].get("pass_rate", 0.0))
    loop_pass = float(loop_on["summary"].get("pass_rate", 0.0))
    result = {
        "baseline": baseline,
        "loop_on": loop_on,
        "delta": {
            "pass_rate": loop_pass - baseline_pass,
            "elapsed_ms": int(loop_on["elapsed_ms"]) - int(baseline["elapsed_ms"]),
        },
    }
    output_path = out_dir / "compare_loop_latest.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["delta"], ensure_ascii=False))
    print(f"[eval] comparison report written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
