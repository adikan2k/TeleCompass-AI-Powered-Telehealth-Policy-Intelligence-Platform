"""The model gate: cost, cap and tracing. No real model is called."""

from decimal import Decimal

import pytest
from pydantic import BaseModel

from fakes import FakeModel, FakeTracer, reply, start_run, store_invented_page
from telecompass import config
from telecompass.db import Connection
from telecompass.llm import (
    BULK_MODEL,
    EXTRACTION_MODEL,
    CostCapReached,
    ModelGate,
    Usage,
    cost_usd,
    worst_case_cost,
)


class Answer(BaseModel):
    text: str


def gate_for(conn: Connection, model: FakeModel, cap: str = "5.00") -> tuple[ModelGate, FakeTracer]:
    _, parse_run, _ = store_invented_page(conn)
    tracer = FakeTracer()
    run_id = start_run(conn, parse_run, cap)
    return ModelGate(conn, model, tracer, run_id, Decimal(cap)), tracer


def ask(gate: ModelGate, user: str = "a question"):
    return gate.call(
        model=EXTRACTION_MODEL, system="be exact", user=user, schema=Answer, purpose="test"
    )


def test_cost_follows_the_price_table() -> None:
    tokens = 100_000  # a tenth of a million, and under the long-prompt threshold
    assert cost_usd(EXTRACTION_MODEL, Usage(input_tokens=tokens)) == Decimal("0.200000")
    assert cost_usd(EXTRACTION_MODEL, Usage(output_tokens=tokens)) == Decimal("1.000000")
    assert cost_usd(BULK_MODEL, Usage(input_tokens=tokens, output_tokens=tokens)) == Decimal(
        "0.060000"
    )


def test_cached_and_cache_write_tokens_have_their_own_prices() -> None:
    usage = Usage(input_tokens=100_000, cached_tokens=60_000, cache_write_tokens=10_000)
    # 30,000 plain at $2.00, 60,000 cached at $0.10, 10,000 written at $2.50, per million.
    assert cost_usd(EXTRACTION_MODEL, usage) == Decimal("0.091000")


def test_very_long_prompts_cost_double_in_and_half_again_out() -> None:
    usage = Usage(input_tokens=300_000, output_tokens=1_000)
    assert cost_usd(EXTRACTION_MODEL, usage) == Decimal("1.215000")


def test_unknown_model_is_an_error_not_free() -> None:
    with pytest.raises(KeyError):
        cost_usd("some-other-model", Usage(input_tokens=10))


def test_a_call_is_counted_in_the_database_and_traced(conn: Connection) -> None:
    model = FakeModel(lambda _: reply(Answer(text="ok"), input_tokens=50_000, output_tokens=2_000))
    gate, tracer = gate_for(conn, model)

    result = ask(gate)

    assert result.parsed == Answer(text="ok")
    row = conn.execute("SELECT * FROM model_call").fetchone()
    assert (row["model"], row["input_tokens"], row["output_tokens"]) == (
        EXTRACTION_MODEL,
        50_000,
        2_000,
    )
    assert row["cost_usd"] == Decimal("0.120000")
    assert row["failure"] is None
    assert gate.spent() == Decimal("0.120000")
    assert tracer.started[0]["metadata"]["run_id"] == gate.run_id
    assert tracer.finished[0]["cost"] == Decimal("0.120000")
    assert tracer.finished[0]["output"] == {"text": "ok"}


def test_call_that_could_pass_the_cap_is_refused_before_it_is_made(conn: Connection) -> None:
    model = FakeModel(lambda _: reply(Answer(text="ok")))
    gate, tracer = gate_for(conn, model, cap="0.10")

    with pytest.raises(CostCapReached, match="cap"):
        ask(gate)  # 16,000 output tokens reserved at $10 per million is $0.16, over the cap

    assert model.calls == []
    assert tracer.started == []
    assert gate.spent() == Decimal(0)


def test_the_cap_counts_what_earlier_calls_spent(conn: Connection) -> None:
    model = FakeModel(lambda _: reply(Answer(text="ok"), input_tokens=0, output_tokens=40_000))
    gate, _ = gate_for(conn, model, cap="0.50")

    ask(gate)  # costs $0.40
    with pytest.raises(CostCapReached):
        ask(gate)  # $0.40 spent plus a $0.16 reserve is over $0.50

    assert len(model.calls) == 1


def test_api_error_is_recorded_as_a_failed_call_and_not_retried(conn: Connection) -> None:
    model = FakeModel(lambda _: RuntimeError("connection reset"))
    gate, tracer = gate_for(conn, model)

    result = ask(gate)

    assert result.parsed is None
    assert result.failure == "RuntimeError: connection reset"
    assert len(model.calls) == 1
    row = conn.execute("SELECT failure, cost_usd FROM model_call").fetchone()
    assert row["failure"] == "RuntimeError: connection reset"
    assert tracer.finished[0]["failure"] == "RuntimeError: connection reset"


def test_worst_case_reserve_grows_with_the_prompt() -> None:
    small = worst_case_cost(EXTRACTION_MODEL, 3_000, 16_000)
    large = worst_case_cost(EXTRACTION_MODEL, 300_000, 16_000)
    assert small == Decimal("0.162002")
    assert large > small


def test_langfuse_address_accepts_the_new_and_the_old_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    with pytest.raises(config.MissingSetting, match="LANGFUSE_BASE_URL"):
        config.langfuse_base_url()

    monkeypatch.setenv("LANGFUSE_HOST", "https://old.example")
    assert config.langfuse_base_url() == "https://old.example"
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://new.example")
    assert config.langfuse_base_url() == "https://new.example"


def test_missing_key_is_named_but_no_value_is_ever_shown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    with pytest.raises(config.MissingSetting, match="LANGFUSE_SECRET_KEY is not set"):
        config.require("LANGFUSE_SECRET_KEY")
