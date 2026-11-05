"""The machine's local web UI: the agent's HTTP API, job handling and UI mode choice."""
import http.client
import json
import threading
import time
from pathlib import Path

import pytest
from test_usb import load_agent

UI_DIR = Path(__file__).resolve().parents[1] / "bootenv" / "agent" / "ui"
HW = {"mac": "aa:bb:cc:00:11:22", "ip": "10.0.0.50", "manufacturer": "Acer", "model": "TravelMate P414RN-54",
      "serial": "X1", "cpu": "Intel", "ram_mb": 8000, "boot_mode": "uefi", "secure_boot": True,
      "disks": [{"path": "/dev/nvme0n1", "size": 256060514304, "model": "KINGSTON", "transport": "nvme",
                 "removable": False}],
      "hardware_ids": ["PCI\\VEN_8086&DEV_1234"]}


@pytest.fixture()
def ui(monkeypatch):
    """A fresh agent with its web server on a random port. Yields (agent, request)."""
    agent = load_agent()
    calls = []

    def fake_api(method, path, body=None, timeout=30):
        calls.append((method, path, body))
        if path == "/register":
            return {"host_id": 1, "pin_required": True}
        if path == "/images":
            return [{"id": 7, "name": "Win11", "kind": "block", "os_family": "windows", "meta": {}}]
        return {}

    monkeypatch.setattr(agent, "api", fake_api)
    monkeypatch.setattr(agent, "collect_hardware", lambda: dict(HW))
    monkeypatch.setattr(agent, "UI_DIR", str(UI_DIR))
    server = agent.ThreadingHTTPServer(("127.0.0.1", 0), agent.UIHandler)
    port = server.server_address[1]
    agent.UI_HOSTS = {f"127.0.0.1:{port}"}
    threading.Thread(target=server.serve_forever, daemon=True).start()
    agent.connect()

    def request(method, path, body=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        payload = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, body=payload, headers={"Host": host or f"127.0.0.1:{port}",
                                                          "Content-Type": "application/json"})
        res = conn.getresponse()
        raw = res.read()
        ctype = res.getheader("Content-Type") or ""
        return res.status, (json.loads(raw) if "json" in ctype else raw.decode())

    agent.calls = calls
    yield agent, request
    server.shutdown()


def wait_for(cond, seconds=3):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_serves_the_page_and_state(ui):
    agent, req = ui
    status, page = req("GET", "/")
    assert status == 200 and "<title>mck-pxe</title>" in page
    assert req("GET", "/app.js")[0] == 200
    status, state = req("GET", "/api/state")
    assert state["online"] is True and state["pin_required"] is True
    assert state["hw"]["model"] == "TravelMate P414RN-54" and "hardware_ids" not in state["hw"]
    assert state["job"]["state"] == "idle" and state["busy"] is False


def test_rejects_other_hosts_and_path_traversal(ui):
    agent, req = ui
    assert req("GET", "/api/state", host="evil.example:8090")[0] == 403  # DNS rebinding
    assert req("POST", "/api/power", {"action": "reboot"}, host="evil.example")[0] == 403
    assert req("GET", "/../mck-agent")[0] == 404
    assert req("GET", "/%2e%2e/mck-agent")[0] == 404


def test_usb_job_runs_in_background_and_reports(ui, monkeypatch):
    agent, req = ui
    release = threading.Event()

    def fake_capture(hw, name, kind, disk, bitlocker_key=None):
        agent.job_log(f"capturing {disk} as {name}")
        agent.job_progress(40.0, "Capturing partition 3 40%")
        release.wait(3)
        return True, "Saved to the USB stick"

    monkeypatch.setattr(agent, "exec_usb_capture", fake_capture)
    status, body = req("POST", "/api/action", {"action": "usb-capture", "name": "Acer", "kind": "block",
                                               "disk": "/dev/nvme0n1"})
    assert status == 200 and body["message"] == "Started"
    assert wait_for(lambda: agent.JOB["progress"] == 40.0)
    state = req("GET", "/api/state")[1]
    assert state["busy"] and state["job"]["state"] == "running" and state["job"]["title"] == "Capture Acer to USB"
    assert state["job"]["log"] == ["capturing /dev/nvme0n1 as Acer"]

    # A second job, or switching to text mode, is refused while one runs
    assert req("POST", "/api/action", {"action": "usb-copy", "image_id": 7, "name": "x"})[0] == 409
    assert req("POST", "/api/ui/text")[0] == 409

    release.set()
    assert wait_for(lambda: agent.JOB["state"] == "done")
    assert agent.JOB["message"] == "Saved to the USB stick" and agent.JOB["after"] is None
    req("POST", "/api/job/dismiss")
    assert req("GET", "/api/state")[1]["job"]["state"] == "idle"


