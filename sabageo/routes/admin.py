"""Admin dashboard: who registered what, payments, and the system's health. Admin key only."""
import logging

import psycopg
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from sabageo import config
from sabageo.db import connect
from sabageo.ledger import verify_chain
from sabageo.security import require_admin

router = APIRouter()
log = logging.getLogger("sabageo")


@router.get("/admin")
def admin_page():
    return FileResponse("admin.html")


@router.get("/admin/payments")
def admin_payments_page():
    # the page itself is plain HTML; everything it shows comes from admin-key APIs
    return FileResponse("admin-payments.html")


def optional(conn, query, params=(), default=None):
    """Run a query on a Phase H table; give `default` if that table is not created yet."""
    try:
        with conn.transaction():
            return conn.execute(query, params).fetchall()
    except psycopg.errors.UndefinedTable:
        log.warning("Phase H table missing: run phase_h.sql")
        return default


@router.get("/api/admin/overview", dependencies=[Depends(require_admin)])
def overview():
    with connect() as conn:
        regions = conn.execute(
            """
            SELECT r.code, r.name,
                   COUNT(p.id) FILTER (WHERE p.source = 'synthetic'),
                   COUNT(p.id) FILTER (WHERE p.source = 'field' AND p.status = 'registered' AND p.client_id IS NULL),
                   COUNT(p.id) FILTER (WHERE p.client_id IS NOT NULL),
                   COUNT(p.id) FILTER (WHERE p.status = 'reserved'),
                   COALESCE(SUM(p.area_m2) FILTER (WHERE p.status = 'registered'), 0)
            FROM regions r LEFT JOIN plots p ON p.region_code = r.code
            GROUP BY r.code, r.name, r.sort_order ORDER BY r.sort_order
            """
        ).fetchall()

        client_plots = conn.execute(
            """
            SELECT p.title_code, r.name, p.area_m2, p.registered_at,
                   p.owner_type, p.owner_name, p.owner_phone, p.owner_email,
                   c.name, c.client_type,
                   (SELECT COUNT(*) FROM photos ph WHERE ph.title_code = p.title_code)
            FROM plots p
            JOIN regions r ON r.code = p.region_code
            LEFT JOIN clients c ON c.id = p.client_id
            WHERE p.client_id IS NOT NULL
            ORDER BY p.id DESC LIMIT 500
            """
        ).fetchall()

        money = conn.execute(
            """
            SELECT COUNT(*) FILTER (WHERE p.status = 'confirmed'),
                   COALESCE(SUM(p.amount_ngn) FILTER (WHERE p.status = 'confirmed'), 0),
                   COUNT(*) FILTER (WHERE p.status = 'void'),
                   COUNT(*) FILTER (WHERE p.status = 'confirmed' AND c.client_type = 'individual'),
                   COUNT(*) FILTER (WHERE p.status = 'confirmed' AND c.client_type = 'corporate'),
                   COALESCE(SUM(p.amount_ngn) FILTER (WHERE p.status = 'confirmed'
                                                       AND p.created_at > NOW() - interval '30 days'), 0)
            FROM payments p JOIN clients c ON c.id = p.client_id
            """
        ).fetchone()
        methods = conn.execute(
            "SELECT method, COUNT(*) FROM payments WHERE status = 'confirmed' GROUP BY method ORDER BY 2 DESC"
        ).fetchall()

        # each payment's newest code decides its state
        codes = conn.execute(
            """
            WITH latest AS (
                SELECT DISTINCT ON (lc.payment_id) lc.*, p.status AS pay_status
                FROM login_codes lc JOIN payments p ON p.id = lc.payment_id
                ORDER BY lc.payment_id, lc.id DESC
            )
            SELECT COUNT(*) FILTER (WHERE NOT revoked AND pay_status = 'confirmed' AND expires_at > NOW()
                                    AND (plots_allowed IS NULL OR plots_used < plots_allowed)),
                   COUNT(*) FILTER (WHERE NOT revoked AND pay_status = 'confirmed' AND expires_at > NOW()
                                    AND plots_allowed IS NOT NULL AND plots_used >= plots_allowed),
                   COUNT(*) FILTER (WHERE NOT revoked AND pay_status = 'confirmed' AND expires_at <= NOW()),
                   COUNT(*) FILTER (WHERE revoked OR pay_status = 'void')
            FROM latest
            """
        ).fetchone()

        checks = optional(
            conn,
            """
            SELECT COUNT(*), COUNT(*) FILTER (WHERE status = 'RED FLAG'),
                   COUNT(*) FILTER (WHERE created_at > NOW() - interval '30 days'),
                   COUNT(*) FILTER (WHERE status = 'RED FLAG' AND created_at > NOW() - interval '30 days'),
                   COALESCE(SUM(overlap_m2), 0)
            FROM check_log
            """,
        )
        checks_by_day = optional(
            conn,
            """
            SELECT d::date, COUNT(c.id), COUNT(c.id) FILTER (WHERE c.status = 'RED FLAG')
            FROM generate_series(CURRENT_DATE - 13, CURRENT_DATE, interval '1 day') d
            LEFT JOIN check_log c ON c.created_at::date = d::date
            GROUP BY d ORDER BY d
            """,
            default=[],
        )
        onchain = optional(conn, "SELECT COUNT(*) FROM chain_titles WHERE action = 'record'")

        ledger = verify_chain(conn)
        anchor = conn.execute(
            "SELECT ledger_id, tx_hash, anchored_at FROM anchors ORDER BY id DESC LIMIT 1"
        ).fetchone()
        ledger_head = conn.execute("SELECT MAX(id) FROM ledger").fetchone()[0]

    c = checks[0] if checks else None
    return {
        "regions": [
            {"code": r[0], "name": r[1], "synthetic": r[2], "field": r[3], "client": r[4],
             "reserved": r[5], "area_m2": round(r[6], 1)}
            for r in regions
        ],
        "client_plots": [
            {"title_code": r[0], "region": r[1], "area_m2": round(r[2], 1) if r[2] else None,
             "registered_at": r[3].isoformat() if r[3] else None,
             "owner_type": r[4], "owner_name": r[5], "owner_phone": r[6], "owner_email": r[7],
             "paid_by": r[8], "paid_by_type": r[9], "photos": r[10]}
            for r in client_plots
        ],
        "payments": {
            "confirmed": money[0], "total_ngn": float(money[1]), "void": money[2],
            "individual": money[3], "corporate": money[4], "last_30_days_ngn": float(money[5]),
            "by_method": [{"method": m[0], "count": m[1]} for m in methods],
        },
        "codes": {"active": codes[0], "used_up": codes[1], "expired": codes[2], "revoked": codes[3]},
        "checks": None if c is None else {
            "total": c[0], "red_flags": c[1], "last_30_days": c[2], "red_flags_30_days": c[3],
            "overlap_m2_caught": round(c[4], 1),
            "by_day": [{"day": d[0].isoformat(), "checks": d[1], "red_flags": d[2]} for d in checks_by_day],
        },
        "ledger": {**ledger, "head": ledger_head},
        "last_anchor": {
            "ledger_id": anchor[0], "url": config.EXPLORER_TX + anchor[1], "anchored_at": anchor[2].isoformat(),
            "covers_latest": anchor[0] == ledger_head,
        } if anchor else None,
        "onchain_titles": onchain[0][0] if onchain else None,
        "provisional_prices": {k: v["amount"] for k, v in config.PLANS.items()},
    }
