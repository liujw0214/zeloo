"""Batch runner — execute a list of prompts through the agent sequentially.

Reads prompts from a text file (one per line, blank lines skipped) or from
stdin, runs each through a fresh :class:`AIAgent` turn, and writes results
as JSONL to stdout or a file.

Usage::

    python scripts/batch_runner.py --input prompts.txt --output results.jsonl
    echo "hello" | python scripts/batch_runner.py --input -
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

# Allow running from project root without installation
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from run_agent import AIAgent  # noqa: E402


def _load_prompts(input_path: str) -> list[str]:
    """Load prompts from a file path or stdin (``-``)."""
    if input_path == "-":
        return [line.rstrip("\n") for line in sys.stdin if line.strip()]

    path = Path(input_path)
    if not path.exists():
        print(f"Input file not found: {path}", file=sys.stderr)
        sys.exit(1)

    return [
        line.rstrip("\n")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_batch(
    prompts: list[str],
    *,
    model: str = "gpt-4o",
    provider: str = "openai",
    base_url: str | None = None,
    api_key: str | None = None,
    max_iterations: int = 90,
    temperature: float = 0.7,
    sleep_seconds: float = 0.0,
) -> list[dict[str, Any]]:
    """Run *prompts* through the agent and return a list of result records."""
    agent = AIAgent(
        model=model,
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        platform="cli",
        max_iterations=max_iterations,
        temperature=temperature,
    )

    results: list[dict[str, Any]] = []
    try:
        for idx, prompt in enumerate(prompts, start=1):
            start_ts = time.monotonic()
            error: str | None = None
            response_text = ""
            try:
                response_text = agent.run_conversation(prompt)
            except Exception as exc:
                error = str(exc)
                logging.exception("Prompt %d failed", idx)

            elapsed = round(time.monotonic() - start_ts, 3)
            results.append({
                "index": idx,
                "prompt": prompt,
                "response": response_text,
                "error": error,
                "elapsed_seconds": elapsed,
            })

            if sleep_seconds > 0 and idx < len(prompts):
                time.sleep(sleep_seconds)
    finally:
        agent.close()

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run prompts through Zeloo in batch")
    parser.add_argument(
        "--input", "-i", required=True,
        help="Input file (one prompt per line) or '-' for stdin",
    )
    parser.add_argument("--output", "-o", default=None, help="Output JSONL file (default: stdout)")
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--max-iterations", type=int, default=90)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between prompts")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    load_dotenv()
    prompts = _load_prompts(args.input)
    if not prompts:
        print("No prompts to run.", file=sys.stderr)
        return 0

    print(f"Running {len(prompts)} prompt(s)...", file=sys.stderr)
    results = run_batch(
        prompts,
        model=args.model,
        provider=args.provider,
        base_url=args.base_url,
        api_key=args.api_key,
        max_iterations=args.max_iterations,
        temperature=args.temperature,
        sleep_seconds=args.sleep,
    )

    lines = [json.dumps(r, ensure_ascii=False) for r in results]
    output = "\n".join(lines) + "\n"

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"Wrote {len(results)} result(s) to {out_path}", file=sys.stderr)
    else:
        sys.stdout.write(output)

    # Summary
    success = sum(1 for r in results if r["error"] is None)
    print(
        f"Done: {success}/{len(results)} succeeded, "
        f"{len(results) - success} failed",
        file=sys.stderr,
    )
    return 0 if success == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
