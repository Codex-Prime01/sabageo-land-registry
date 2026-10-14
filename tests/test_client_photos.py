"""Client beacon photos (Phase H, step 4)."""
import io

from PIL import Image

from conftest import E0, body, login, new_payment, owner, rect


def jpeg(lat=None, lon=None):
    """A small JPEG, optionally with a GPS tag (degrees, minutes, seconds)."""
    img = Image.new("RGB", (64, 48), (200, 160, 60))
    exif = img.getexif()
    if lat is not None:
        def dms(v):
            d = int(v); m = int((v - d) * 60); s = (v - d - m / 60) * 3600
            return (float(d), float(m), round(s, 4))
        exif.get_ifd(0x8825).update({1: "N", 2: dms(lat), 3: "E", 4: dms(lon)})
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif)
    return out.getvalue()


def setup_plot(client, admin, ref="PH-1"):
    token = login(client, new_payment(client, admin, reference=ref, plots_allowed=None, client_type="corporate")["code"])
    code = client.post("/client/register", json={**body(rect(), "OTH"), **owner()}, headers=token).json()["title_code"]
    return token, code


def upload(client, token, code, data, name="beacon.jpg", ctype="image/jpeg"):
    return client.post(f"/client/plots/{code}/photo", files={"file": (name, data, ctype)}, headers=token)


def test_photo_inside_plot(client, admin):
    token, code = setup_plot(client, admin)
    centre = client.get(f"/plots/{code}/report").json()["centroid"]
    r = upload(client, token, code, jpeg(*centre))
    assert r.status_code == 200, r.text
    assert r.json()["has_gps"] is True and r.json()["distance_m"] == 0
    mine = client.get("/api/client/plots", headers=token).json()[0]
    assert mine["photos"] == 1 and mine["photos_left"] == 4
    assert len(client.get(f"/plots/{code}/report").json()["photos"]) == 1


def test_photo_without_gps(client, admin):
    token, code = setup_plot(client, admin)
    r = upload(client, token, code, jpeg())
    assert r.status_code == 200 and r.json()["has_gps"] is False


def test_cannot_add_photo_to_someone_elses_plot(client, admin):
    _, code = setup_plot(client, admin, ref="PH-A")
    other = login(client, new_payment(client, admin, reference="PH-B")["code"])
    assert upload(client, other, code, jpeg()).status_code == 404


def test_cannot_add_photo_to_admin_plot(client, admin):
    from conftest import register
    code = register(client, admin, rect(e=E0 + 300))
    token, _ = setup_plot(client, admin)
    assert upload(client, token, code, jpeg()).status_code == 404


def test_photo_needs_login(client, admin):
    _, code = setup_plot(client, admin)
    r = client.post(f"/client/plots/{code}/photo", files={"file": ("b.jpg", jpeg(), "image/jpeg")})
    assert r.status_code == 401


def test_photo_limit(client, admin):
    token, code = setup_plot(client, admin)
    for _ in range(5):
        assert upload(client, token, code, jpeg()).status_code == 200
    r = upload(client, token, code, jpeg())
    assert r.status_code == 400 and "5 photos" in r.json()["detail"]
    assert client.get("/api/client/plots", headers=token).json()[0]["photos_left"] == 0


def test_rejects_non_images(client, admin):
    token, code = setup_plot(client, admin)
    assert upload(client, token, code, b"not an image at all", ctype="image/jpeg").status_code == 400
    assert upload(client, token, code, b"%PDF-1.4", name="x.pdf", ctype="application/pdf").status_code == 400
