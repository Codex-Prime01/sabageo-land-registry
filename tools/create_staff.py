"""
Make an admin account, or reset one (new password, switched back on). Runs on your own computer,
so the very first admin never has to be created over the internet.

Run it from the project folder:  python tools/create_staff.py
It uses the database in .env (DATABASE_URL, or the local DB settings). It shows which database
host it is about to change and asks before saving.
"""
import getpass
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402
from psycopg.conninfo import conninfo_to_dict  # noqa: E402

from sabageo import config  # noqa: E402
from sabageo.security import hash_password  # noqa: E402


def ask(prompt, default=""):
    got = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return got or default


def main():
    host = conninfo_to_dict(config.DB).get("host", "localhost")
    print(f"Database host: {host}")

    username = ask("Username (letters, numbers, . _ -)").lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", username):
        sys.exit("Usernames are 3 to 40 letters, numbers, dots, dashes or underscores.")

    with psycopg.connect(config.DB) as conn:
        try:
            existing = conn.execute("SELECT name FROM staff WHERE username = %s", (username,)).fetchone()
        except psycopg.errors.UndefinedTable:
            sys.exit("This database has no staff table yet. Run phase_j.sql on it first.")

        if existing:
            print(f"'{username}' already exists ({existing[0]}). This will reset the password,")
            print("switch the account back on, and log it out everywhere.")
            name = existing[0]
        else:
            name = ask("Full name")
            if len(name) < 2:
                sys.exit("Please give a name.")

        password = getpass.getpass("Password (10+ characters, not shown): ")
        if len(password) < 10:
            sys.exit("Use at least 10 characters.")
        if getpass.getpass("Same password again: ") != password:
            sys.exit("The two passwords did not match. Nothing was saved.")

        if ask(f"Save admin {username} on {host}? yes/no", "no").lower() not in ("y", "yes"):
            sys.exit("Nothing was saved.")

        if existing:
            conn.execute("UPDATE staff SET password_hash = %s, active = TRUE WHERE username = %s",
                         (hash_password(password), username))
            conn.execute("DELETE FROM staff_sessions WHERE staff_id = (SELECT id FROM staff WHERE username = %s)",
                         (username,))
        else:
            conn.execute("INSERT INTO staff (username, name, password_hash) VALUES (%s, %s, %s)",
                         (username, name, hash_password(password)))
    print(f"Saved. {username} can now log in at /staff.")


if __name__ == "__main__":
    main()