def test_deploy_counts_down_to_reboot_and_can_be_stopped(ui, monkeypatch):
    agent, req = ui
    monkeypatch.setattr(agent, "exec_usb_deploy", lambda *a: (True, "Completed"))
    req("POST", "/api/action", {"action": "usb-deploy", "dir": "/x", "disk": "/dev/nvme0n1", "after": "reboot"})
    assert wait_for(lambda: agent.JOB["state"] == "done")
    assert agent.JOB["after"] == "reboot" and agent.JOB["after_at"] > time.time()
    req("POST", "/api/after/cancel")
    assert agent.JOB["after"] is None


def test_cancel_stops_a_running_job(ui, monkeypatch):
    agent, req = ui

    def slow(*a):
        for i in range(200):
            agent.job_progress(i / 2, "working")  # raises Cancelled once asked
            time.sleep(0.01)
        return True, "finished"

    monkeypatch.setattr(agent, "exec_usb_copy", slow)
    req("POST", "/api/action", {"action": "usb-copy", "image_id": 7, "name": "Win11"})
    assert wait_for(lambda: agent.JOB["state"] == "running")
    req("POST", "/api/job/cancel")
    assert wait_for(lambda: agent.JOB["state"] == "failed")
    assert agent.JOB["message"] == "Cancelled"


def test_server_task_is_queued_with_pin_and_after(ui):
    agent, req = ui
    status, body = req("POST", "/api/action", {"action": "server-task", "type": "deploy", "image_id": 7,
                                               "disk": "/dev/nvme0n1", "drivers": "auto", "pin": "1234",
                                               "after": "poweroff"})
    assert status == 200 and "Queued" in body["message"]
    method, path, sent = agent.calls[-1]
    assert (method, path) == ("POST", "/tasks")
    assert sent == {"mac": HW["mac"], "type": "deploy", "image_id": 7, "disk": "/dev/nvme0n1", "drivers": "auto",
                    "pin": "1234", "after": "poweroff"}


def test_bad_requests_are_explained(ui):
    agent, req = ui
    status, body = req("POST", "/api/action", {"action": "usb-capture"})
    assert status == 400 and "name" in body["detail"]
    assert req("POST", "/api/action", {"action": "launch-missiles"})[0] == 400
    assert req("POST", "/api/nope")[0] == 404


