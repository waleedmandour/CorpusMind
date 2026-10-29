"""Transient-failure retry for model-provider HTTP calls (v2.0.1).

Fixes the recurring user reports of an intermittent
"HTTP 502: Model call failed" on the AI assistant chat: a single dropped
connection — Ollama restarting under RAM pressure, LM Studio recycling
keep-alive sockets, a cloud gateway blip (502/503/429) — used to surface as
a hard 502 with no recovery, even though the very next attempt usually
succeeds.

Policy, following published practice for LLM/API clients:

- **Retry only transient failures** (OpenAI & Anthropic SDK retry semantics,
  https://github.com/openai/openai-python#retries): transport-level errors
  (connect/reset/read/write) and HTTP 408/425/429/500/502/503/504/529.
  Never 4xx client errors — 400/401/403/404/422 are deterministic and
  retrying them only delays the actionable message.
- **Exponential backoff with full jitter** (AWS Builders' Library,
  "Exponential Backoff and Jitter", 2015): wait drawn uniformly from
  [0, min(8s, 0.5s · 2^(attempt-1))]. Full jitter avoids the thundering
  herd when several classroom clients retry against one Ollama box.
- **Honor Retry-After** when the server sends one (429/503), capped at 15s
  so an advisory header cannot eat the chat turn's deadline.
- **3 attempts total.** Every chat completion POST is idempotent at the
  provider (no partial server-side writes), so replay is safe; the engine's
  overall chat deadline (CORPUSMIND_CHAT_TIMEOUT_S, default 180s) still
  bounds the whole turn.
- **Streaming: retry the connect/headers phase only.** Once a completion has
  started emitting tokens, a dropped connection is NOT retried — replaying
  would duplicate output the user already saw.
- Every retry logs a structured ``provider_retry`` warning (attempt, error,
  next wait) so the posterior in the logs matches the user experience.

Contract: the helpers RETURN the final ``httpx.Response`` whatever its
status (or re-raise the last transport error after the budget is spent), so
every caller keeps its existing ``raise_for_status()`` / status-code checks
and error-message shape untouched.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

import httpx

from app.logging import get_logger

log = get_logger(__name__)

# HTTP statuses worth one more attempt: request timeout (408), early-hints/
# tokens-exhausted variants (425), rate limit (429), and the gateway/
# overloaded family (500/502/503/504, Cloudflare 529).
RETRYABLE_STATUS: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504, 529})

_ATTEMPTS = 3
_INITIAL_WAIT_S = 0.5
_MAX_WAIT_S = 8.0
_RETRY_AFTER_CAP_S = 15.0

Sleep = Callable[[float], Awaitable[None]]


def _retry_after_s(response: httpx.Response) -> float | None:
    """Parse a Retry-After header (delay-seconds form only; the HTTP-date
    form is rare on model gateways and not worth a date parser here)."""
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw.strip()))
    except ValueError:
        return None


def next_wait_s(attempt: int, retry_after: float | None) -> float:
    """Wait before retrying `attempt` (1-based): full-jitter exponential,
    or the server's Retry-After (capped) when provided."""
    if retry_after is not None:
        return min(retry_after, _RETRY_AFTER_CAP_S)
    ceiling = min(_MAX_WAIT_S, _INITIAL_WAIT_S * (2 ** (attempt - 1)))
    return random.uniform(0.0, ceiling)


async def _resilient_send(
    send: Callable[[], Awaitable[httpx.Response]],
    *,
    label: str,
    attempts: int = _ATTEMPTS,
    sleep: Sleep = asyncio.sleep,
    discard_response: Callable[[httpx.Response], Awaitable[None]] | None = None,
) -> httpx.Response:
    """Drive `send` with the transient-retry policy above.

    `discard_response` is called on responses that are about to be retried
    away (streaming responses must be closed before a new attempt opens
    another); for plain posts it is None and error bodies are simply dropped.
    """
    for attempt in range(1, attempts + 1):
        try:
            r = await send()
        except httpx.TransportError as e:
            if attempt == attempts:
                raise  # caller's existing except httpx.HTTPError wraps it
            wait = next_wait_s(attempt, None)
            log.warning(
                "provider_retry",
                label=label,
                attempt=attempt,
                error=f"{type(e).__name__}: {e}",
                next_wait_s=round(wait, 2),
            )
            await sleep(wait)
            continue
        if r.status_code in RETRYABLE_STATUS and attempt < attempts:
            if discard_response is not None:
                await discard_response(r)
            wait = next_wait_s(attempt, _retry_after_s(r))
            log.warning(
                "provider_retry",
                label=label,
                attempt=attempt,
                status=r.status_code,
                next_wait_s=round(wait, 2),
            )
            await sleep(wait)
            continue
        return r
    raise AssertionError("unreachable: retry loop returns or raises")  # pragma: no cover


async def post_with_resilience(
    client: httpx.AsyncClient,
    path: str,
    *,
    json: object | None = None,
    timeout: float | None = None,
    label: str = "post",
    attempts: int = _ATTEMPTS,
    sleep: Sleep = asyncio.sleep,
) -> httpx.Response:
    """POST with the transient-retry policy. Returns the final response
    (any status); re-raises the last transport error once the budget is
    spent, preserving every caller's existing error contract."""
    return await _resilient_send(
        lambda: client.post(path, json=json, timeout=timeout),
        label=label,
        attempts=attempts,
        sleep=sleep,
    )


async def stream_with_resilience(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    json: object | None = None,
    timeout: float | None = None,
    label: str = "stream",
    attempts: int = _ATTEMPTS,
    sleep: Sleep = asyncio.sleep,
) -> httpx.Response:
    """Open a streaming response with the transient-retry policy applied to
    the connect/headers phase ONLY (never mid-stream — see module docstring).
    The caller owns the returned streaming response and must close it."""
    request = client.build_request(method, path, json=json, timeout=timeout)

    async def _open() -> httpx.Response:
        return await client.send(request, stream=True)

    async def _discard(r: httpx.Response) -> None:
        await r.aclose()

    return await _resilient_send(
        _open,
        label=label,
        attempts=attempts,
        sleep=sleep,
        discard_response=_discard,
    )
