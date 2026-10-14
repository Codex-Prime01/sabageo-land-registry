"""Login codes and payment records (shared by the admin form and online payments)."""
import re
import secrets
from datetime import datetime, timezone

from sabageo.helpers import sha

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0, O, 1, I or L, so codes are easy to read out


def normalise_code(code):
    text = re.sub(r"[^A-Z0-9]", "", code.upper())
    return text[4:] if text.startswith("SABA") else text


def code_hash(code):
    return sha(normalise_code(code))


def new_login_code():
    while True:
        chars = "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))
        if not chars.startswith("SABA"):
            return f"SABA-{chars[:4]}-{chars[4:8]}-{chars[8:]}"


def issue_login_code(conn, payment_id, client_id, days, plots_allowed, plots_used=0):
    code = new_login_code()
    expires = conn.execute("SELECT NOW() + make_interval(days => %s)", (days,)).fetchone()[0]
    conn.execute(
        """
        INSERT INTO login_codes (payment_id, client_id, code_hash, expires_at, plots_allowed, plots_used)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (payment_id, client_id, code_hash(code), expires, plots_allowed, plots_used),
    )
    return code, expires


def create_payment(conn, name, client_type, email, phone, amount, method, reference, days, plots_allowed):
    """
    Record a confirmed payment: the client, the receipt and a fresh login code.
    Raises psycopg.errors.UniqueViolation if the payment reference was already recorded.
    """
    client_id = conn.execute(
        "INSERT INTO clients (name, client_type, email, phone) VALUES (%s, %s, %s, %s) RETURNING id",
        (name.strip(), client_type, email, phone),
    ).fetchone()[0]
    n = conn.execute("SELECT nextval('receipt_seq')").fetchone()[0]
    receipt_no = f"SABA-RCPT-{datetime.now(timezone.utc).year}-{n:04d}"
    verify = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    payment_id = conn.execute(
        """
        INSERT INTO payments (client_id, receipt_no, verify_code, amount_ngn, method, reference)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (client_id, receipt_no, verify, round(amount, 2), method, reference.strip()),
    ).fetchone()[0]
    code, expires = issue_login_code(conn, payment_id, client_id, days, plots_allowed)
    return {"receipt_no": receipt_no, "verify_code": verify, "code": code, "expires_at": expires.isoformat()}
