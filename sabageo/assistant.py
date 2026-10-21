"""The Help chat's brain. Free and offline: no AI service, no extra library.

It finds the best answer by comparing the words of a question with the words of every answer
(built-in ones below, plus the ones admins write on /admin/help). Rare words count more than
common ones, and small typos are forgiven. Questions it can't answer are saved, so an admin
can write the answer once and the chat knows it from then on.
"""
import difflib
import math
import re

from sabageo import config


def naira(amount):
    return "₦{:,.0f}".format(amount)


def _plans():
    ind, corp = config.PLANS["individual"], config.PLANS["corporate"]
    return (f"Individual: {naira(ind['amount'])} for one plot, valid {ind['days']} days.\n"
            f"Corporate: {naira(corp['amount'])} per month, no plot limit, valid {corp['days']} days.")


# Built-in answers. "errors" are bits of the site's own error messages: when a person hits one
# of those, the chat offers this answer before they even ask.
BUILT_IN = [
    {
        "key": "check", "pages": ["/"],
        "question": "How do I check if a plot overlaps another plot?",
        "keywords": "check plot overlap verify land free search corners coordinates test clash encroach",
        "answer": "1. Open the map (/).\n2. Type the plot's corners, one per line (at least 3).\n"
                  "3. Under More options, pick the coordinate type (lat/long or UTM zone).\n"
                  "4. Press Check plot.\nYou get 0 OVERLAP if it is clear, or a RED FLAG with the overlapping "
                  "plots, the overlap size in m² and the overlap zone shaded on the map. Checking is free, "
                  "no login needed.",
    },
    {
        "key": "redflag", "pages": ["/"],
        "question": "What does RED FLAG or 0 OVERLAP mean?",
        "keywords": "red flag zero overlap result meaning shaded zone clear flagged",
        "errors": ["overlaps a registered plot"],
        "answer": "RED FLAG means your plot covers part of a plot already in the registry. The list shows "
                  "which plots, and how many m² overlap; the red shaded area on the map is the overlap.\n"
                  "0 OVERLAP means no registered plot is inside your corners.\n"
                  "Plots that only touch along a boundary are not an overlap (we allow 10 cm for survey noise).",
    },
    {
        "key": "crs", "pages": ["/", "/register-plot", "/field-kit"],
        "question": "Which coordinate type should I choose?",
        "keywords": "coordinate type crs utm zone minna wgs84 latitude longitude easting northing datum "
                    "outside nigeria convert wrong",
        "errors": ["outside Nigeria", "could not be converted", "Unknown coordinate type", "Latitude must be"],
        "answer": "Use the type your survey plan is written in:\n"
                  "- Latitude, longitude (degrees): WGS84.\n"
                  "- Easting, northing (metres): UTM. Zone 31N is the far west (Lagos, Benin City), 32N the "
                  "middle (Abuja, Kano), 33N the east (Maiduguri, Biu).\n"
                  "- Old survey plans often use Minna: pick the Minna type with the same zone.\n"
                  "If the check says the plot lands outside Nigeria, the type or zone is wrong, or the "
                  "easting and northing are swapped.",
    },
    {
        "key": "corners", "pages": ["/", "/register-plot"],
        "question": "Why does it say my shape is invalid?",
        "keywords": "shape invalid corners order polygon crossing bowtie three corners",
        "errors": ["Shape is invalid", "at least 3 corners"],
        "answer": "Type the corners in order as you walk round the plot (clockwise or anticlockwise). "
                  "If you jump across, the lines cross and the shape is invalid. You need at least 3 corners. "
                  "You don't need to repeat the first corner at the end.",
    },
    {
        "key": "csv", "pages": ["/", "/field-kit", "/register-plot"],
        "question": "Can I upload my corners from a CSV or Excel file?",
        "keywords": "csv excel file upload import template spreadsheet field kit",
        "answer": "Yes. Get the template on the Field kit page (/field-kit), fill one corner per row, save it "
                  "as CSV, then use the CSV button on the map or on Register New Plot. The columns must be "
                  "in the same order as the coordinate type you picked.",
    },
    {
        "key": "plans", "pages": ["/payments", "/pay/individual", "/pay/corporate"],
        "question": "How much does it cost?",
        "keywords": "price cost fee plan how much naira individual corporate money charge expensive register plot",
        "answer": "Checking a plot on the map is free. Registering needs a token payment:\n" + "{plans}\n"
                  "These prices are provisional while the project is reviewed.",
    },
    {
        "key": "pay", "pages": ["/payments", "/pay/individual", "/pay/corporate", "/account"],
        "question": "How do I pay?",
        "keywords": "pay payment paystack card bank transfer online checkout buy token cash office",
        "errors": ["Online payment is not set up", "did not go through", "Could not reach Paystack"],
        "answer": "1. Create an account or log in (/account).\n2. Open Plans (/payments) and pick a plan.\n"
                  "3. Pay with Paystack (card or bank).\n4. You come back to your receipt with your login code.\n"
                  "You can also pay at the SABAGeo office; you get a receipt with a verification code, which "
                  "you can add to your account. If online payment is off, please pay SABAGeo directly.",
    },
    {
        "key": "register", "pages": ["/register-plot", "/account", "/receipt"],
        "question": "How do I register my plot after paying?",
        "keywords": "register plot title code after paying start registering new plot own land",
        "errors": ["Please log in with your login code"],
        "answer": "1. Go to My account (/account).\n2. On your receipt, press Register a plot (no code typing needed). "
                  "Or open Register New Plot (/register-plot) and type your login code.\n"
                  "3. Enter the corners and the owner's details, check, then register.\n"
                  "The server checks for overlaps again and gives you a title code like SABA-LAG-CLT-001.",
    },
    {
        "key": "lostcode", "pages": ["/account", "/register-plot", "/receipt"],
        "question": "I lost my login code. How do I get it back?",
        "keywords": "lost forgot code login code retrieve recover new code missing again",
        "errors": ["login code is not valid", "has no login code"],
        "answer": "Codes are stored scrambled, so nobody can show the old one again. Get a new one instead:\n"
                  "My account (/account) → your receipt → Get a new code. The old code stops working; "
                  "the new one keeps the same expiry date and plot limit.\n"
                  "Paid at the office? First add the receipt to your account with its receipt number and "
                  "verification code.",
    },
    {
        "key": "expired", "pages": ["/account", "/register-plot"],
        "question": "My code expired or has no plots left. What now?",
        "keywords": "expired code no plots left used up finished end validity days",
        "errors": ["has expired", "no plots left", "cancelled, so its code", "payment is void"],
        "answer": "An Individual code covers one plot and lasts {ind_days} days. A Corporate code lasts "
                  "{corp_days} days with no plot limit. Once it has expired or its plot is used, make a new "
                  "token payment on Plans (/payments). A new code from My account keeps the old expiry, so "
                  "it can't extend an expired one.",
    },
    {
        "key": "lock", "pages": ["/register-plot"],
        "question": "Why can't I check a different plot with my Individual code?",
        "keywords": "locked plot different another second use same individual code one plot bound",
        "errors": ["for one plot only"],
        "answer": "An Individual code is for ONE plot. It locks to the first plot you check or register with it. "
                  "Small fixes to the same plot (each corner within 3 m) are fine. A different plot needs its "
                  "own payment. Made a genuine mistake? Contact SABAGeo: an admin can unlock it.",
    },
    {
        "key": "account", "pages": ["/account"],
        "question": "What can I do in My account?",
        "keywords": "my account sign up create account login receipts my plots dashboard profile",
        "errors": ["Please log in to your account", "already an account with that email"],
        "answer": "My account (/account) shows your receipts and your plots. From there you can start "
                  "registering without typing a code, get a new code, add a receipt you paid in cash, and "
                  "change your password. Sign up with your email and a password of 8 or more characters.",
    },
    {
        "key": "password", "pages": ["/account"],
        "question": "I forgot my password.",
        "keywords": "forgot password reset change password wrong password cant login locked out",
        "errors": ["Wrong email or password", "current password is not right"],
        "answer": "There is no reset email yet. Contact SABAGeo: an admin checks it is really you and sets a "
                  "new password, then you change it in My account → Change password. Check your email for "
                  "typos first.",
    },
    {
        "key": "claim", "pages": ["/account", "/receipt"],
        "question": "How do I add a receipt I paid at the office to my account?",
        "keywords": "add receipt claim cash receipt verification code office paid offline",
        "errors": ["Receipt not found", "already in another account", "not in your account"],
        "answer": "My account (/account) → Add a receipt. Type the receipt number (SABA-RCPT-...) and the "
                  "verification code printed on it. If it says the receipt is in another account, contact SABAGeo.",
    },
    {
        "key": "photos", "pages": ["/register-plot", "/report"],
        "question": "How do beacon photos work?",
        "keywords": "photo beacon picture upload gps exif camera image jpg png",
        "errors": ["Photo is too big", "not a real image", "JPG or PNG", "photos, the most allowed"],
        "answer": "After registering, add up to 5 beacon photos to your plot (JPG or PNG, under 10 MB). Take them "
                  "with your phone's location ON: we read the photo's GPS and show how far it was taken from "
                  "the plot.",
    },
    {
        "key": "verify", "pages": ["/verify", "/report"],
        "question": "How do I verify a title code or a parcel report?",
        "keywords": "verify title code check genuine report qr scan fake real authentic",
        "errors": ["No title with that code"],
        "answer": "Open Verify a title (/verify) and type the title code, or scan the QR code on the parcel "
                  "report. It shows the plot and whether its record is unchanged since it was written.",
    },
    {
        "key": "report", "pages": ["/report", "/registry"],
        "question": "How do I get or print a parcel report?",
        "keywords": "parcel report print pdf document certificate download",
        "answer": "Open Parcel report (/report) and type the title code (or open a plot from the Registry). "
                  "Use your browser's Print to save it as PDF. It has a QR code that leads to the verify page.",
    },
    {
        "key": "ledger", "pages": ["/how-it-works", "/architecture", "/verify"],
        "question": "What is the ledger and blockchain part?",
        "keywords": "ledger blockchain hash chain polygon tamper anchor smart contract crypto secure",
        "answer": "Every registration is added to a hash-chained ledger: each record carries a fingerprint of "
                  "the one before, so a changed record shows up. The latest fingerprint can be anchored on "
                  "the Polygon Amoy TEST network. It proves a record hasn't changed since it was written, "
                  "not that the survey itself was right.",
    },
    {
        "key": "legal", "pages": ["/about", "/how-it-works"],
        "question": "Is this an official land registry?",
        "keywords": "official legal government title deed c of o certificate occupancy law valid",
        "answer": "No. SABAGeo is a working research prototype, not a legal land registry, and its title codes "
                  "are not certificates of occupancy. Use it to spot overlaps early, then follow the official "
                  "process with the land registry.",
    },
    {
        "key": "about", "pages": ["/about"],
        "question": "Who made SABAGeo?",
        "keywords": "who made built build creator owner about company sabageo naub research team contact",
        "answer": "SABAGeo is built by SABAGeo Technology Limited as research at NAUB, Borno State, on "
                  "decentralised land records. See About us (/about).",
    },
    {
        "key": "registry", "pages": ["/registry"],
        "question": "What are the plots on the map and in the Registry?",
        "keywords": "registry plots list map synthetic sample data real test",
        "answer": "The Registry (/registry) lists every registered plot. Plots marked synthetic are sample data "
                  "made for testing; the NAUB pilot plots are real field slots. Owner phone numbers and emails "
                  "are never shown publicly.",
    },
    {
        "key": "limits", "pages": [],
        "question": "It says too many tries. What should I do?",
        "keywords": "too many tries requests wait blocked limit",
        "errors": ["Too many wrong tries", "Too many requests"],
        "answer": "For safety, the site pauses after too many wrong codes or passwords. Wait ten minutes and "
                  "try again, carefully.",
    },
    {
        "key": "session", "pages": [],
        "question": "Why was I logged out?",
        "keywords": "logged out session ended expired login again",
        "errors": ["session has ended", "login has ended"],
        "answer": "Logins end by themselves for safety: a code session after 12 hours, an account after 7 days. "
                  "Just log in again.",
    },
    {
        "key": "tour", "pages": ["/"],
        "question": "Is there a guided tour of the map?",
        "keywords": "tour guide tutorial help start beginner show me how",
        "answer": "Yes. On the map, open the menu (☰) and press Take the tour. It shows each control one step "
                  "at a time and moves on only when you press Next.",
    },
    {
        "key": "admin", "pages": ["/staff", "/admin"],
        "question": "How do admins log in?",
        "keywords": "admin login staff dashboard username",
        "errors": ["log in as admin", "Wrong username or password"],
        "answer": "Admins log in on /staff with their username and password. New admins are added there by an "
                  "existing admin.",
    },
]

