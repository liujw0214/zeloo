"""Zeloo oneshot mode — run agent once, print response, exit."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


def run_oneshot(prompt: str, **kwargs: Any) -> int:
    """Run the agent once with the given prompt and return the response.

    This is a simplified oneshot mode that:
    1. Initializes the agent
    2. Runs a single conversation turn
    3. Prints the response
    4. Exits cleanly

    Args:
        prompt: The user's message/prompt to send to the agent.
        **kwargs: Additional arguments passed to AIAgent.

    Returns:
        0 on success, non-zero on failure.
    """
    if not prompt or not prompt.strip():
        print("Error: No prompt provided for oneshot mode.", file=sys.stderr)
        return 1

    from zeloo_cli.profiles import activate_profile
    from zeloo_cli.config import load_config, load_env_file

    profile = kwargs.pop("profile", None) or "default"
    if profile != "default":
        activate_profile(profile)

    config = load_config()
    env = load_env_file()

    model = kwargs.pop("model", None) or config.get("model", "gpt-4o")
    provider = kwargs.pop("provider", None) or config.get("provider", "openai")
    base_url = kwargs.pop("base_url", None) or env.get("BASE_URL", "") or config.get("base_url", "")
    api_key = kwargs.pop("api_key", None) or env.get("API_KEY", "")
    max_iterations = kwargs.pop("max_iterations", None) or config.get("max_iterations", 10)
    temperature = kwargs.pop("temperature", None) or config.get("temperature", 0.0)

    streaming = os.environ.get("ZELOO_STREAM", "").lower() not in ("0", "false", "no")

    try:
        from run_agent import AIAgent

        agent = AIAgent(
            model=model,
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            max_iterations=max_iterations,
            temperature=temperature,
            platform="cli",
            **kwargs,
        )

        try:
            on_token: Any = None
            if streaming:
                def token_callback(token: str) -> None:
                    print(token, end="", flush=True)
                on_token = token_callback

            response = agent.run_conversation(prompt, on_token=on_token)

            if not streaming:
                print(response)

            if streaming:
                print()

        finally:
            agent.close()

    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0
