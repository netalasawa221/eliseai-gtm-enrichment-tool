"""Anthropic Claude API wrapper.

Thin wrapper around the Anthropic Python SDK. All prompt construction happens
in core/email_generator.py — this module is only responsible for the API call,
error handling, and returning a consistent response dict.

Typical usage:
    from clients.llm_client import complete

    result = complete(system="You are a helpful assistant.", user="Say hello.")
    if result["success"]:
        print(result["text"])
    else:
        print(result["error"])
"""

import anthropic
import config


# Lazily initialised on first call; reused across all subsequent calls.
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def complete(
    system: str,
    user: str,
    max_tokens: int = 1024,
) -> dict:
    """Call Claude with a system prompt and a user prompt.

    Args:
        system:     System prompt that sets Claude's role and constraints.
        user:       The specific request to fulfill.
        max_tokens: Maximum tokens in the response (default 1024).

    Returns:
        Always returns a dict — never raises.

        On success:
            {
                "text": "Claude's response as a plain string",
                "success": True,
                "error": None,
                "tokens_used": 543
            }

        On failure (network, auth, rate limit, etc.):
            {
                "text": None,
                "success": False,
                "error": "human-readable description",
                "tokens_used": 0
            }
    """
    try:
        client = _get_client()
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text: str = response.content[0].text
        tokens_used: int = response.usage.input_tokens + response.usage.output_tokens
        return {
            "text": text,
            "success": True,
            "error": None,
            "tokens_used": tokens_used,
        }

    except anthropic.AuthenticationError:
        return _error("Anthropic authentication failed — check ANTHROPIC_API_KEY in .env")

    except anthropic.RateLimitError:
        return _error("Anthropic rate limit reached — try again later")

    except anthropic.APIConnectionError as exc:
        return _error(f"Anthropic connection error: {exc}")

    except anthropic.APIStatusError as exc:
        return _error(f"Anthropic API error {exc.status_code}: {exc.message}")

    except anthropic.APIError as exc:
        return _error(f"Anthropic API error: {exc}")


def _error(message: str) -> dict:
    return {"text": None, "success": False, "error": message, "tokens_used": 0}


if __name__ == "__main__":
    print("Testing llm_client.complete() with a simple prompt...")
    result = complete(
        system="You are a helpful assistant. Be brief.",
        user="Say hello in exactly one sentence.",
        max_tokens=64,
    )
    print(f"  Success:      {result['success']}")
    if result["success"]:
        print(f"  Response:     {result['text']}")
        print(f"  Tokens used:  {result['tokens_used']}")
    else:
        print(f"  Error:        {result['error']}")