# Page starters: what people on that page most likely want to know.
STARTERS = {
    "/": ["check", "redflag", "crs", "tour"],
    "/payments": ["plans", "pay", "register"],
    "/account": ["register", "lostcode", "claim", "password"],
    "/register-plot": ["register", "lock", "crs", "photos"],
    "/receipt": ["register", "lostcode", "claim"],
    "/verify": ["verify", "ledger", "legal"],
    "/report": ["report", "verify", "photos"],
    "/registry": ["registry", "report", "check"],
}
DEFAULT_STARTERS = ["check", "plans", "register", "legal"]

STOP = set("a an the is are am be to of in on at for and or i me my we you your it this that do does did can "
           "could how what why when where which who will would should with from by as so if not no yes there "
           "have has had get got want need please pls hi hello hey sir ma just about wat abeg naw".split())
# different words people use for the same thing
SAME = {"cost": "price", "fee": "price", "charge": "price", "much": "price", "amount": "price",
        "pin": "code", "token": "code", "passcode": "code", "pword": "password", "pass": "password",
        "land": "plot", "parcel": "plot", "property": "plot", "clash": "overlap", "encroach": "overlap",
        "signup": "account", "registration": "register", "login": "log",
        "pic": "photo", "picture": "photo", "image": "photo", "lost": "forgot", "misplaced": "forgot",
        "certificate": "report", "paid": "pay", "paying": "pay", "payment": "pay"}
