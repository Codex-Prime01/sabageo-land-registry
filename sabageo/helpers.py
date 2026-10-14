import hashlib
import re

from fastapi import HTTPException


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def clean_contact(phone, email):
    phone = (phone or "").strip()
    email = (email or "").strip() or None
    if phone and not re.fullmatch(r"\+?[0-9 ()-]{7,20}", phone):
        raise HTTPException(status_code=400, detail="Please enter a valid phone number, like 0803 123 4567.")
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address, or leave it empty.")
    return phone or None, email
