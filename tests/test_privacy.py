"""Owner phone numbers and emails must never show on public pages or APIs."""
from conftest import body, login, new_payment, owner, rect

PHONE = "0809 555 1212"
EMAIL = "musa@example.com"


def test_owner_contact_never_public(client, admin):
    token = login(client, new_payment(client, admin)["code"])
    r = client.post("/client/register", json={**body(rect(), "OTH"), **owner()}, headers=token)
    code = r.json()["title_code"]

    public = [
        "/plots",
        "/api/registry",
        f"/plots/{code}/report",
        f"/plots/{code}/coordinates?crs=wgs84",
        "/regions",
    ]
    for path in public:
        text = client.get(path).text
        assert PHONE not in text and EMAIL not in text, path

    # the report may show the owner's NAME only
    assert client.get(f"/plots/{code}/report").json()["owner_name"] == "Musa Ali"
