"""The Help chat: answers questions about the website, and learns from the ones it can't answer.

Anyone can ask (no login). When the person is logged in, the chat also looks at THEIR OWN
receipts, code and plots to give tips. Nobody else's data is ever used.
The help tables (phase_k.sql) are optional: without them the chat still answers, it just
can't save questions or use the admins' answers.
"""
import logging
import secrets
from datetime import datetime, timezone

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse

from sabageo import assistant
from sabageo.db import connect
from sabageo.helpers import sha
from sabageo.models import HelpAnswerIn, HelpAskIn, HelpFeedbackIn
from sabageo.routes.accounts import account_me
from sabageo.security import account_from_token, log_action, require_admin, require_client, staff_from_token, throttle

router = APIRouter()
log = logging.getLogger("sabageo")

NOT_SURE = ("I'm not sure about that one yet. I've saved your question so the SABAGeo team can add an answer. "
            "Meanwhile, one of these might help:")


def optional(conn, query, params=(), default=None):
    """Run a query on a help table; give `default` if phase_k.sql has not been run yet."""
    try:
        with conn.transaction():
            cur = conn.execute(query, params)
            return cur.fetchall() if cur.description else True
    except psycopg.errors.UndefinedTable:
        log.warning("Help tables missing: run phase_k.sql (the chat still answers, but can't learn)")
        return default


def page_of(path):
    """/receipt/SABA-RCPT-0001?x=1 -> /receipt, so receipt numbers and codes in addresses are never saved."""
    path = (path or "/").split("?")[0].split("#")[0]
    if path.startswith("/pay/"):
        return "/payments"
    if path.startswith("/admin"):
        return "/admin"
    parts = [p for p in path.split("/") if p]
    return "/" + parts[0] if parts else "/"


def admin_answers(conn):
    return optional(conn, "SELECT id, question, keywords, answer FROM help_answers WHERE active ORDER BY id", default=[])


def short(item):
    return {"key": item["key"], "question": item["question"]}


def when(t):
    return t.strftime("%d %b %Y") if t else ""


def user_tips(page, account_token, client_token, staff_token):
    """What the chat can see about the person asking: only their own things, said in plain words."""
    tips, name = [], None
    try:
        staff = staff_from_token(staff_token)
        if staff:
            name = staff["name"]
            tips.append("You're logged in as an admin, so you can use every admin page.")
        account = account_from_token(account_token)
    except HTTPException:  # accounts not set up on this database yet
        staff = account = None
    if account:
        name = account["name"]
        me = account_me(account)
        if not me["payments"]:
            tips.append("Your account has no receipts yet. Pick a plan on /payments, or add an office receipt "
                        "in My account (/account).")
        for p in me["payments"][:2]:
            no, state = p["receipt_no"], p["code_state"]
            if state == "active":
                left = ("no plot limit" if p["plots_allowed"] is None
                        else f"{p['plots_allowed'] - p['plots_used']} plot(s) left")
                ends = datetime.fromisoformat(p["expires_at"])
                tips.append(f"Receipt {no}: your code works until {when(ends)} ({left}). Press Register a plot "
                            "on it in My account (/account).")
            elif state == "expired":
                tips.append(f"Receipt {no}: its code has expired. A new token payment (/payments) is needed "
                            "to register more plots.")
            elif state == "used_up":
                tips.append(f"Receipt {no}: its plot is already used. A different plot needs a new payment.")
            elif state == "revoked":
                tips.append(f"Receipt {no} was cancelled, so its code doesn't work. Please contact SABAGeo.")
        if me["plots"]:
            tips.append(f"You have {len(me['plots'])} registered plot(s), listed in My account.")
    if client_token:
        try:
            c = require_client(client_token)
            name = name or c["name"]
            left = ("no plot limit" if c["plots_allowed"] is None
                    else f"{c['plots_allowed'] - c['plots_used']} plot(s) left")
            ends = datetime.fromisoformat(c["code_expires"])
            tips.append(f"You're logged in with a login code: {left}, valid until {when(ends)}.")
        except HTTPException:
            if page == "/register-plot":
                tips.append("Your code login has ended. Log in again with your code, or from My account.")
    if not (staff or account or client_token) and page in ("/register-plot", "/account", "/receipt"):
        tips.append("You're not logged in. Log in or create an account on My account (/account).")
    return name, tips[:4]


