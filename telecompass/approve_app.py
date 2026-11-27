"""A local page where a person approves or rejects each rule before it goes live (D17, rule 13).

Each page shows one rule, the exact words of the law it rests on, those words in their place
in the stored source, and what the second model said about it. A person's click is the only
thing that writes a review. Reviews are added rows; the rule itself is never changed.
"""

import re
from collections.abc import Callable
from datetime import datetime
from html import escape
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from telecompass import rule_store, scope, store
from telecompass.db import Connection
from telecompass.extract import normalise, select_passages
from telecompass.fetch import utc_now
from telecompass.models import Rule
from telecompass.review import distinct_quoted_rules

JURISDICTIONS = ["florida", "federal"]
PLACES = {"florida": "Florida", "federal": "Federal Medicare"}
PASSAGE_CHARS = 5_000
DECISIONS = {"approved": "Approve", "rejected": "Reject"}


def rules_to_review(conn: Connection) -> list[tuple[Rule, dict | None]]:
    """The distinct quoted rules of each jurisdiction's newest run, with the second model's view."""
    found: list[tuple[Rule, dict | None]] = []
    for jurisdiction in JURISDICTIONS:
        run = rule_store.latest_run(conn, jurisdiction)
        if run is None:
            continue
        automated = rule_store.latest_reviews(conn, run["id"])
        rules = distinct_quoted_rules(rule_store.rules_for(conn, run["id"]))
        rules.sort(key=lambda rule: (scope.RULE_TYPES.index(rule.rule_type)
                                     if rule.rule_type in scope.RULE_TYPES else 99, rule.id))  # fmt: skip
        found += [(rule, automated.get(rule.id)) for rule in rules]
    return found


def quote_in_place(source_text: str, quote: str) -> str:
    """The source passage around the quote, as HTML, with the quoted words set in bold."""
    passage, _ = select_passages(source_text, quote, PASSAGE_CHARS)
    words = normalise(quote).split(" ")
    pattern = r"\s+".join(re.escape(word) for word in words if word)
    html = escape(passage)
    match = re.search(pattern, passage) if pattern else None
    if match is None:
        return html
    start, end = match.span()
    return (
        escape(passage[:start])
        + f"<strong class='hit'>{escape(passage[start:end])}</strong>"
        + escape(passage[end:])
    )


def create_app(conn: Connection, reviewer: str, now: Callable[[], datetime] = utc_now) -> FastAPI:
    app = FastAPI(title="TeleCompass rule review", docs_url=None, redoc_url=None)
    items = rules_to_review(conn)
    ids = [rule.id for rule, _ in items]

    def reviews() -> dict[int, dict]:
        return rule_store.latest_rule_reviews(conn, ids)

    def next_unreviewed(after: int = -1) -> int | None:
        done = reviews()
        order = list(range(after + 1, len(items))) + list(range(0, after + 1))
        return next((i for i in order if ids[i] not in done), None)

    @app.get("/")
    def home() -> RedirectResponse:
        position = next_unreviewed()
        return RedirectResponse("/done" if position is None else f"/rule/{position}", 303)

    @app.get("/rule/{position}", response_class=HTMLResponse)
    def show(position: int) -> HTMLResponse:
        if not 0 <= position < len(items):
            return HTMLResponse(_page("Not found", "<p>No rule at that number.</p>"), 404)
        rule, automated = items[position]
        source = store.source_text_by_id(conn, rule.source_text_id) if rule.source_text_id else None
        earlier = reviews().get(rule.id)
        done = len(reviews())
        body = _rule_html(rule, automated, source.text if source else None, position, len(items),
                          done, earlier)  # fmt: skip
        return HTMLResponse(_page(f"Rule {position + 1} of {len(items)}", body))

    @app.post("/rule/{position}")
    async def save(position: int, request: Request) -> RedirectResponse:
        form = parse_qs((await request.body()).decode("utf-8"))
        decision = form.get("decision", [""])[0]
        if not 0 <= position < len(items) or decision not in DECISIONS:
            return RedirectResponse(f"/rule/{position}", 303)
        note = form.get("note", [""])[0].strip() or None
        rule_store.save_rule_review(conn, ids[position], decision, note, reviewer, now())
        following = next_unreviewed(position)
        return RedirectResponse("/done" if following is None else f"/rule/{following}", 303)

    @app.get("/done", response_class=HTMLResponse)
    def done() -> HTMLResponse:
        return HTMLResponse(_page("Review", _summary_html(items, reviews())))

    return app


def _field(name: str, value: object) -> str:
    if value in (None, "", "any", []):
        return ""
    return f"<dt>{escape(name)}</dt><dd>{escape(str(value))}</dd>"


