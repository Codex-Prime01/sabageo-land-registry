"""
Online token payment through Paystack (test mode by default).

Flow:
  1. POST /api/pay/start      we save a pay_intent (plan, name, the amount WE expect), ask Paystack
                              for a checkout page, and send the customer there.
  2. GET  /pay/callback       Paystack sends the customer back. We ask Paystack's server whether the
                              payment really succeeded, for the right amount, then record it and show
                              the receipt with the login code.
  3. POST /api/pay/webhook    Paystack's server tells us directly (signed). Records the payment even if
                              the customer closed the browser. The code is shown when they come back.
Every step is safe to repeat: one pay_intent can only ever become one payment.
"""
import hashlib
import hmac
import json
import logging
import re
import secrets
from typing import Literal
from urllib.parse import quote

import psycopg
import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from sabageo import config
from sabageo.codes import create_payment, issue_login_code
from sabageo.db import connect
from sabageo.helpers import clean_contact
from sabageo.routes.verify import site_url
from sabageo.security import check_limit, record_fail, throttle

router = APIRouter()
log = logging.getLogger("sabageo")


class PayStart(BaseModel):
    plan: Literal["individual", "corporate"]
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=120)
    phone: str | None = Field(default=None, max_length=40)


def paystack(method, path, key, **kwargs):
    """Call Paystack's API. Raises HTTPException(502) with a readable message if it fails."""
    try:
        r = requests.request(method, config.PAYSTACK_API + path, timeout=20,
                             headers={"Authorization": "Bearer " + key}, **kwargs)
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        log.warning("Paystack call failed: %s", type(e).__name__)
        raise HTTPException(status_code=502, detail="Could not reach Paystack. Please try again.")
    if not r.ok or not data.get("status"):
        log.warning("Paystack said no (%s): %s", r.status_code, str(data.get("message"))[:120])
        raise HTTPException(status_code=502, detail="Paystack could not do that: " + str(data.get("message") or "unknown error")[:120])
    return data["data"]


@router.get("/api/pay/config")
def pay_config():
    key = config.paystack_key()
    return {"enabled": bool(key), "test_mode": bool(key and key.startswith("sk_test_"))}


@router.post("/api/pay/start")
def pay_start(body: PayStart, request: Request):
    throttle(request, "pay_start", limit=10, window=600)
    key = config.paystack_key()
    if not key:
        raise HTTPException(status_code=503, detail="Online payment is not set up yet. Please pay SABAGeo directly.")
    phone, email = clean_contact(body.phone, body.email)
    if not email:
        raise HTTPException(status_code=400, detail="Please enter your email address. Paystack sends the payment receipt there.")
    plan = config.PLANS[body.plan]
    amount_kobo = int(round(plan["amount"] * 100))
    reference = "SABA-PS-" + secrets.token_hex(8).upper()

    with connect() as conn:
        try:
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO pay_intents (reference, plan, name, email, phone, amount_kobo)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (reference, body.plan, body.name.strip(), email, phone, amount_kobo),
                )
        except psycopg.errors.UndefinedTable:
            raise HTTPException(status_code=503, detail="Online payment is not set up on this server yet (run phase_h.sql).")

    data = paystack("POST", "/transaction/initialize", key, json={
        "email": email,
        "amount": amount_kobo,
        "currency": "NGN",
        "reference": reference,
        "callback_url": site_url(request) + "/pay/callback",
        "metadata": {"plan": body.plan, "cancel_action": site_url(request) + "/payments"},
    })
    return {"authorization_url": data["authorization_url"], "reference": reference}


