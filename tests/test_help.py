"""The Help chat: answers, suggestions, tips about the asker's own things, and learning from questions."""
from conftest import login, new_payment
from test_accounts import claim, signup

from sabageo import assistant


def ask(client, question, headers=None, **extra):
    r = client.post("/api/help/ask", json={"question": question, "page": "/", **extra}, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()


def test_matcher_understands_everyday_questions():
    items = assistant.library()
    for question, key in [("how much is it", "plans"), ("i forgot my pasword", "password"),
                          ("how do i register my plot", "register"), ("can i upload excel", "csv"),
                          ("which utm zone for maiduguri", "crs"), ("is this legal", "legal"),
                          ("can i use my code for another plot", "lock")]:
        assert assistant.best_matches(question, items)[0][1]["key"] == key, question
    assert assistant.best_matches("whats the weather today", items) == []


def test_answer_uses_the_real_prices(client):
    d = ask(client, "How much does it cost?")
    assert d["sure"] and d["key"] == "plans" and "₦15,000" in d["answer"] and "₦200,000" in d["answer"]


def test_suggestions_change_with_the_page(client):
    home = client.get("/api/help/start", params={"page": "/"}).json()
    pay = client.get("/api/help/start", params={"page": "/pay/individual"}).json()
    assert home["suggestions"][0]["key"] == "check" and pay["suggestions"][0]["key"] == "plans"
    assert home["tips"] == [] and home["name"] is None


def test_unknown_question_is_saved_for_admins_who_teach_the_chat(client, admin, db):
    d = ask(client, "Can I get a refund?")
    assert not d["sure"] and d["related"]  # says it's not sure, offers other questions
    seen = client.get("/api/admin/help", headers=admin).json()
    assert seen["unanswered"][0]["question"] == "can i get a refund?" and seen["asked_30d"] == 1

    r = client.post("/api/admin/help/answers", headers=admin,
                    json={"question": "Can I get a refund?", "keywords": "refund money back", "answer": "Contact SABAGeo."})
    assert r.status_code == 200
    d = ask(client, "how do i get my money back, refund")
    assert d["sure"] and d["answer"] == "Contact SABAGeo." and d["key"] == f"a{r.json()['id']}"
    assert db.execute("SELECT action FROM staff_log").fetchone()[0] == "added help answer"

    # turned off: the chat stops using it
    client.put(f"/api/admin/help/answers/{r.json()['id']}", headers=admin,
               json={"question": "Can I get a refund?", "keywords": "refund", "answer": "Contact SABAGeo.", "active": False})
    assert not ask(client, "refund")["sure"]


def test_explains_the_error_the_page_showed(client):
    msg = "This login code is for one plot only, and it is already used for the plot you first checked."
    d = ask(client, "I got this message: " + msg, error=msg)
    assert d["key"] == "lock"


def test_feedback_only_once_and_only_with_the_key(client, db):
    d = ask(client, "what is the blockchain part")
    log = d["log"]
    assert client.post("/api/help/feedback", json={"id": log["id"], "key": "wrong-key-123", "helpful": False}).status_code == 404
    assert client.post("/api/help/feedback", json={**log, "helpful": False}).status_code == 200
    assert client.post("/api/help/feedback", json={**log, "helpful": True}).status_code == 404
    assert db.execute("SELECT helpful FROM help_log").fetchone()[0] is False


def test_tips_about_my_own_receipt(client, admin):
    acct = signup(client)
    pay = new_payment(client, admin)
    assert claim(client, acct, pay).status_code == 200
    d = client.get("/api/help/start", params={"page": "/account"}, headers=acct).json()
    assert d["name"] == "Ada" and pay["receipt_no"] in d["tips"][0] and "1 plot(s) left" in d["tips"][0]
    # logged in with the code itself
    code = client.get("/api/help/start", params={"page": "/register-plot"}, headers=login(client, pay["code"])).json()
    assert any("login code" in t for t in code["tips"])


def test_admin_help_needs_an_admin(client):
    assert client.get("/api/admin/help").status_code == 401
    assert client.post("/api/admin/help/answers", json={"question": "Hello there", "answer": "Hi there"}).status_code == 401


def test_works_without_phase_k(client, admin, db):
    """Before phase_k.sql runs (e.g. Neon), the chat must still answer."""
    db.execute("ALTER TABLE help_log RENAME TO help_log_off")
    db.execute("ALTER TABLE help_answers RENAME TO help_answers_off")
    try:
        d = ask(client, "how much is it")
        assert d["sure"] and d["log"] is None
        assert client.get("/api/help/start").status_code == 200
        assert client.get("/api/admin/help", headers=admin).status_code == 503
    finally:
        db.execute("ALTER TABLE help_log_off RENAME TO help_log")
        db.execute("ALTER TABLE help_answers_off RENAME TO help_answers")
