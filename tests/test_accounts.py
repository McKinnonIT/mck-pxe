"""Local accounts: signing in, roles, managing accounts, and the boot USB's offline account."""
import pytest
from conftest import ADMIN_PASSWORD, console_headers

from mckpxe import auth, iso
from mckpxe.cli import reset_password

MAC = "aa:bb:cc:dd:ee:42"


@pytest.fixture
def host(client):
    client.post("/api/agent/register", json={"mac": MAC, "model": "Test"})


def login(c, username, password):
    return c.post("/api/auth/login", json={"username": username, "password": password})


def test_admin_console_needs_sign_in(anon):
    assert anon.get("/api/me").status_code == 401
    assert anon.get("/api/hosts").status_code == 401
    assert anon.get("/api/users").status_code == 401
    # Machines still boot and register without signing in
    assert anon.get("/api/agent/images").status_code == 200
    assert anon.get(f"/api/boot/grub/{MAC}.cfg").status_code == 200


def test_sign_in_and_out(anon):
    assert login(anon, "admin", "wrong-password").status_code == 401
    assert login(anon, "nobody", "whatever").status_code == 401
    r = login(anon, "Admin", ADMIN_PASSWORD)
    assert r.status_code == 200 and r.json()["role"] == "admin"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert anon.get("/api/me").json()["username"] == "admin"
    anon.post("/api/auth/logout")
    assert anon.get("/api/me").status_code == 401


def test_technician_only_signs_in_at_machines(client, anon, host):
    r = client.post("/api/users", json={"username": "tech1", "name": "Tech One", "role": "technician",
                                        "password": "tech-password"})
    assert r.status_code == 200, r.text
    assert login(anon, "tech1", "tech-password").status_code == 403
    h = console_headers(anon, MAC, "tech1", "tech-password")
    assert anon.post("/api/agent/images", headers=h, json={"mac": MAC, "name": "t", "kind": "wim"}).status_code == 200
    # A console token isn't an admin console session
    assert anon.get("/api/hosts", headers=h).status_code == 401


def test_account_rules(client):
    assert client.post("/api/users", json={"username": "Bad Name", "password": "long-enough"}).status_code == 400
    assert client.post("/api/users", json={"username": "short", "password": "short"}).status_code == 400
    assert client.post("/api/users", json={"username": "admin", "password": "long-enough"}).status_code == 409
    me = client.get("/api/me").json()
    # You can't lock yourself out
    assert client.patch(f"/api/users/{me['id']}", json={"role": "technician"}).status_code == 400
    assert client.patch(f"/api/users/{me['id']}", json={"enabled": False}).status_code == 400
    assert client.delete(f"/api/users/{me['id']}").status_code == 400
    users = client.get("/api/users").json()
    assert all("password_hash" not in u for u in users)


def test_disabling_or_resetting_signs_the_user_out(client, anon, host):
    uid = client.post("/api/users", json={"username": "tech2", "role": "technician",
                                          "password": "tech-password"}).json()["id"]
    h = console_headers(anon, MAC, "tech2", "tech-password")
    body = {"mac": MAC, "type": "capture", "name": "x", "disk": "/dev/sda"}
    client.patch(f"/api/users/{uid}", json={"password": "new-password!"})
    assert anon.post("/api/agent/tasks", headers=h, json=body).status_code == 401
    h = console_headers(anon, MAC, "tech2", "new-password!")
    client.patch(f"/api/users/{uid}", json={"enabled": False})
    assert anon.post("/api/agent/tasks", headers=h, json=body).status_code == 401
    assert anon.post("/api/agent/login", json={"mac": MAC, "username": "tech2",
                                                "password": "new-password!"}).status_code == 401
    assert client.delete(f"/api/users/{uid}").status_code == 200


def test_change_my_password(client, anon):
    uid = client.post("/api/users", json={"username": "admin2", "role": "admin",
                                          "password": "admin2-password"}).json()["id"]
    assert login(anon, "admin2", "admin2-password").status_code == 200
    r = anon.post("/api/me/password", json={"current": "wrong", "new": "brand-new-pass"})
    assert r.status_code == 400
    r = anon.post("/api/me/password", json={"current": "admin2-password", "new": "brand-new-pass"})
    assert r.status_code == 200
    assert anon.get("/api/me").status_code == 200  # this session stays signed in
    assert login(anon, "admin2", "brand-new-pass").status_code == 200
    client.delete(f"/api/users/{uid}")


def test_too_many_failures_are_throttled(anon, monkeypatch):
    monkeypatch.setattr(auth, "_fails", {})
    for _ in range(auth.MAX_FAILS):
        assert login(anon, "throttle-me", "wrong").status_code == 401
    assert login(anon, "throttle-me", "wrong").status_code == 429


def test_reset_password_from_the_shell(anon):
    password = reset_password("rescue")
    assert login(anon, "rescue", password).json()["role"] == "admin"


def test_usb_account_goes_into_the_iso_as_a_hash(client, data_dir):
    assert client.get("/api/settings/usb-account").json() is None
    r = client.put("/api/settings/usb-account", json={"username": "usbtech", "password": "usb-password"})
    assert r.status_code == 200 and r.json()["username"] == "usbtech"
    args = iso.kernel_args()
    assert "usb-password" not in args
    account = next(a for a in args.split() if a.startswith("mckpxe.account="))
    username, hashed = account.split("=", 1)[1].split(":", 1)
    assert username == "usbtech" and auth.verify_password("usb-password", hashed)
    assert "$" not in hashed  # GRUB would expand it
    assert "usb-password" not in (data_dir / "system" / "usb-account.json").read_text()
    client.delete("/api/settings/usb-account")
    assert "mckpxe.account" not in iso.kernel_args()


def test_password_hash_round_trip():
    h = auth.hash_password("correct horse")
    assert auth.verify_password("correct horse", h)
    assert not auth.verify_password("Correct horse", h)
    assert not auth.verify_password("x", "not-a-hash")
