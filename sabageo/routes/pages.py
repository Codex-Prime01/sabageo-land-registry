"""The HTML pages."""
from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()


def page(name):
    return FileResponse(name)


@router.get("/")
def home():
    return page("index.html")


@router.get("/health")
def health():
    # tiny route for the keep-awake pinger; it does not touch the database
    return {"ok": True}


@router.get("/about")
def about_page():
    return page("about.html")


@router.get("/how-it-works")
def how_it_works_page():
    return page("how-it-works.html")


@router.get("/architecture")
def architecture_page():
    return page("architecture.html")


@router.get("/registry")
def registry_page():
    return page("registry.html")


@router.get("/report")
@router.get("/report/{title_code}")
def report_page(title_code: str = ""):
    return page("report.html")


@router.get("/payments")
def payments_page():
    return page("payments.html")


@router.get("/receipt")
@router.get("/receipt/{receipt_no}")
def receipt_page(receipt_no: str = ""):
    return page("receipt.html")


@router.get("/register-plot")
def register_plot_page():
    return page("register-plot.html")


@router.get("/field-kit")
def field_kit_page():
    return page("field-kit.html")