MATCH_AT = 0.42   # below this, the chat says it isn't sure


def words(text):
    out = []
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if w in STOP or len(w) < 2:
            continue
        w = SAME.get(w, w)
        for end in ("ing", "ed", "es", "s"):   # a rough stem: plots -> plot, checking -> check
            if len(w) > 4 and w.endswith(end):
                w = w[: -len(end)]
                break
        out.append(SAME.get(w, w))
    return out


def fill(answer):
    ind, corp = config.PLANS["individual"], config.PLANS["corporate"]
    return (answer.replace("{plans}", _plans())
            .replace("{ind_days}", str(ind["days"])).replace("{corp_days}", str(corp["days"])))


def library(extra=()):
    """Every answer: built-in ones, then the admins' ones (key 'a<id>')."""
    items = [dict(b, answer=fill(b["answer"])) for b in BUILT_IN]
    items += [{"key": f"a{r[0]}", "question": r[1], "keywords": r[2], "answer": r[3], "pages": [], "admin": True}
              for r in extra]
    return items


def best_matches(question, items, top=3):
    """[(score 0..1, item)] best first. Score = how much of the question's meaning an answer covers."""
    docs = [set(words(i["question"] + " " + i["keywords"])) for i in items]
    vocab = set().union(*docs) if docs else set()
    idf = {w: math.log(1 + len(docs) / (1 + sum(w in d for d in docs))) for w in vocab}
    asked = []
    for w in words(question):
        if w not in vocab:   # forgive typos: "pasword" -> "password"
            near = difflib.get_close_matches(w, vocab, n=1, cutoff=0.8)
            w = near[0] if near else w
        asked.append(w)
    asked = set(asked)
    if not asked:
        return []
    weight = lambda w: idf.get(w, 1.0)  # noqa: E731  (unknown words still count, so off-topic questions score low)
    total = sum(weight(w) for w in asked)
    scored = []
    for item, doc in zip(items, docs):
        hit = sum(weight(w) for w in asked & doc)
        if hit:
            score = hit / total * (1.1 if item.get("admin") else 1.0)  # admins' answers win a tie
            # tie-break: the answer whose own question is mostly about these words is the more exact one
            title = set(words(item["question"]))
            exact = sum(weight(w) for w in asked & title) / (sum(weight(w) for w in title) or 1)
            scored.append((min(score, 1.0), exact, item))
    scored.sort(key=lambda s: (-s[0], -s[1]))
    return [(s, item) for s, _, item in scored[:top]]


def for_error(message, items):
    """The built-in answer that explains one of the site's error messages, or None."""
    low = (message or "").lower()
    for item in items:
        if any(e.lower() in low for e in item.get("errors", [])):
            return item
    return None