def _rule_html(
    rule: Rule,
    automated: dict | None,
    source_text: str | None,
    position: int,
    total: int,
    done: int,
    earlier: dict | None,
) -> str:
    place = PLACES.get(rule.jurisdiction, rule.jurisdiction)
    kind = scope.RULE_TYPE_LABELS.get(rule.rule_type, rule.rule_type)
    dates = ""
    if rule.effective_from or rule.effective_to:
        dates = (
            f"{rule.effective_from or 'no stated start'} to {rule.effective_to or 'no stated end'}"
        )
    fields = "".join([
        _field("Effect", {"allow": "Allows", "deny": "Forbids or excludes",
                          "require": "Requires"}.get(rule.effect, rule.effect)),
        _field("Who", rule.profession),
        _field("Payer", rule.payer),
        _field("How", (rule.modality or "").replace("_", " ")),
        _field("Service", rule.service),
        _field("Kind of care", (rule.service_category or "").replace("_", " ")),
        _field("Compact", rule.compact),
        _field("In force", dates),
    ])  # fmt: skip
    if rule.conditions:
        items = "".join(f"<li>{escape(condition)}</li>" for condition in rule.conditions)
        fields += f"<dt>Conditions</dt><dd><ul class='conditions'>{items}</ul></dd>"
    if automated is None:
        machine = "<p class='machine'>The second model has not checked this rule.</p>"
    elif automated["verdict"] == "right":
        machine = (f"<p class='machine'><b>Second model: passed.</b> "
                   f"{escape(automated['reason'] or '')}</p>")  # fmt: skip
    else:
        machine = (f"<p class='machine flag'><b>Second model: flagged.</b> "
                   f"{escape(automated['reason'] or '')}</p>")  # fmt: skip
    context = (
        f"<pre class='source'>{quote_in_place(source_text, rule.quote or '')}</pre>"
        if source_text
        else "<p>No stored text for this source.</p>"
    )
    link = (
        f'<a href="{escape(rule.source_url)}" target="_blank" rel="noreferrer">'
        f"{escape(rule.source_url)}</a>"
        if rule.source_url
        else "no link stored"
    )
    before = ""
    if earlier:
        word = "approved" if earlier["decision"] == "approved" else "rejected"
        note = f" Note: {escape(earlier['note'])}" if earlier["note"] else ""
        before = (
            f"<p class='earlier'>You {word} this rule earlier.{note} A new choice replaces it.</p>"
        )
    prev_link = f"<a href='/rule/{position - 1}'>Previous rule</a>" if position > 0 else ""
    next_link = (
        f"<a href='/rule/{position + 1}'>Skip to the next rule</a>" if position + 1 < total else ""
    )
    return f"""
<p class="progress"><span>{done} of {total} reviewed</span>
  <span class="bar"><span style="width:{round(100 * done / max(total, 1))}%"></span></span></p>
<p class="where">{escape(place)}. {escape(kind)}.</p>
<h2>{escape(rule.summary)}</h2>
<dl class="fields">{fields}</dl>
<h3>The words of the law</h3>
<blockquote>{escape(rule.quote or "")}</blockquote>
{machine}
<details open><summary>Where the words sit in the source</summary>
  <p class="src">Source: {link}</p>{context}</details>
<form method="post">
  <h3>Your review</h3>
  <p class="help">Approve if the sentence at the top says what the quoted words say, no more and no
  less, and the details match them. Reject if anything is wrong, missing or broader than the law.
  You can type a note either way.</p>
  {before}
  <label for="note">Note (optional)</label>
  <textarea id="note" name="note" rows="2"></textarea>
  <div class="buttons">
    <button class="approve" type="submit" name="decision" value="approved">Approve <kbd>A</kbd></button>
    <button class="reject" type="submit" name="decision" value="rejected">Reject <kbd>R</kbd></button>
  </div>
</form>
<nav class="pager">{prev_link} <a href="/done">All rules</a> {next_link}</nav>
<script>
document.addEventListener('keydown', (e) => {{
  if (e.target.closest('textarea, input') || e.metaKey || e.ctrlKey || e.altKey) return;
  const pick = {{a: 'approved', r: 'rejected'}}[e.key.toLowerCase()];
  if (pick) document.querySelector(`button[value="${{pick}}"]`).click();
}});
</script>"""


