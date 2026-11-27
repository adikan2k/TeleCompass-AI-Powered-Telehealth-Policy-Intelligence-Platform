"""A small local page for labelling a fixed sample of rules against the law (D11).

Blind: the page shows the rule, its quote and the nearest passages of the source. It never
shows the quote-check result, the rule's status, the grade or the CCHP entry.
Labels are written only when a person submits the form (rule 6).
"""

import random
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from html import escape
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from telecompass import rule_store, scope, store
from telecompass.db import Connection
from telecompass.extract import select_passages
from telecompass.fetch import utc_now
from telecompass.models import Rule
from telecompass.review import distinct_quoted_rules

SAMPLE_SIZE = 30
SAMPLE_SEED = 20261126
PASSAGE_CHARS = 6_000
VERDICTS = {"right": "Right", "wrong": "Wrong", "cannot_tell": "Cannot tell"}


def draw_sample(rules: list[Rule], size: int = SAMPLE_SIZE, seed: int = SAMPLE_SEED) -> list[int]:
    """Pick rule ids to label: spread over the rule types, same result for the same seed.

    Only rules that carry a quote are eligible; a silent rule has nothing to check. When
    several entries cite the same law, the same rule comes out more than once; only the first
    copy (same rule type, effect and quote) is eligible, so no label is spent on a repeat.
    """
    groups: dict[str, list[int]] = defaultdict(list)
    for rule in distinct_quoted_rules(rules):
        groups[rule.rule_type].append(rule.id)
    rng = random.Random(seed)
    for ids in groups.values():
        ids.sort()
        rng.shuffle(ids)
    chosen: list[int] = []
    order = sorted(groups)
    while len(chosen) < size and any(groups[name] for name in order):
        for name in order:  # one from each type in turn, so small types are not crowded out
            if groups[name] and len(chosen) < size:
                chosen.append(groups[name].pop())
    rng.shuffle(chosen)
    return chosen


def ensure_sample(conn: Connection, run_id: int, at: datetime) -> list[int]:
    """The run's stored sample, drawing and storing it the first time."""
    sample = rule_store.sample_for(conn, run_id)
    if not sample:
        sample = draw_sample(rule_store.rules_for(conn, run_id))
        rule_store.save_sample(conn, run_id, sample, SAMPLE_SEED, at)
    return sample


def create_app(
    conn: Connection,
    run_id: int,
    labeller: str,
    sources_fetched: str,
    now: Callable[[], datetime] = utc_now,
) -> FastAPI:
    app = FastAPI(title="TeleCompass labelling", docs_url=None, redoc_url=None)
    sample = ensure_sample(conn, run_id, now())
    footer = f"Not legal advice. Sources last fetched {sources_fetched}."

    def next_unlabelled() -> int | None:
        done = rule_store.latest_labels(conn, run_id)
        return next((i for i, rule_id in enumerate(sample) if rule_id not in done), None)

    @app.get("/")
    def home() -> RedirectResponse:
        position = next_unlabelled()
        return RedirectResponse("/done" if position is None else f"/rule/{position}", 303)

    @app.get("/rule/{position}", response_class=HTMLResponse)
    def show_rule(position: int) -> HTMLResponse:
        if not 0 <= position < len(sample):
            return HTMLResponse(
                _page("Not found", "<p>No such rule in the sample.</p>", footer), 404
            )
        rule = rule_store.rule_by_id(conn, sample[position])
        source = store.source_text_by_id(conn, rule.source_text_id) if rule.source_text_id else None
        earlier = rule_store.latest_labels(conn, run_id).get(rule.id)
        body = _rule_html(rule, source.text if source else None, position, len(sample), earlier)
        return HTMLResponse(_page(f"Rule {position + 1} of {len(sample)}", body, footer))

    @app.post("/rule/{position}")
    async def save(position: int, request: Request) -> RedirectResponse:
        form = parse_qs((await request.body()).decode("utf-8"))
        verdict = form.get("verdict", [""])[0]
        if not 0 <= position < len(sample) or verdict not in VERDICTS:
            return RedirectResponse(f"/rule/{position}", 303)
        note = form.get("note", [""])[0].strip() or None
        rule_store.save_label(conn, run_id, sample[position], verdict, note, labeller, now())
        return RedirectResponse("/", 303)

    @app.get("/done", response_class=HTMLResponse)
    def done() -> HTMLResponse:
        labelled = len(rule_store.latest_labels(conn, run_id))
        body = (
            f"<p>{labelled} of {len(sample)} rules are labelled.</p>"
            "<p>Stop this page with Ctrl+C in the terminal, then run "
            "<code>python -m telecompass grade</code> for the jurisdiction to add the labels to "
            "the results file.</p>" + _index_html(sample, conn, run_id)
        )
        return HTMLResponse(_page("Labelling", body, footer))

    return app


