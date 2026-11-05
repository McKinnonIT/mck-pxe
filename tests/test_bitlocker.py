"""Capturing BitLocker drives with the recovery key, entered at the machine only."""
import json
import subprocess

import pytest
from test_agent_web import ui  # noqa: F401  (fixture)
from test_usb import load_agent

agent = load_agent()
KEY = "-".join(["123453"] * 8)  # each group a multiple of 11, like real recovery keys


@pytest.mark.parametrize("text, expected", [
    (KEY, KEY),
    (KEY.replace("-", " "), KEY),
    (KEY.replace("-", ""), KEY),
    (KEY[:-1] + "4", None),  # last group no longer a multiple of 11: a typo
    ("123453-123453", None),
    ("", None),
])
def test_recovery_key_validation(text, expected):
    assert agent.normalise_recovery_key(text) == expected


class Log:
    def __init__(self):
        self.lines = []

    def log(self, line):
        self.lines.append(line)

    def send(self, *a, **k):
        pass


def test_unlock_uses_stdin_and_never_logs_the_key(monkeypatch):
    calls = []

    def fake_run(cmd, input=None, text=None, capture_output=None, **kw):
        calls.append((cmd, input))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(agent, "bitlocker_partitions", lambda disk: [{"path": "/dev/nvme0n1p3"}])
    monkeypatch.setattr(agent.subprocess, "run", fake_run)
    closed = []
    monkeypatch.setattr(agent, "try_run", lambda cmd: closed.append(cmd))
    r = Log()
    unlock = agent.BitLockerUnlock("/dev/nvme0n1", KEY.replace("-", " "), r)
    assert unlock.open() == {"/dev/nvme0n1p3": "/dev/mapper/mckpxe-bitlk-nvme0n1p3"}
    cmd, given = calls[0]
    assert cmd[:5] == ["cryptsetup", "open", "--type", "bitlk", "--readonly"] and "--key-file=-" in cmd
    assert given == KEY and KEY not in " ".join(cmd)  # on stdin, not the command line
    assert not any("123453" in line for line in r.lines)
    unlock.close()
    assert closed == [["cryptsetup", "close", "mckpxe-bitlk-nvme0n1p3"]]


def test_wrong_key_and_missing_key(monkeypatch):
    monkeypatch.setattr(agent, "bitlocker_partitions", lambda disk: [{"path": "/dev/nvme0n1p3"}])
    with pytest.raises(RuntimeError, match="recovery key"):
        agent.BitLockerUnlock("/dev/nvme0n1", None, Log()).open()
    monkeypatch.setattr(agent.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a[0], 2, "", "No key available"))
    with pytest.raises(RuntimeError, match="didn't unlock /dev/nvme0n1p3"):
        agent.BitLockerUnlock("/dev/nvme0n1", KEY, Log()).open()


def test_block_capture_reads_the_decrypted_view(monkeypatch):
    parts = [{"path": "/dev/nvme0n1p1", "partn": 1, "size": 200 << 20, "fstype": "vfat", "uuid": "a", "label": ""},
             {"path": "/dev/nvme0n1p3", "partn": 3, "size": 230 << 30, "fstype": "BitLocker", "uuid": "b",
              "label": ""}]
    table = {"partitiontable": {"label": "gpt", "partitions": [{"start": 2048, "size": 1}] * 2}}
    pipelines, shell = [], []
    monkeypatch.setattr(agent, "partitions", lambda disk: parts)
    monkeypatch.setattr(agent, "sh", lambda cmd, check=True: shell.append(cmd) or (
        json.dumps(table) if cmd[:2] == ["sfdisk", "-J"] else "512000000000"))
    monkeypatch.setattr(agent, "read", lambda *a, **k: "512")
    monkeypatch.setattr(agent, "run_pipeline", lambda script, steps: pipelines.append(script))
    monkeypatch.setattr(agent, "blkid_probe", lambda node: {"TYPE": "ntfs"})
    monkeypatch.setattr(agent, "target_disk", lambda path: {})
    monkeypatch.setattr(agent, "find_windows_partition", lambda disk, unlocked=None: None)
    monkeypatch.setattr(agent.BitLockerUnlock, "open", lambda self: {"/dev/nvme0n1p3": "/dev/mapper/x"})
    monkeypatch.setattr(agent.BitLockerUnlock, "close", lambda self: None)

    result = agent.capture_block({"disk": "/dev/nvme0n1", "upload_url": "http://s/up",
                                  "params": {"bitlocker_key": KEY}}, Log())
    assert any("partclone.ntfs -c -s /dev/mapper/x" in p for p in pipelines)  # decrypted, not the raw partition
    windows = result["meta"]["partitions"][1]
    assert windows["fstype"] == "ntfs" and windows["tool"] == "partclone.ntfs" and windows["decrypted"]
    assert result["os_family"] == "windows"


def test_capture_without_key_explains_both_options(monkeypatch):
    parts = [{"path": "/dev/nvme0n1p3", "partn": 3, "size": 1, "fstype": "BitLocker", "uuid": "", "label": ""}]
    monkeypatch.setattr(agent, "partitions", lambda disk: parts)
    monkeypatch.setattr(agent, "bitlocker_partitions", lambda disk: parts)
    monkeypatch.setattr(agent, "sh", lambda cmd, check=True: json.dumps(
        {"partitiontable": {"label": "gpt", "partitions": [{"start": 1, "size": 1}]}}))
    monkeypatch.setattr(agent, "read", lambda *a, **k: "512")
    with pytest.raises(RuntimeError) as e:
        agent.capture_block({"disk": "/dev/nvme0n1", "params": {}}, Log())
    assert "turn BitLocker off" in str(e.value) and "recovery key" in str(e.value)


def test_server_capture_key_stays_on_the_machine(ui):  # noqa: F811
    agent_ui, req = ui
    status, _ = req("POST", "/api/action", {"action": "server-task", "type": "capture", "name": "Acer",
                                            "kind": "block", "disk": "/dev/nvme0n1", "bitlocker_key": KEY})
    assert status == 200
    method, path, sent = agent_ui.calls[-1]
    assert path == "/tasks" and "bitlocker_key" not in sent and "123453" not in json.dumps(sent)
    assert agent_ui.STATE["bitlocker_keys"] == {"/dev/nvme0n1": KEY}
    # When the task comes back from the server to run, the key is added locally, once
    task = agent_ui.attach_local_key({"type": "capture", "disk": "/dev/nvme0n1", "params": {"name": "Acer"}})
    assert task["params"]["bitlocker_key"] == KEY and agent_ui.STATE["bitlocker_keys"] == {}


def test_invalid_key_is_refused(ui):  # noqa: F811
    agent_ui, req = ui
    status, body = req("POST", "/api/action", {"action": "usb-capture", "name": "x", "kind": "block",
                                               "disk": "/dev/nvme0n1", "bitlocker_key": "12345"})
    assert status == 400 and "recovery key" in body["detail"]