def _summary_html(items: list[tuple[Rule, dict | None]], reviews: dict[int, dict]) -> str:
    approved = sum(1 for review in reviews.values() if review["decision"] == "approved")
    rejected = sum(1 for review in reviews.values() if review["decision"] == "rejected")
    left = len(items) - len(reviews)
    rows = []
    for position, (rule, _) in enumerate(items):
        review = reviews.get(rule.id)
        state = {"approved": "Approved", "rejected": "Rejected"}.get(
            review["decision"] if review else "", "Not reviewed"
        )
        rows.append(
            f"<li><a href='/rule/{position}'>{escape(rule.summary)}</a> "
            f"<span class='state {state.split()[0].lower()}'>{state}</span></li>"
        )
    finish = (
        "<p><b>All rules are reviewed.</b> Stop this page with Ctrl+C in the terminal and tell "
        "Claude it is done.</p>"
        if left == 0
        else f"<p>{left} still to review. <a href='/'>Continue</a></p>"
    )
    return (
        f"<p class='totals'>{approved} approved, {rejected} rejected, {left} not reviewed.</p>"
        f"{finish}<ol class='all'>{''.join(rows)}</ol>"
    )


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}: TeleCompass rule review</title>
<style>
  :root {{ --paper:#eef2f0; --sheet:#fff; --ink:#14211e; --soft:#46554f; --rule:rgb(20 33 30/.13);
          --strong:rgb(20 33 30/.28); --signal:#e4570e; --ok:#0b6b3c; --stop:#a8201a;
          --warn:#7c5200; --warnsoft:#f8edd2; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--ink);
         font:16px/1.55 "Segoe UI", system-ui, sans-serif; }}
  header {{ background:var(--ink); color:#fff; padding:10px 24px; font-size:14px; }}
  main {{ max-width:56rem; margin:0 auto; padding:24px; }}
  h1 {{ font-size:15px; font-weight:600; margin:0; }}
  h2 {{ font-size:24px; line-height:1.25; font-weight:600; letter-spacing:-.015em; margin:.2em 0 .6em; }}
  h3 {{ font-size:15px; margin:1.6em 0 .5em; }}
  .progress {{ display:flex; align-items:center; gap:12px; color:var(--soft); font-size:14px; }}
  .bar {{ flex:1; height:4px; background:var(--strong); }}
  .bar span {{ display:block; height:4px; background:var(--signal); }}
  .where {{ color:var(--soft); margin:1.4em 0 0; font-size:14px; }}
  dl.fields {{ display:grid; grid-template-columns:max-content 1fr; gap:4px 16px; font-size:15px;
               background:var(--sheet); border:1px solid var(--rule); padding:12px 16px; margin:0; }}
  dl.fields dt {{ color:var(--soft); }} dl.fields dd {{ margin:0; }}
  ul.conditions {{ margin:0; padding-left:1.1em; }} ul.conditions li {{ margin:2px 0; }}
  blockquote {{ margin:0; background:var(--sheet); border:1px solid var(--strong); padding:12px 16px;
               font-size:17px; line-height:1.65; max-width:68ch; }}
  .machine {{ font-size:15px; padding:10px 14px; border:1px solid var(--rule); background:var(--sheet); }}
  .machine.flag {{ border:2px solid var(--warn); background:var(--warnsoft); }}
  details {{ margin-top:16px; }} summary {{ cursor:pointer; font-weight:600; font-size:15px; }}
  .src {{ font-size:14px; overflow-wrap:anywhere; color:var(--soft); }}
  pre.source {{ white-space:pre-wrap; font:14px/1.6 Consolas, ui-monospace, monospace;
               background:var(--sheet); border:1px solid var(--rule); padding:12px 16px;
               max-height:22rem; overflow:auto; }}
  .hit {{ background:#fdeadd; outline:1px solid var(--signal); }}
  form {{ margin-top:8px; border-top:1px solid var(--strong); }}
  .help {{ color:var(--soft); font-size:15px; max-width:68ch; }}
  label {{ display:block; font-size:14px; font-weight:600; margin-top:12px; }}
  textarea {{ width:100%; font:inherit; margin-top:4px; padding:8px; border:1px solid var(--strong); }}
  .buttons {{ display:flex; gap:12px; margin-top:12px; flex-wrap:wrap; }}
  button {{ font:inherit; font-weight:600; min-height:48px; padding:0 22px; border:2px solid var(--ink);
           cursor:pointer; transition:transform 160ms cubic-bezier(.23,1,.32,1); }}
  button:active {{ transform:scale(.97); }}
  button.approve {{ background:var(--ink); color:#fff; }}
  button.reject {{ background:var(--sheet); color:var(--stop); border-color:var(--stop); }}
  kbd {{ font:12px Consolas, monospace; border:1px solid currentColor; padding:1px 5px; margin-left:6px;
        opacity:.8; }}
  :focus-visible {{ outline:2px solid var(--signal); outline-offset:2px; }}
  .earlier {{ background:var(--warnsoft); padding:8px 12px; font-size:15px; }}
  .pager {{ display:flex; gap:20px; margin-top:28px; font-size:15px; }}
  a {{ color:var(--ink); text-underline-offset:3px; }}
  .totals {{ font-size:20px; font-weight:600; }}
  ol.all {{ padding-left:1.4em; }} ol.all li {{ margin:6px 0; }}
  .state {{ font-size:13px; font-weight:600; margin-left:6px; }}
  .state.approved {{ color:var(--ok); }} .state.rejected {{ color:var(--stop); }}
  .state.not {{ color:var(--soft); }}
  @media (prefers-reduced-motion: reduce) {{ button {{ transition:none; }} }}
</style></head>
<body><header><h1>TeleCompass rule review. Local only. Not legal advice.</h1></header>
<main>{body}</main></body></html>"""
