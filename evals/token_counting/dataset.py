"""Standard evaluation prompt datasets for token counting benchmarks."""

from __future__ import annotations


def load_eval_prompts(name: str = "default") -> list[dict]:
    """Load standard evaluation prompt datasets.

    Available datasets:
    - default: Mixed prompts (short/medium/long)
    - short: Under 500 tokens
    - long_context: 50K+ tokens (context overflow test)
    """
    prompts: dict[str, list[dict]] = {
        "default": [
            {"role": "user", "content": "Hello, how are you?"},
            {
                "role": "user",
                "content": "Explain the difference between a stack and a queue.",
            },
            {
                "role": "system",
                "content": "You are a helpful assistant.",
            },
            {
                "role": "user",
                "content": "Write a Python function to check if a string is a palindrome.",
            },
        ],
        "short": [
            {"role": "user", "content": "Hi"},
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
            {"role": "user", "content": "Thanks!"},
        ],
        "long_context": [
            {
                "role": "user",
                "content": "Summarize this document: " + ("Lorem ipsum " * 10000),
            },
        ],
    }
    return prompts.get(name, prompts["default"])
