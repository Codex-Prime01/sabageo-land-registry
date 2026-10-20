"""The shapes of the data the website sends."""
from typing import Literal

from pydantic import BaseModel, Field


class Corner(BaseModel):
    easting: float   # x: easting, or LONGITUDE when the type is wgs84
    northing: float  # y: northing, or LATITUDE when the type is wgs84


class NewPlot(BaseModel):
    corners: list[Corner]
    crs: str = "utm32"     # wgs84, utm31, utm32 or utm33
    region: str = "TST"    # TST = test area. NAUB = real pilot plots (uses the reserved slots)


class ClientPlot(NewPlot):
    """Register New Plot: the owner's details come with the corners."""
    owner_type: Literal["individual", "corporate"]
    owner_name: str = Field(min_length=2, max_length=120)
    owner_phone: str = Field(min_length=7, max_length=40)
    owner_email: str | None = Field(default=None, max_length=120)


class PaymentIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    client_type: Literal["individual", "corporate"]
    email: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    amount_ngn: float = Field(gt=0, lt=1_000_000_000)
    method: Literal["Bank transfer", "Card or POS", "Cash", "Other"]
    reference: str = Field(min_length=3, max_length=80)
    valid_days: int = Field(default=30, ge=1, le=365)
    plots_allowed: int | None = Field(default=None, ge=1, le=1000)


class ReissueIn(BaseModel):
    valid_days: int = Field(default=30, ge=1, le=365)


class LoginIn(BaseModel):
    code: str = Field(min_length=6, max_length=40)


class StaffLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)


class StaffIn(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9._-]{3,40}$")
    name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=10, max_length=200)


class PasswordIn(BaseModel):
    password: str = Field(min_length=10, max_length=200)


class PasswordChangeIn(PasswordIn):
    current: str = Field(min_length=1, max_length=200)


class SignupIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    password: str = Field(min_length=8, max_length=200)


class AccountLoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=200)


class ClaimIn(BaseModel):
    receipt_no: str = Field(min_length=5, max_length=40)
    verify_code: str = Field(min_length=4, max_length=20)
