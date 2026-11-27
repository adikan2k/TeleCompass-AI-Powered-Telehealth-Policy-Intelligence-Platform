"""The only module that calls a model (D9).

Every call goes through ModelGate, which:
- refuses the call if the run's spend, read from the database, could pass the cap (rule 20);
- writes one `model_call` row with tokens and cost (rule 21);
- traces the call in Langfuse (rule 20).

A failed call is recorded and returned as a failure. It is never retried silently.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel

from telecompass import config
from telecompass.db import Connection
from telecompass.fetch import utc_now

EXTRACTION_MODEL = "gpt-6.2-sol"
BULK_MODEL = "gpt-6-luna"
MAX_OUTPUT_TOKENS = 16_000
CHARS_PER_TOKEN_FLOOR = 3  # a cautious guess used only to reserve budget before a call


@dataclass(frozen=True)
class Price:
    """US dollars per one million tokens."""

    input: Decimal
    cached: Decimal
    cache_write: Decimal
    output: Decimal


# From OpenAI's pricing page, checked 2026-11-26. Standard (not batch) rates.
PRICES = {
    EXTRACTION_MODEL: Price(Decimal("2.00"), Decimal("0.10"), Decimal("2.50"), Decimal("10.00")),
    BULK_MODEL: Price(Decimal("0.10"), Decimal("0.01"), Decimal("0.125"), Decimal("0.50")),
}
# Prompts above this many input tokens are billed at 2x input and 1.5x output.
LONG_PROMPT_TOKENS = 272_000
MILLION = Decimal(1_000_000)


class Usage(BaseModel):
    input_tokens: int = 0  # all input tokens, including cached and cache-write ones
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0  # includes reasoning tokens


@dataclass
class ModelReply:
    parsed: BaseModel | None
    usage: Usage
    failure: str | None = None
    response_id: str | None = None


class CostCapReached(RuntimeError):
    """The next call could take the run past its cap, so it was not made."""


def cost_usd(model: str, usage: Usage) -> Decimal:
    """What a call cost, from the price table. An unknown model is an error, not zero."""
    price = PRICES[model]
    long_prompt = usage.input_tokens > LONG_PROMPT_TOKENS
    input_factor = Decimal(2) if long_prompt else Decimal(1)
    output_factor = Decimal("1.5") if long_prompt else Decimal(1)
    plain = max(usage.input_tokens - usage.cached_tokens - usage.cache_write_tokens, 0)
    input_cost = (
        plain * price.input
        + usage.cached_tokens * price.cached
        + usage.cache_write_tokens * price.cache_write
    ) * input_factor
    output_cost = usage.output_tokens * price.output * output_factor
    return ((input_cost + output_cost) / MILLION).quantize(Decimal("0.000001"))


def worst_case_cost(model: str, prompt_chars: int, max_output_tokens: int) -> Decimal:
    """An upper estimate of a call's cost, used to reserve budget before it is made."""
    tokens = prompt_chars // CHARS_PER_TOKEN_FLOOR + 1
    return cost_usd(model, Usage(input_tokens=tokens, output_tokens=max_output_tokens))


class ModelClient(Protocol):
    def parse(
        self, *, model: str, system: str, user: str, schema: type[BaseModel], max_output_tokens: int
    ) -> ModelReply: ...


Finish = Callable[[Any, Usage, Decimal, str | None], None]


class Tracer(Protocol):
    def start(
        self, *, name: str, model: str, system: str, user: str, metadata: dict[str, Any]
    ) -> Finish: ...

    def flush(self) -> None: ...


class OpenAIClient:
    """Structured outputs through the Responses API."""

    def __init__(self) -> None:
        from openai import OpenAI

        config.require("OPENAI_API_KEY")
        self._client = OpenAI()  # reads OPENAI_API_KEY from the environment

    def parse(
        self, *, model: str, system: str, user: str, schema: type[BaseModel], max_output_tokens: int
    ) -> ModelReply:
        response = self._client.responses.parse(
            model=model,
            input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            text_format=schema,
            max_output_tokens=max_output_tokens,
            store=False,
        )
        return ModelReply(
            parsed=response.output_parsed,
            usage=_usage_of(response),
            failure=_failure_of(response),
            response_id=response.id,
        )


def _usage_of(response: Any) -> Usage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return Usage()
    details = getattr(usage, "input_tokens_details", None)
    return Usage(
        input_tokens=usage.input_tokens or 0,
        cached_tokens=getattr(details, "cached_tokens", 0) or 0,
        cache_write_tokens=getattr(details, "cache_write_tokens", 0) or 0,
        output_tokens=usage.output_tokens or 0,
    )