def test_falls_back_to_text_mode(monkeypatch, tmp_path):
    agent = load_agent()
    monkeypatch.setattr(agent, "KIOSK_LOG", str(tmp_path / "kiosk.log"))
    monkeypatch.setattr(agent, "GRAPHICS_WAIT", 0)
    monkeypatch.setattr(agent, "try_run", lambda cmd: "")
    monkeypatch.setattr(agent, "cmdline_arg", lambda name: "text" if name == "mckpxe.ui" else None)
    assert agent.kiosk_available() == (False, "text mode was chosen at boot")
    monkeypatch.setattr(agent, "cmdline_arg", lambda name: None)
    monkeypatch.setattr(agent.shutil, "which", lambda tool: None if tool == "cage" else f"/usr/bin/{tool}")
    assert agent.kiosk_available() == (False, "cage isn't installed")
    monkeypatch.setattr(agent.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(agent.glob, "glob", lambda pattern: [])
    ok, reason = agent.kiosk_available()
    assert not ok and reason.startswith("no graphics device appeared")
    assert "=== no graphics device" in (tmp_path / "kiosk.log").read_text()  # diagnostics for the technician
    monkeypatch.setattr(agent.glob, "glob", lambda pattern: ["/dev/dri/card0"])
    assert agent.kiosk_available() == (True, "")


def test_waits_for_a_slow_graphics_driver(monkeypatch):
    agent = load_agent()
    ran = []
    monkeypatch.setattr(agent, "try_run", lambda cmd: ran.append(cmd[0]) or "")
    monkeypatch.setattr(agent, "read", lambda path, default="": "boot=live nomodeset quiet")
    monkeypatch.setattr(agent.time, "sleep", lambda s: None)
    checks = iter([[], [], [], [], ["/dev/dri/card0"]])  # appears on the 5th look
    monkeypatch.setattr(agent.glob, "glob", lambda pattern: next(checks))
    assert agent.wait_for_graphics(timeout=60) is True
    assert ran == ["udevadm", "modprobe"]  # settled udev, loaded simpledrm for safe graphics


class FakeKiosk:
    """Stands in for cage/firefox; records each launch's command and environment."""

    def __init__(self, agent, monkeypatch, tmp_path, runtimes):
        self.launches, self.commands, self.runtimes, self.clock = [], [], list(runtimes), [1000.0]
        monkeypatch.setattr(agent, "KIOSK_LOG", str(tmp_path / "kiosk.log"))
        monkeypatch.setattr(agent.os, "makedirs", lambda *a, **k: None)
        monkeypatch.setattr(agent.time, "time", lambda: self.clock[0])
        monkeypatch.setattr(agent.time, "sleep", lambda s: None)
        monkeypatch.setattr(agent, "try_run", lambda cmd: self.ran.append(cmd) or "")
        self.ran = []
        real_open, fake = open, self
        monkeypatch.setattr("builtins.open", lambda p, *a, **k: real_open(
            tmp_path / "user.js" if str(p).endswith("user.js") else p, *a, **k))

        class Proc:
            def __init__(self, cmd, env, stdout, stderr):
                fake.launches.append(env)
                fake.commands.append(cmd)

            def wait(self):
                fake.clock[0] += fake.runtimes.pop(0)  # how long this launch "ran"
                return 1

        monkeypatch.setattr(agent.subprocess, "Popen", Proc)


def test_graphics_fall_back_to_software_then_text(monkeypatch, tmp_path):
    agent = load_agent()
    fake = FakeKiosk(agent, monkeypatch, tmp_path, runtimes=[2, 3])  # both fail straight away
    reason = agent.run_kiosk()
    assert [e.get("WLR_RENDERER") for e in fake.launches] == [None, "pixman"]
    assert fake.launches[1]["LIBGL_ALWAYS_SOFTWARE"] == "1"
    # Uses the running seatd service; seatd-launch would clash with it
    assert ["systemctl", "start", "seatd.service"] in fake.ran
    assert all(cmd[0] == "cage" for cmd in fake.commands)
    assert all(e["LIBSEAT_BACKEND"] == "seatd" for e in fake.launches)
    assert reason == "graphics wouldn't start, even with software rendering"
    assert "starting kiosk (software rendering)" in (tmp_path / "kiosk.log").read_text()


def test_kiosk_restarts_after_a_crash_then_gives_up(monkeypatch, tmp_path):
    agent = load_agent()
    fake = FakeKiosk(agent, monkeypatch, tmp_path, runtimes=[600, 600, 600])  # ran a while, then crashed
    assert agent.run_kiosk() == "the graphical interface kept crashing (accelerated rendering)"
    assert len(fake.launches) == 3


def test_choosing_text_mode_is_not_a_failure(monkeypatch, tmp_path):
    agent = load_agent()
    FakeKiosk(agent, monkeypatch, tmp_path, runtimes=[600])
    agent.STATE["switch_to_text"] = True
    assert agent.run_kiosk() is None
