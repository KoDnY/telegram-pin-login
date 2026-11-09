"""Launcher coordination tests: no network, GUI, credentials or child processes."""
from pathlib import Path
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run


@pytest.fixture
def project(tmp_path):
    (tmp_path / ".env").write_text(
        "API_PORT=3000\nBOT_PORT=8080\nBOT_TOKEN=fake-token\n"
        "INTERNAL_API_KEY=test-shared\nWEBHOOK_SECRET=other-secret\n"
        "API_BASE_URL=http://127.0.0.1:3000\nBOT_INTERNAL_URL=http://127.0.0.1:8080\n"
        "PUBLIC_BASE_URL=old-address\n", encoding="utf-8")
    rel = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    python = tmp_path / ".venv" / rel
    python.parent.mkdir(parents=True)
    python.touch()
    compiler = tmp_path / "api/node_modules/typescript/bin/tsc"
    compiler.parent.mkdir(parents=True)
    compiler.touch()
    return tmp_path


def settings(project):
    with patch("run.shutil.which", side_effect=lambda name: "/fake/" + name):
        return run.Settings(project)


def test_settings_old_url_is_not_required_because_tunnel_will_replace_it(project):
    s = settings(project)
    assert s.api_port == 3000 and s.bot_port == 8080
    assert s.bot["PUBLIC_BASE_URL"] == "old-address"


def test_missing_env_has_actionable_error(project):
    (project / ".env").unlink()
    with pytest.raises(run.LaunchError, match=r"\.env"):
        settings(project)


@pytest.mark.parametrize("line,error", [
    ("INTERNAL_API_KEY=", "INTERNAL_API_KEY"),
    ("WEBHOOK_SECRET=test-shared", "WEBHOOK_SECRET"),
    ("BOT_TOKEN=", "BOT_TOKEN"),
    ("API_BASE_URL=http://localhost:9999", "API_BASE_URL"),
    ("BOT_INTERNAL_URL=http://localhost:9999", "BOT_INTERNAL_URL"),
    ("BOT_PORT=3000", "Порты"),
])
def test_invalid_settings_do_not_leak_values(project, line, error):
    p = project / ".env"
    p.write_text(p.read_text(encoding="utf-8") + "\n" + line + "\n", encoding="utf-8")
    with pytest.raises(run.LaunchError, match=error) as exc:
        settings(project)
    assert "fake-token" not in str(exc.value)
    assert "test-shared" not in str(exc.value)


def test_server_has_no_client_dependency(project):
    s = settings(project)
    assert s.bot_python.endswith("python.exe" if os.name == "nt" else "python")
    assert not hasattr(s, "client")
    assert not hasattr(s, "client_python")
    assert not (project / "client").exists()


def tunnel(public="https://test.ngrok-free.app", address="http://localhost:8080"):
    return {"public_url": public, "config": {"addr": address}}


def test_select_only_https_correct_local_port():
    d = {"tunnels": [tunnel("https://wrong.ngrok-free.app", "http://localhost:3000"),
                       tunnel("http://bad.ngrok-free.app"),
                       tunnel(address="http://elsewhere.invalid:8080"), tunnel()]}
    assert run.tunnel_url(d, 8080) == "https://test.ngrok-free.app"
    assert run.tunnel_url({"tunnels": [tunnel(address="http://localhost:invalid")]}, 8080) is None


def test_existing_tunnel_failure_is_safe():
    with patch("run.read_json", side_effect=OSError("token must not leak")):
        assert run.existing_tunnel(8080) is None


def test_external_ports_are_never_killed(project):
    launcher = run.Launcher(settings(project))
    with patch("run.port_open", return_value=True), patch.object(launcher, "start") as start:
        with pytest.raises(run.LaunchError, match="3000"):
            launcher.run()
        start.assert_not_called()
        assert launcher.owned == []


def test_close_only_owned_processes_in_reverse_order():
    launcher = run.Launcher(SimpleNamespace())
    order = []
    a, b = Mock(), Mock()
    a.stop.side_effect = lambda: order.append("api")
    b.stop.side_effect = lambda: order.append("bot")
    launcher.owned = [a, b]
    launcher.close()
    assert order == ["bot", "api"]
    assert launcher.owned == []


def test_wait_detects_child_exit_without_leaking_logs():
    launcher = run.Launcher(SimpleNamespace())
    launcher.owned = [SimpleNamespace(name="bot", process=SimpleNamespace(poll=lambda: 1))]
    with pytest.raises(run.LaunchError, match="bot"):
        launcher.wait_for(lambda: False, "test")


def test_main_cleans_up_on_startup_failure():
    launcher = Mock()
    launcher.run.side_effect = run.LaunchError("safe failure")
    with patch("run.Settings"), patch("run.Launcher", return_value=launcher), patch.object(sys, "argv", ["run.py"]):
        assert run.main() == 1
    launcher.close.assert_called_once()


def test_success_reuses_external_ngrok_updates_url_and_tracks_only_own(project):
    s = settings(project)
    launcher = run.Launcher(s)
    names = []
    process = SimpleNamespace(process=SimpleNamespace(poll=lambda: None, returncode=None))
    def start(name, command, env):
        names.append(name)
        return process
    with patch("run.port_open", return_value=False), \
         patch("run.existing_tunnel", return_value="https://new.ngrok-free.app"), \
         patch("run.subprocess.run", return_value=SimpleNamespace(returncode=0)), \
         patch.object(launcher, "start", side_effect=start), \
         patch.object(launcher, "wait_for", side_effect=[True, True]), \
         patch.object(launcher, "monitor") as monitor:
        launcher.run()
    assert names == ["api", "bot"]
    monitor.assert_called_once()
    assert run.dotenv_values(project / ".env")["PUBLIC_BASE_URL"] == "https://new.ngrok-free.app"
    assert s.bot["PUBLIC_BASE_URL"] == "https://new.ngrok-free.app"


def test_build_failure_starts_nothing(project):
    launcher = run.Launcher(settings(project))
    with patch("run.port_open", return_value=False), patch("run.existing_tunnel", return_value="https://test.ngrok-free.app"), \
         patch("run.subprocess.run", return_value=SimpleNamespace(returncode=1)), patch.object(launcher, "start") as start:
        with pytest.raises(run.LaunchError, match="сборки"):
            launcher.run()
        start.assert_not_called()