def _index_html(sample: list[int], conn: Connection, run_id: int) -> str:
    done = rule_store.latest_labels(conn, run_id)
    links = []
    for position, rule_id in enumerate(sample):
        state = "labelled" if rule_id in done else "not labelled"
        links.append(f'<li><a href="/rule/{position}">Rule {position + 1}</a> ({state})</li>')
    return "<ol class='index'>" + "".join(links) + "</ol>"


def _field(name: str, value: object) -> str:
    return f"<tr><th>{escape(name)}</th><td>{escape(str(value))}</td></tr>" if value else ""


def _rule_html(
    rule: Rule, source_text: str | None, position: int, total: int, earlier: dict | None
) -> str:
    fields = "".join(
        [
            _field("Rule type", scope.RULE_TYPE_LABELS.get(rule.rule_type, rule.rule_type)),
            _field("Effect", rule.effect),
            _field("Kind", rule.aspect),
            _field("Profession", rule.profession),
            _field("Payer", rule.payer),
            _field("Modality", rule.modality),
            _field("Service", rule.service),
            _field("Compact", rule.compact),
            _field("Conditions", "; ".join(rule.conditions)),
            _field("In force from", rule.effective_from),
            _field("In force to", rule.effective_to),
        ]
    )
    if source_text:
        passages, cut = select_passages(source_text, f"{rule.quote} {rule.summary}", PASSAGE_CHARS)
        heading = "Nearest passages of the source" if cut else "The source text"
        source_html = f"<h2>{heading}</h2><pre class='source'>{escape(passages)}</pre>"
    else:
        source_html = "<h2>The source text</h2><p>No stored text for this source.</p>"
    link = (
        f'<p>Source: <a href="{escape(rule.source_url)}" rel="noreferrer">'
        f"{escape(rule.source_url)}</a></p>"
        if rule.source_url
        else ""
    )
    before = (
        f"<p class='earlier'>You labelled this rule earlier as: "
        f"<strong>{escape(VERDICTS[earlier['verdict']])}</strong>. A new answer replaces it.</p>"
        if earlier
        else ""
    )
    buttons = "".join(
        f'<button type="submit" name="verdict" value="{value}">{text}</button>'
        for value, text in VERDICTS.items()
    )
    return (
        f"<p class='progress'>Rule {position + 1} of {total}</p>"
        f"<h2>The rule</h2><p class='summary'>{escape(rule.summary)}</p><table>{fields}</table>"
        f"<h2>The quote it rests on</h2><blockquote>{escape(rule.quote or '')}</blockquote>"
        f"{link}{source_html}"
        "<h2>Your judgement</h2>"
        "<p>Right: the quote is in the source, and the rule says what the source says. "
        "Wrong: either one fails. Cannot tell: the source shown is not enough to decide.</p>"
        f"{before}<form method='post'>"
        "<label for='note'>Note (optional)</label>"
        "<textarea id='note' name='note' rows='3'></textarea>"
        f"<div class='buttons'>{buttons}</div></form>"
    )


def _page(title: str, body: str, footer: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} - TeleCompass labelling</title>
<style>
  body {{ font: 16px/1.5 system-ui, sans-serif; color: #1a1a1a; background: #fff;
         max-width: 60rem; margin: 0 auto; padding: 1rem; }}
  h1 {{ font-size: 1.3rem; }} h2 {{ font-size: 1.05rem; margin-top: 1.5rem; }}
  table {{ border-collapse: collapse; }} th {{ text-align: left; padding-right: 1rem; }}
  th, td {{ vertical-align: top; padding-top: .2rem; padding-bottom: .2rem; }}
  blockquote {{ margin: 0; padding: .6rem 1rem; border-left: 4px solid #1a1a1a;
               background: #f2f2f2; }}
  pre.source {{ white-space: pre-wrap; font: 14px/1.5 ui-monospace, monospace; background: #f7f7f7;
               border: 1px solid #bbb; padding: .8rem; max-height: 28rem; overflow: auto; }}
  textarea {{ display: block; width: 100%; font: inherit; margin: .3rem 0 .8rem; }}
  .buttons {{ display: flex; gap: .6rem; flex-wrap: wrap; }}
  button {{ font: inherit; padding: .5rem 1.2rem; border: 2px solid #1a1a1a; background: #fff;
           cursor: pointer; }}
  button:hover, button:focus {{ background: #1a1a1a; color: #fff; }}
  .progress {{ color: #444; }} footer {{ margin-top: 2rem; border-top: 1px solid #bbb;
           padding-top: .6rem; color: #444; font-size: 14px; }}
</style></head>
<body><h1>{escape(title)}</h1>
{body}
<footer>{escape(footer)} TeleCompass labelling page, local use only.</footer>
</body></html>"""