def _failure_of(response: Any) -> str | None:
    if response.status == "incomplete":
        reason = getattr(response.incomplete_details, "reason", "unknown")
        return f"The answer was cut off ({reason})."
    if response.error is not None:
        return f"The API reported an error: {response.error}"
    if response.output_parsed is None:
        return "No structured answer came back (a refusal or an empty reply)."
    return None


class LangfuseTracer:
    """Traces each call as a Langfuse generation. Refuses to start without working keys."""

    def __init__(self) -> None:
        from langfuse import Langfuse

        self._client = Langfuse(
            public_key=config.require("LANGFUSE_PUBLIC_KEY"),
            secret_key=config.require("LANGFUSE_SECRET_KEY"),
            base_url=config.langfuse_base_url(),
        )
        if not self._client.auth_check():
            raise config.MissingSetting("Langfuse did not accept the keys. No model call was made.")

    def start(
        self, *, name: str, model: str, system: str, user: str, metadata: dict[str, Any]
    ) -> Finish:
        context = self._client.start_as_current_observation(
            as_type="generation",
            name=name,
            model=model,
            input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            metadata=metadata,
        )
        generation = context.__enter__()

        def finish(output: Any, usage: Usage, cost: Decimal, failure: str | None) -> None:
            generation.update(
                output=output,
                usage_details={"input": usage.input_tokens, "output": usage.output_tokens},
                cost_details={"total": float(cost)},
                level="ERROR" if failure else "DEFAULT",
                status_message=failure,
            )
            context.__exit__(None, None, None)

        return finish

    def flush(self) -> None:
        self._client.flush()


class ModelGate:
    """Counts, caps and traces every model call of one run."""

    def __init__(
        self,
        conn: Connection,
        client: ModelClient,
        tracer: Tracer,
        run_id: int,
        cap_usd: Decimal,
        now: Callable[[], datetime] = utc_now,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.conn = conn
        self.client = client
        self.tracer = tracer
        self.run_id = run_id
        self.cap_usd = cap_usd
        self.now = now
        self.clock = clock

    def spent(self) -> Decimal:
        """The run's spend so far, read from the database."""
        row = self.conn.execute(
            "SELECT coalesce(sum(cost_usd), 0) AS total FROM model_call WHERE run_id = %s",
            (self.run_id,),
        ).fetchone()
        return Decimal(row["total"]) if row else Decimal(0)

    def call(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[BaseModel],
        purpose: str,
        entry_id: int | None = None,
        max_output_tokens: int = MAX_OUTPUT_TOKENS,
    ) -> ModelReply:
        """Make one model call, or raise CostCapReached without making it."""
        reserve = worst_case_cost(model, len(system) + len(user), max_output_tokens)
        spent = self.spent()
        if spent + reserve > self.cap_usd:
            raise CostCapReached(
                f"Spent ${spent:.2f} of the ${self.cap_usd:.2f} cap; the next call could cost "
                f"up to ${reserve:.2f}."
            )
        metadata = {"run_id": self.run_id, "entry_id": entry_id, "purpose": purpose}
        finish = self.tracer.start(
            name=purpose, model=model, system=system, user=user, metadata=metadata
        )
        started_at, start = self.now(), self.clock()
        try:
            reply = self.client.parse(
                model=model,
                system=system,
                user=user,
                schema=schema,
                max_output_tokens=max_output_tokens,
            )
        except Exception as error:  # noqa: BLE001 - any API failure is recorded, not hidden
            reply = ModelReply(None, Usage(), f"{type(error).__name__}: {error}"[:500])
        cost = cost_usd(model, reply.usage)
        self._record(purpose, entry_id, model, reply, cost, started_at, self.clock() - start)
        output = reply.parsed.model_dump(mode="json") if reply.parsed else None
        finish(output, reply.usage, cost, reply.failure)
        return reply

    def _record(
        self,
        purpose: str,
        entry_id: int | None,
        model: str,
        reply: ModelReply,
        cost: Decimal,
        started_at: datetime,
        seconds: float,
    ) -> None:
        self.conn.execute(
            "INSERT INTO model_call (run_id, purpose, entry_id, model, input_tokens, "
            "cached_tokens, cache_write_tokens, output_tokens, cost_usd, started_at, seconds, "
            "failure, response_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                self.run_id,
                purpose,
                entry_id,
                model,
                reply.usage.input_tokens,
                reply.usage.cached_tokens,
                reply.usage.cache_write_tokens,
                reply.usage.output_tokens,
                cost,
                started_at,
                seconds,
                reply.failure,
                reply.response_id,
            ),
        )
        self.conn.commit()
