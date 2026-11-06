"""WIM capture skips files NTFS-3G can't read instead of failing the whole capture."""
import pytest
from test_usb import load_agent

agent = load_agent()

ERROR = """command failed:
3587 MiB scanned (21560 files, 3272 directories)
[ERROR] Failed to open NTFS file "/Users/defaultuser0/AppData/Local/TokenBroker/Cache/e1d3.tbres": Input/output error
ERROR: Exiting with error code 46:
       NTFS-3G encountered an error (check errno)."""


def test_unreadable_file_parsed_from_wimlib_error():
    path = "/Users/defaultuser0/AppData/Local/TokenBroker/Cache/e1d3.tbres"
    assert agent.unreadable_file(ERROR) == path
    assert agent.unreadable_file("command failed:\ncurl: (7) Failed to connect") is None


def test_config_keeps_wimlib_defaults_and_adds_skipped():
    cfg = agent.wim_config(["/Users/x/a b.tbres"])
    assert cfg.startswith("[ExclusionList]\n")
    assert "\\pagefile.sys\n" in cfg and "\\System Volume Information\n" in cfg
    assert "\\Users\\x\\a b.tbres\n" in cfg


class Log:
    def __init__(self):
        self.lines = []

    def log(self, line):
        self.lines.append(line)

    def progress(self, *a, **k):
        pass


@pytest.fixture
def capture(monkeypatch):
    class Unlock:
        def __init__(self, *a):
            pass

        def open(self):
            return {}

        def close(self):
            pass

    monkeypatch.setattr(agent, "BitLockerUnlock", Unlock)
    monkeypatch.setattr(agent, "find_windows_partition", lambda d, u: {"path": "/dev/x3", "source": "/dev/x3"})
    monkeypatch.setattr(agent, "storage_info", lambda d: {})
    monkeypatch.setattr(agent, "target_disk", lambda d: d)
    monkeypatch.setattr(agent, "Steps", lambda r, w: type("S", (), {"next": lambda s, m: None})())
    configs = []

    def run(errors):
        def fake(script, steps):
            path = script.split("--config=")[1].split()[0].strip("'")
            configs.append(open(path).read())
            if errors:
                raise RuntimeError(errors.pop(0))
        monkeypatch.setattr(agent, "run_pipeline", fake)
        r = Log()
        task = {"disk": "/dev/x", "params": {"name": "Win"}, "upload_url": "http://s/u"}
        return agent.capture_wim(task, r), r
    return run, configs


def test_capture_retries_without_unreadable_file(capture):
    run, configs = capture
    result, r = run([ERROR])
    assert len(configs) == 2 and "TokenBroker" not in configs[0] and "TokenBroker" in configs[1]
    assert result["meta"]["skipped_files"] == [agent.unreadable_file(ERROR)]
    assert any("Skipping" in line for line in r.lines)


def test_capture_still_fails_on_other_errors(capture):
    run, _ = capture
    with pytest.raises(RuntimeError, match="curl"):
        run(["command failed:\ncurl: (7) Failed to connect"])


def test_capture_gives_up_on_the_same_file_twice(capture):
    run, configs = capture
    with pytest.raises(RuntimeError, match="NTFS-3G"):
        run([ERROR, ERROR])
    assert len(configs) == 2