@router.get("/api/help/start")
def help_start(page: str = "/", x_account_token: str | None = Header(default=None),
               x_client_token: str | None = Header(default=None), x_staff_token: str | None = Header(default=None)):
    """Suggested questions for this page (plus the most-asked ones), and tips about the person's own things."""
    page = page_of(page)
    with connect() as conn:
        items = assistant.library(admin_answers(conn))
        popular = optional(conn, """
            SELECT answer_key FROM help_log
            WHERE answer_key IS NOT NULL AND helpful IS NOT FALSE AND created_at > NOW() - interval '30 days'
            GROUP BY answer_key ORDER BY COUNT(*) DESC LIMIT 5""", default=[])
    by_key = {i["key"]: i for i in items}
    keys = assistant.STARTERS.get(page, assistant.DEFAULT_STARTERS)[:3]
    for (k,) in popular:  # what other people ask most, after this page's own starters
        if k not in keys and k in by_key and len(keys) < 5:
            keys.append(k)
    name, tips = user_tips(page, x_account_token, x_client_token, x_staff_token)
    return {"suggestions": [short(by_key[k]) for k in keys if k in by_key],
            "name": name.split()[0] if name else None, "tips": tips}


@router.post("/api/help/ask")
def help_ask(body: HelpAskIn, request: Request):
    throttle(request, "help", limit=30, window=600)
    page = page_of(body.page)
    question = " ".join(body.question.split())
    with connect() as conn:
        items = assistant.library(admin_answers(conn))
        by_key = {i["key"]: i for i in items}
        found, score = None, 0.0
        if body.key and body.key in by_key:          # a suggestion was tapped
            found, score = by_key[body.key], 1.0
        elif body.error:                              # "help me with this error"
            found = assistant.for_error(body.error, items)
            score = 1.0 if found else 0.0
        matches = assistant.best_matches(question, items, top=4)
        if not found and matches and matches[0][0] >= assistant.MATCH_AT:
            score, found = matches[0]
        related = [short(i) for s, i in matches if i is not found and s >= 0.25][:3]
        if not related and not found:
            related = [short(by_key[k]) for k in assistant.STARTERS.get(page, assistant.DEFAULT_STARTERS)[:3]]
        feedback = secrets.token_urlsafe(16)
        row = optional(conn, """
            INSERT INTO help_log (question, page, answer_key, score, feedback_key)
            VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                       (question, page, found["key"] if found else None, round(score, 3), sha(feedback)))
    return {
        "answer": found["answer"] if found else NOT_SURE,
        "key": found["key"] if found else None,
        "sure": bool(found),
        "related": related,
        "log": {"id": row[0][0], "key": feedback} if row else None,
    }


@router.post("/api/help/feedback")
def help_feedback(body: HelpFeedbackIn):
    """👍 / 👎 on one answer. Only the person who asked holds the key, and they can rate it once."""
    with connect() as conn:
        rows = optional(conn, """
            UPDATE help_log SET helpful = %s
            WHERE id = %s AND feedback_key = %s AND helpful IS NULL RETURNING id""",
                        (body.helpful, body.id, sha(body.key)), default=None)
    if rows is None:
        raise HTTPException(status_code=503, detail="Feedback is not set up yet (run phase_k.sql).")
    if not rows:
        raise HTTPException(status_code=404, detail="That answer was already rated, or can't be found.")
    return {"ok": True}


# ---------- Admin: what people ask, and the answers admins add ----------
@router.get("/admin/help")
def admin_help_page():
    return FileResponse("admin-help.html")


def tables_missing():
    raise HTTPException(status_code=503, detail="The Help chat can't learn yet. Run phase_k.sql on this database.")


@router.get("/api/admin/help", dependencies=[Depends(require_admin)])
def admin_help():
    with connect() as conn:
        answers = optional(conn, """
            SELECT id, question, keywords, answer, active, updated_at FROM help_answers ORDER BY id DESC""")
        if answers is None:
            tables_missing()
        unanswered = conn.execute("""
            SELECT lower(question), COUNT(*), MAX(created_at), MAX(page) FROM help_log
            WHERE answer_key IS NULL GROUP BY lower(question) ORDER BY COUNT(*) DESC, MAX(created_at) DESC LIMIT 50""").fetchall()
        unhelpful = conn.execute("""
            SELECT lower(question), answer_key, COUNT(*), MAX(created_at) FROM help_log
            WHERE helpful IS FALSE GROUP BY lower(question), answer_key ORDER BY COUNT(*) DESC LIMIT 50""").fetchall()
        top = conn.execute("""
            SELECT answer_key, COUNT(*), COUNT(*) FILTER (WHERE helpful), COUNT(*) FILTER (WHERE helpful IS FALSE)
            FROM help_log WHERE answer_key IS NOT NULL AND created_at > NOW() - interval '30 days'
            GROUP BY answer_key ORDER BY COUNT(*) DESC LIMIT 15""").fetchall()
        totals = conn.execute("""
            SELECT COUNT(*), COUNT(*) FILTER (WHERE answer_key IS NOT NULL) FROM help_log
            WHERE created_at > NOW() - interval '30 days'""").fetchone()
    by_key = {i["key"]: i["question"] for i in assistant.library([a[:4] for a in answers])}
    iso = lambda t: t.isoformat() if t else None  # noqa: E731
    return {
        "asked_30d": totals[0], "answered_30d": totals[1], "built_in": len(assistant.BUILT_IN),
        "unanswered": [{"question": r[0], "times": r[1], "last_at": iso(r[2]), "page": r[3]} for r in unanswered],
        "unhelpful": [{"question": r[0], "answer": by_key.get(r[1], r[1]), "times": r[2], "last_at": iso(r[3])}
                      for r in unhelpful],
        "top": [{"answer": by_key.get(r[0], r[0]), "times": r[1], "up": r[2], "down": r[3]} for r in top],
        "answers": [{"id": r[0], "question": r[1], "keywords": r[2], "answer": r[3], "active": r[4],
                     "updated_at": iso(r[5])} for r in answers],
    }


@router.post("/api/admin/help/answers")
def add_answer(body: HelpAnswerIn, staff=Depends(require_admin)):
    with connect() as conn:
        row = optional(conn, """
            INSERT INTO help_answers (question, keywords, answer, active, staff_id)
            VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                       (body.question.strip(), body.keywords.strip(), body.answer.strip(), body.active, staff["id"]))
        if row is None:
            tables_missing()
        log_action(conn, staff, "added help answer", body.question.strip()[:80])
    return {"id": row[0][0]}


@router.put("/api/admin/help/answers/{answer_id}")
def edit_answer(answer_id: int, body: HelpAnswerIn, staff=Depends(require_admin)):
    with connect() as conn:
        row = optional(conn, """
            UPDATE help_answers SET question = %s, keywords = %s, answer = %s, active = %s, updated_at = %s
            WHERE id = %s RETURNING id""",
                       (body.question.strip(), body.keywords.strip(), body.answer.strip(), body.active,
                        datetime.now(timezone.utc), answer_id))
        if row is None:
            tables_missing()
        if not row:
            raise HTTPException(status_code=404, detail="No such answer.")
        log_action(conn, staff, "edited help answer", body.question.strip()[:80])
    return {"ok": True}
