"""The labelling page: a fixed sample, a blind page, and labels only from a submitted form."""

from fastapi.testclient import TestClient

from fakes import AT, CODE_59_1, LAW_59_1, save_source, start_run, store_invented_page
from telecompass import grade, rule_store, scope
from telecompass.db import Connection
from telecompass.label_app import create_app, draw_sample, ensure_sample
from telecompass.models import Rule

QUOTE = "The programme reimburses services delivered by live, two-way video."


def make_rules(
    conn: Connection, per_type: dict[str, int], silent: int = 0
) -> tuple[int, list[Rule]]:
    """A run with the given number of quoted rules per rule type, half of them unverified."""
    _, parse_run, entries = store_invented_page(conn)
    source = save_source(conn, CODE_59_1, LAW_59_1)
    run_id = start_run(conn, parse_run)
    rules = []
    for rule_type, count in per_type.items():
        for number in range(count):
            verified = number % 2 == 0
            rules.append(
                rule_store.save_rule(
                    conn,
                    run_id=run_id,
                    entry_id=entries[0].id,
                    jurisdiction="avalon",
                    rule_type=rule_type,
                    aspect="coverage",
                    effect="allow",
                    summary=f"Rule {number} of {rule_type}.",
                    status="draft" if verified else "unverified",
                    quote_verified=verified,
                    quote=QUOTE if verified else "A quote that is not in the law at all.",
                    quote_note=None if verified else "The quote was not found word for word.",
                    source_text_id=source.id,
                    source_url=CODE_59_1,
                    created_at=AT,
                )
            )
    for _ in range(silent):
        rule_store.save_rule(
            conn,
            run_id=run_id,
            entry_id=entries[0].id,
            jurisdiction="avalon",
            rule_type=scope.CONSENT,
            aspect="consent",
            effect="silent",
            summary="The state is silent on this point.",
            status="draft",
            quote_verified=False,
            created_at=AT,
        )
    return run_id, rules


def client_for(conn: Connection, run_id: int) -> TestClient:
    app = create_app(conn, run_id, labeller="Aditya", sources_fetched="2026-03-15", now=lambda: AT)
    return TestClient(app, follow_redirects=False)


def test_sample_is_the_same_every_time_and_spread_over_rule_types(conn: Connection) -> None:
    _, rules = make_rules(
        conn, {scope.MEDICAID_MODALITY: 40, scope.ONLINE_PRESCRIBING: 12, scope.CONSENT: 2}
    )

    first, second = draw_sample(rules), draw_sample(rules)

    assert first == second
    assert len(first) == len(set(first)) == 30
    by_id = {rule.id: rule.rule_type for rule in rules}
    counts = {name: sum(1 for i in first if by_id[i] == name) for name in set(by_id.values())}
    assert counts == {scope.CONSENT: 2, scope.ONLINE_PRESCRIBING: 12, scope.MEDICAID_MODALITY: 16}
    assert draw_sample(rules, seed=7) != first


def test_silent_rules_are_never_sampled_and_a_small_run_is_taken_whole(conn: Connection) -> None:
    _, rules = make_rules(conn, {scope.MEDICAID_MODALITY: 3}, silent=4)
    assert sorted(draw_sample(rules)) == sorted(rule.id for rule in rules)


def test_sample_is_stored_once_and_reused(conn: Connection) -> None:
    run_id, _ = make_rules(conn, {scope.MEDICAID_MODALITY: 6})

    first = ensure_sample(conn, run_id, AT)
    again = ensure_sample(conn, run_id, AT)

    assert first == again == rule_store.sample_for(conn, run_id)
    assert len(first) == 6


def test_page_shows_the_rule_and_the_law_but_not_how_the_rule_was_judged(
    conn: Connection,
) -> None:
    run_id, _ = make_rules(conn, {scope.MEDICAID_MODALITY: 4})
    client = client_for(conn, run_id)

    assert client.get("/").headers["location"] == "/rule/0"
    pages = [client.get(f"/rule/{position}") for position in range(4)]

    for page in pages:
        assert page.status_code == 200
        assert "The programme reimburses services delivered by live, two-way video." in page.text
        assert "The programme does not reimburse telephone conversations" in page.text  # the law
        assert CODE_59_1 in page.text
        assert "Not legal advice. Sources last fetched 2026-03-15." in page.text
        for giveaway in ("unverified", "draft", "quote_verified", "not found word for word"):
            assert giveaway not in page.text
    shown = {("A quote that is not in the law at all." in page.text) for page in pages}
    assert shown == {True, False}  # both kinds are in the sample, and look the same


def test_label_is_written_only_when_the_form_is_submitted(conn: Connection) -> None:
    run_id, _ = make_rules(conn, {scope.MEDICAID_MODALITY: 3})
    client = client_for(conn, run_id)
    sample = rule_store.sample_for(conn, run_id)

    client.get("/rule/0")
    client.get("/done")
    assert rule_store.latest_labels(conn, run_id) == {}

    response = client.post("/rule/0", content="verdict=wrong&note=Quote+is+from+another+section")

    assert response.headers["location"] == "/"
    assert client.get("/").headers["location"] == "/rule/1"
    label = rule_store.latest_labels(conn, run_id)[sample[0]]
    assert (label["verdict"], label["note"], label["labeller"]) == (
        "wrong",
        "Quote is from another section",
        "Aditya",
    )


def test_bad_verdict_or_position_writes_nothing(conn: Connection) -> None:
    run_id, _ = make_rules(conn, {scope.MEDICAID_MODALITY: 2})
    client = client_for(conn, run_id)

    client.post("/rule/0", content="verdict=approved")
    client.post("/rule/99", content="verdict=right")

    assert rule_store.latest_labels(conn, run_id) == {}
    assert client.get("/rule/99").status_code == 404


def test_a_second_answer_replaces_the_first_without_deleting_it(conn: Connection) -> None:
    run_id, _ = make_rules(conn, {scope.MEDICAID_MODALITY: 1})
    client = client_for(conn, run_id)

    client.post("/rule/0", content="verdict=wrong")
    client.post("/rule/0", content="verdict=right")

    sample = rule_store.sample_for(conn, run_id)
    assert rule_store.latest_labels(conn, run_id)[sample[0]]["verdict"] == "right"
    assert conn.execute("SELECT count(*) AS n FROM label").fetchone()["n"] == 2
    assert client.get("/").headers["location"] == "/done"
    assert "1 of 1 rules are labelled" in client.get("/done").text
    assert "You labelled this rule earlier as: <strong>Right</strong>" in client.get("/rule/0").text


def test_labels_reach_the_results_file(conn: Connection) -> None:
    run_id, _ = make_rules(conn, {scope.MEDICAID_MODALITY: 3})
    client = client_for(conn, run_id)
    client.post("/rule/0", content="verdict=right")
    client.post("/rule/1", content="verdict=cannot_tell&note=Source+page+is+a+summary")

    labels = grade.build_results(conn, "avalon", AT)["labels"]

    assert (labels["sample_size"], labels["labelled"]) == (3, 2)
    assert (labels["right"], labels["wrong"], labels["cannot_tell"]) == (1, 0, 1)
    assert labels["labellers"] == ["Aditya"]
    assert labels["items"][1]["note"] == "Source page is a summary"