def confirm(conn, reference, key):
    """
    Make sure this pay_intent is paid and recorded. Asks Paystack's server, never the browser.
    Returns (receipt_no, verify_code, payment_id) or raises HTTPException.
    Lock the intent row first, so a callback and a webhook at the same moment cannot both record it.
    """
    intent = conn.execute(
        "SELECT plan, name, email, phone, amount_kobo, status, receipt_no FROM pay_intents WHERE reference = %s FOR UPDATE",
        (reference,),
    ).fetchone()
    if not intent:
        raise HTTPException(status_code=404, detail="We have no payment with that reference.")
    plan_code, name, email, phone, amount_kobo, status, receipt_no = intent

    if status != "paid":
        tx = paystack("GET", "/transaction/verify/" + quote(reference, safe=""), key)
        if tx.get("status") != "success":
            raise HTTPException(status_code=402, detail="Paystack says this payment did not go through (" + str(tx.get("status")) + ").")
        if tx.get("reference") != reference or int(tx.get("amount") or 0) != amount_kobo or tx.get("currency") != "NGN":
            log.error("Paystack amount/reference mismatch for %s", reference)
            raise HTTPException(status_code=400, detail="This payment does not match what was asked for. Please contact SABAGeo.")
        plan = config.PLANS[plan_code]
        try:
            with conn.transaction():
                made = create_payment(conn, name, plan_code, email, phone, amount_kobo / 100, "Paystack",
                                      reference, plan["days"], plan["plots"])
        except psycopg.errors.UniqueViolation:
            log.error("Paystack reference %s was already recorded by hand", reference)
            raise HTTPException(status_code=409, detail="This payment was already recorded. Please contact SABAGeo for your code.")
        receipt_no = made["receipt_no"]
        conn.execute(
            "UPDATE pay_intents SET status = 'paid', receipt_no = %s, paid_at = NOW() WHERE reference = %s",
            (receipt_no, reference),
        )
        # the code from create_payment is not kept anywhere: the callback issues the one the customer sees

    pay = conn.execute(
        "SELECT verify_code, id FROM payments WHERE receipt_no = %s", (receipt_no,)
    ).fetchone()
    return receipt_no, pay[0], pay[1]


@router.get("/pay/callback")
def pay_callback(request: Request, reference: str = "", trxref: str = ""):
    """Where Paystack sends the customer back. Shows the receipt with the login code, once."""
    reference = (reference or trxref).strip()
    key = config.paystack_key()
    if not key or not re.fullmatch(r"SABA-PS-[0-9A-F]{16}", reference):
        return RedirectResponse("/payments?pay=error", status_code=303)
    check_limit(request)
    try:
        with connect() as conn:
            receipt_no, verify, payment_id = confirm(conn, reference, key)
            shown = conn.execute(
                "SELECT code_shown FROM pay_intents WHERE reference = %s", (reference,)
            ).fetchone()[0]
            if shown:
                # the code was already shown once; it is only stored as a fingerprint, so send them to the receipt
                return RedirectResponse(f"/receipt/{receipt_no}?v={verify}&shown=1", status_code=303)
            # a fresh code replaces any earlier one (for example from the webhook), then it is shown exactly once
            plan = config.PLANS[conn.execute("SELECT plan FROM pay_intents WHERE reference = %s", (reference,)).fetchone()[0]]
            conn.execute("UPDATE login_codes SET revoked = TRUE WHERE payment_id = %s", (payment_id,))
            code, _ = issue_login_code(conn, payment_id,
                                       conn.execute("SELECT client_id FROM payments WHERE id = %s", (payment_id,)).fetchone()[0],
                                       plan["days"], plan["plots"])
            conn.execute("UPDATE pay_intents SET code_shown = TRUE WHERE reference = %s", (reference,))
    except HTTPException as e:
        record_fail(request)
        log.warning("Payment callback for %s failed: %s", reference, e.detail)
        return RedirectResponse("/payments?pay=" + ("failed" if e.status_code == 402 else "error"), status_code=303)
    return RedirectResponse(f"/receipt/{receipt_no}?v={verify}#code={quote(code)}", status_code=303)


@router.post("/api/pay/webhook")
async def pay_webhook(request: Request):
    """Paystack's server-to-server message. Only trusted if the signature matches our secret key."""
    key = config.paystack_key()
    raw = await request.body()
    given = request.headers.get("x-paystack-signature", "")
    if not key or not given or not hmac.compare_digest(hmac.new(key.encode(), raw, hashlib.sha512).hexdigest(), given):
        raise HTTPException(status_code=401, detail="Bad signature.")
    try:
        event = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Bad body.")
    reference = str((event.get("data") or {}).get("reference") or "")
    if event.get("event") != "charge.success" or not reference.startswith("SABA-PS-"):
        return {"ok": True, "ignored": True}
    try:
        with connect() as conn:
            confirm(conn, reference, key)
    except HTTPException as e:
        # answer 200 for payments we will never accept, so Paystack stops retrying; 5xx makes it retry
        if e.status_code >= 500:
            raise
        log.warning("Webhook for %s not recorded: %s", reference, e.detail)
        return {"ok": False}
    return {"ok": True}
