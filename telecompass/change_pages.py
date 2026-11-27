"""The change queue and official-copy pages of the local review page (D21).

A person sees what changed between two snapshots, decides on each proposal, and then asks for
the decisions to be applied, which resumes the paused change agent. A person also confirms, here,
that an official copy is the same document as a citation the fetcher may not open (D7).
"""

from collections.abc import Callable
from datetime import datetime
from html import escape
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from langgraph.checkpoint.postgres import PostgresSaver

from telecompass import change_agent, rule_store, sources, store
from telecompass.db import Connection

CHOICES = {
    "add": {"approved": "Approve the new rule", "rejected": "Reject it"},
    "retire": {"approved": "Retire the rule", "rejected": "Keep the rule"},
}
EXCERPT = 700


def _excerpt(text: str | None) -> str:
    if not text:
        return "<i>none</i>"
    flat = " ".join(text.split())
    return escape(flat if len(flat) <= EXCERPT else flat[:EXCERPT].rstrip() + "…")


def add_change_pages(
    app: FastAPI,
    conn: Connection,
    reviewer: str,
    now: Callable[[], datetime],
    db_url: str | None,
    page: Callable[[str, str], str],
    quote_in_place: Callable[[str, str], str],
) -> None:
    """Register the /changes and /sources pages on the review app."""

    def with_graph(work: Callable):
        if db_url is None:
            raise RuntimeError("The change queue needs the database address.")
        with PostgresSaver.from_conn_string(db_url) as saver:
            saver.setup()
            return work(change_agent.build_graph(conn, saver, now=now))

    @app.get("/changes", response_class=HTMLResponse)
    def changes() -> HTMLResponse:
        runs = conn.execute(
            "SELECT d.id, d.jurisdiction, so.captured_at AS old_at, so.origin AS old_origin, "
            "sn.captured_at AS new_at, sn.origin AS new_origin, "
            "(SELECT count(*) FROM entry_change c WHERE c.diff_run_id = d.id "
            " AND c.rule_type IS NOT NULL AND c.kind IN ('added','removed','changed')) AS real, "
            "(SELECT count(*) FROM change_proposal p WHERE p.diff_run_id = d.id) AS proposals "
            "FROM diff_run d "
            "JOIN parse_run ro ON ro.id = d.old_parse_run_id JOIN snapshot so ON so.id = ro.snapshot_id "
            "JOIN parse_run rn ON rn.id = d.new_parse_run_id JOIN snapshot sn ON sn.id = rn.snapshot_id "
            "ORDER BY d.id DESC"
        ).fetchall()
        statuses = with_graph(lambda g: {r["id"]: change_agent.status(g, r["id"]) for r in runs})
        rows = "".join(
            f"<li><a href='/changes/{r['id']}'>{escape(r['jurisdiction'].title())}: "
            f"{r['old_at']:%d %b %Y} ({r['old_origin']}) to {r['new_at']:%d %b %Y} "
            f"({r['new_origin']})</a> <span class='state not'>{r['real']} real changes, "
            f"{r['proposals']} proposals, {statuses[r['id']]}</span></li>"
            for r in runs
        )
        body = (
            f"<h2>Changes between snapshots</h2><ol class='all'>{rows or '<li>None yet.</li>'}</ol>"
        )
        return HTMLResponse(page("Changes", body))

    @app.get("/changes/{diff_id}", response_class=HTMLResponse)
    def one(diff_id: int) -> HTMLResponse:
        status = with_graph(lambda g: change_agent.status(g, diff_id))
        items = conn.execute(
            "SELECT c.*, o.text AS old_text, n.text AS new_text, n.source_links AS links "
            "FROM entry_change c LEFT JOIN entry o ON o.id = c.old_entry_id "
            "LEFT JOIN entry n ON n.id = c.new_entry_id WHERE c.diff_run_id = %s "
            "AND c.rule_type IS NOT NULL AND c.kind IN ('added','removed','changed') ORDER BY c.id",
            (diff_id,),
        ).fetchall()
        proposals = conn.execute(
            "SELECT * FROM change_proposal WHERE diff_run_id = %s ORDER BY id", (diff_id,)
        ).fetchall()
        decided = change_agent.latest_decisions(conn, [p["id"] for p in proposals])
        candidates = {o.cited_url: o for o in sources.candidate_overrides()}
        blocks = []
        for item in items:
            mine = [p for p in proposals if p["entry_change_id"] == item["id"]]
            place = " / ".join(x for x in (item["category"], item["topic"], item["subtopic"]) if x)
            parts = "".join(
                _proposal_html(p, decided.get(p["id"]), diff_id, status, item, candidates)
                for p in mine
            )
            blocks.append(
                f"<section class='change'><h3>{escape(item['kind'].title())}: {escape(place)}</h3>"
                f"<dl class='fields'><dt>Before</dt><dd>{_excerpt(item['old_text'])}</dd>"
                f"<dt>Now</dt><dd>{_excerpt(item['new_text'])}</dd></dl>"
                f"{parts or '<p class=help>The agent has not looked at this change yet.</p>'}"
                "</section>"
            )
        if status == "waiting for review":
            undecided = sum(1 for p in proposals if p["kind"] in CHOICES and p["id"] not in decided)
            footer = (
                f"<form method='post' action='/changes/{diff_id}/apply' class='bulk'><h3>Apply your "
                "decisions</h3><p class='help'>Approved new rules join the live rules and approved "
                f"retirements take rules out. {undecided} proposal(s) are still undecided and will stay out."
                "</p><button class='approve' type='submit'>Apply decisions</button></form>"
            )
        elif status == "done":
            footer = "<p><b>The decisions on this change have been applied.</b></p>"
        else:
            footer = (
                "<p class='help'>The change agent has not run on this diff yet. Run "
                f"<code>python -m telecompass changes &lt;state&gt; --diff {diff_id}</code>.</p>"
            )
        body = f"<h2>Changes in diff {diff_id}</h2><p class='where'>Status: {status}.</p>"
        return HTMLResponse(page(f"Diff {diff_id}", body + "".join(blocks) + footer))

    def _proposal_html(proposal, decision, diff_id, status, item, candidates) -> str:
        kind = proposal["kind"]
        if kind in ("add", "already_live", "retire"):
            rule_id = proposal["rule_id"] if kind != "retire" else proposal["matched_rule_id"]
            rule = rule_store.rule_by_id(conn, rule_id)
            source = (
                store.source_text_by_id(conn, rule.source_text_id) if rule.source_text_id else None
            )
            context = (
                f"<details><summary>Where the words sit in the source</summary>"
                f"<p class='src'>{escape(rule.source_url or '')}</p>"
                f"<pre class='source'>{quote_in_place(source.text, rule.quote or '')}</pre></details>"
                if source and source.text
                else ""
            )
            heading = {
                "add": "Proposed new rule",
                "already_live": "Read again: already live, nothing to do",
                "retire": "Proposed retirement of a live rule",
            }[kind]
            note = f"<p class='help'>{escape(proposal['note'])}</p>" if proposal["note"] else ""
            card = (
                f"<div class='proposal {kind}'><h4>{heading}</h4><p><b>{escape(rule.summary)}</b></p>"
                f"<blockquote>{escape(rule.quote or '')}</blockquote>{note}{context}"
            )
        else:
            heading = {"unreadable": "The cited law could not be read",
                       "no_rules": "The law was read; no rule on this point"}[kind]  # fmt: skip
            hint = ""
            for link in item["links"] or []:
                candidate = candidates.get(link["url"])
                if candidate is not None:
                    hint = (
                        f"<p class='help'>An official copy may exist: {escape(candidate.document)}. "
                        "Compare it on the <a href='/sources'>Official copies</a> page.</p>"
                    )
            card = (
                f"<div class='proposal {kind}'><h4>{heading}</h4>"
                f"<p class='help'>{escape(proposal['note'] or '')}</p>{hint}"
            )
        if kind in CHOICES:
            if decision is not None:
                word = CHOICES[kind][decision["decision"]]
                card += f"<p class='earlier'>Your decision: {escape(word)}.</p>"
            if status == "waiting for review":
                buttons = "".join(
                    f"<button class='{'approve' if value == 'approved' else 'reject'}' "
                    f"type='submit' name='decision' value='{value}'>{escape(text)}</button>"
                    for value, text in CHOICES[kind].items()
                )
                card += (
                    f"<form method='post' action='/changes/{diff_id}/proposal/{proposal['id']}'>"
                    f"<div class='buttons'>{buttons}</div></form>"
                )
        return card + "</div>"

    @app.post("/changes/{diff_id}/proposal/{proposal_id}")
    async def decide(diff_id: int, proposal_id: int, request: Request) -> RedirectResponse:
        form = parse_qs((await request.body()).decode("utf-8"))
        decision = form.get("decision", [""])[0]
        row = conn.execute(
            "SELECT kind FROM change_proposal WHERE id = %s AND diff_run_id = %s",
            (proposal_id, diff_id),
        ).fetchone()
        if row is not None and row["kind"] in CHOICES and decision in ("approved", "rejected"):
            change_agent.save_decision(conn, proposal_id, decision, None, reviewer, now())
        return RedirectResponse(f"/changes/{diff_id}", 303)

    @app.post("/changes/{diff_id}/apply")
    def apply(diff_id: int) -> RedirectResponse:
        with_graph(lambda g: change_agent.finish(g, diff_id, reviewer))
        return RedirectResponse(f"/changes/{diff_id}", 303)

    @app.get("/sources", response_class=HTMLResponse)
    def official_copies() -> HTMLResponse:
        confirmed = sources.load_overrides(conn=conn)
        cards = []
        for index, item in enumerate(sources.candidate_overrides()):
            done = confirmed.get(item.cited_url)
            state = (
                f"<p class='earlier'>Confirmed by {escape(done.confirmed_by)} on "
                f"{escape(done.confirmed_on)}.</p>"
                if done is not None and done.official_url == item.official_url
                else (
                    f"<form method='post' action='/sources/{index}/confirm'>"
                    "<label class='tick'><input type='checkbox' name='same' value='yes' required> "
                    "I opened both links, and they are the same document.</label>"
                    "<div class='buttons'><button class='approve' type='submit'>Confirm the "
                    "official copy</button></div></form>"
                )
            )
            cards.append(
                f"<section class='change'><h3>{escape(item.document)}</h3><dl class='fields'>"
                f"<dt>Cited</dt><dd><a href='{escape(item.cited_url)}' target='_blank' "
                f"rel='noreferrer'>{escape(item.cited_url)}</a></dd>"
                f"<dt>Official copy</dt><dd><a href='{escape(item.official_url)}' target='_blank' "
                f"rel='noreferrer'>{escape(item.official_url)}</a></dd></dl>{state}</section>"
            )
        body = (
            "<h2>Official copies</h2><p class='help'>Some citations sit on sites that forbid "
            "automated fetching. Where the same document is published officially, it is listed "
            "here. It is used only after a person opens both and confirms they match.</p>"
            + "".join(cards)
        )
        return HTMLResponse(page("Official copies", body))

    @app.post("/sources/{index}/confirm")
    async def confirm(index: int, request: Request) -> RedirectResponse:
        form = parse_qs((await request.body()).decode("utf-8"))
        listed = sources.candidate_overrides()
        if form.get("same", [""])[0] == "yes" and 0 <= index < len(listed):
            sources.confirm_override(conn, listed[index], reviewer, now())
        return RedirectResponse("/sources", 303)
