"""Start this standalone server project: .venv/Scripts/python.exe run.py."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parent
INSPECTOR = "http://127.0.0.1:4040/api/tunnels"


class LaunchError(Exception):
    """Only explicitly safe, user-facing messages belong here."""


def read_json(url: str, timeout: float = 3) -> dict:
    with urlopen(url, timeout=timeout) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError("Expected object")
    return result


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def tunnel_url(data: dict, port: int) -> str | None:
    for tunnel in data.get("tunnels", []):
        if not isinstance(tunnel, dict):
            continue
        public = str(tunnel.get("public_url", ""))
        parsed = urlsplit(public)
        address = str(tunnel.get("config", {}).get("addr", ""))
        target = urlsplit(address if "://" in address else "http://" + address)
        try:
            matches = target.hostname in ("127.0.0.1", "localhost", "::1") and target.port == port
        except ValueError:
            matches = False
        if (matches and parsed.scheme == "https" and parsed.netloc and not parsed.username
                and not parsed.query and not parsed.fragment and parsed.path in ("", "/")):
            return public.rstrip("/")
    return None


def existing_tunnel(port: int) -> str | None:
    try:
        return tunnel_url(read_json(INSPECTOR), port)
    except Exception:
        return None


def child_env(values: dict) -> dict[str, str]:
    env = dict(os.environ)
    env.update({k: str(v) for k, v in values.items() if v is not None})
    env["PYTHONUNBUFFERED"] = "1"
    return env


class Settings:
    def __init__(self, root: Path):
        self.root = root
        values = self._read()
        self.api_port = self._port(values.get("API_PORT") or "3000")
        self.bot_port = self._port(values.get("BOT_PORT") or "8080")
        if self.api_port == self.bot_port:
            raise LaunchError("Порты API и бота должны различаться.")
        self.api_url = f"http://127.0.0.1:{self.api_port}"
        token = self._required(values, "BOT_TOKEN")
        key = self._required(values, "INTERNAL_API_KEY")
        if key == "replace-with-a-random-shared-secret":
            raise LaunchError("Замените пример INTERNAL_API_KEY в server/.env случайным секретом.")
        secret = self._required(values, "WEBHOOK_SECRET")
        if secret == key or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret) is None:
            raise LaunchError("WEBHOOK_SECRET должен быть отдельным секретом из букв, цифр, _ и -.")
        admin = (values.get("ADMIN_CHAT_ID") or "").strip()
        if admin and (re.fullmatch(r"-?[0-9]+", admin) is None or int(admin) == 0):
            raise LaunchError("ADMIN_CHAT_ID должен быть числом или оставаться пустым до настройки.")
        api_url = values.get("API_BASE_URL") or self.api_url
        if not self._local_url(api_url, self.api_port):
            raise LaunchError("API_BASE_URL в server/.env должен указывать на локальный API и API_PORT.")
        internal_url = values.get("BOT_INTERNAL_URL") or f"http://127.0.0.1:{self.bot_port}"
        if not self._local_url(internal_url, self.bot_port):
            raise LaunchError("BOT_INTERNAL_URL в server/.env должен указывать на локальный BOT_PORT.")
        # The API gets only the settings it uses, not the Telegram bot token.
        self.api = {"API_PORT": str(self.api_port), "PORT": str(self.api_port),
                    "INTERNAL_API_KEY": key, "BOT_INTERNAL_URL": internal_url}
        self.bot = {**values, "BOT_TOKEN": token, "INTERNAL_API_KEY": key,
                    "WEBHOOK_SECRET": secret, "BOT_PORT": str(self.bot_port),
                    "PORT": str(self.bot_port), "API_BASE_URL": self.api_url}
        self.bot_python = self._python()
        self.node = shutil.which("node")
        if not self.node:
            raise LaunchError("Не найден Node.js. Установите Node.js 24 и повторите запуск.")
        self.compiler = root / "api/node_modules/typescript/bin/tsc"
        if not self.compiler.is_file():
            raise LaunchError("Нет зависимостей API. Из server выполните npm.cmd --prefix api ci.")
        portable = root / "tools/ngrok.exe"
        self.ngrok = str(portable) if portable.is_file() else shutil.which("ngrok")

    def _read(self) -> dict:
        path = self.root / ".env"
        if not path.is_file():
            raise LaunchError("Создайте server/.env по примеру server/.env.example.")
        return dict(dotenv_values(path))

    def _python(self) -> str:
        relative = "Scripts/python.exe" if os.name == "nt" else "bin/python"
        path = self.root / ".venv" / relative
        if not path.is_file():
            raise LaunchError("Нет окружения server/.venv. Установите зависимости по server/README.md.")
        return str(path)

    @staticmethod
    def _local_url(value: str, port: int) -> bool:
        try:
            parsed = urlsplit(value)
            return (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")
                    and parsed.port == port and parsed.path in ("", "/")
                    and not parsed.query and not parsed.fragment and not parsed.username)
        except ValueError:
            return False

    @staticmethod
    def _required(values: dict, key: str) -> str:
        value = (values.get(key) or "").strip()
        if not value:
            raise LaunchError(f"Заполните {key} в server/.env.")
        return value

    @staticmethod
    def _port(value: str) -> int:
        if re.fullmatch(r"[0-9]+", value) is None or not 1 <= int(value) <= 65535:
            raise LaunchError("API_PORT и BOT_PORT должны быть числами от 1 до 65535.")
        return int(value)


class OwnedProcess:
    def __init__(self, name: str, process: subprocess.Popen, log):
        self.name, self.process, self.log = name, process, log

    def stop(self) -> None:
        if self.process.poll() is None:
            try:
                if os.name == "nt":
                    self.process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self.process.send_signal(signal.SIGINT)
                self.process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                if self.process.poll() is None:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                    else:
                        self.process.kill()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
        self.log.close()


class Launcher:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.owned: list[OwnedProcess] = []

    def start(self, name: str, command: list[str], env: dict | None = None) -> OwnedProcess:
        logdir = self.settings.root / ".tmp/launcher"
        logdir.mkdir(parents=True, exist_ok=True)
        logfile = (logdir / f"{name}.log").open("wb")
        try:
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            process = subprocess.Popen(command, cwd=self.settings.root, env=env,
                                       stdout=logfile, stderr=subprocess.STDOUT, creationflags=flags)
        except OSError:
            logfile.close()
            raise LaunchError(f"Не удалось запустить {name}. Проверьте установку программы.") from None
        item = OwnedProcess(name, process, logfile)
        self.owned.append(item)
        return item

    def wait_for(self, predicate, description: str, timeout: float = 35):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for item in self.owned:
                if item.process.poll() is not None:
                    raise LaunchError(f"Процесс {item.name} завершился. Подробности в .tmp/launcher/{item.name}.log (не публикуйте журналы).")
            try:
                value = predicate()
                if value:
                    return value
            except Exception:
                pass
            time.sleep(0.25)
        raise LaunchError(f"Не удалось дождаться: {description}. Проверьте .tmp/launcher/ и настройки.")

    def close(self) -> None:
        for item in reversed(self.owned):
            item.stop()
        self.owned.clear()

    def run(self) -> None:
        s = self.settings
        for port, name in ((s.api_port, "API"), (s.bot_port, "бота")):
            if port_open(port):
                raise LaunchError(f"Порт {port} уже занят. Остановите прежний процесс {name} перед единым запуском.")
        public = existing_tunnel(s.bot_port)
        if not public and port_open(4040):
            raise LaunchError("Порт 4040 занят другим ngrok/процессом. Остановите его или используйте правильный туннель к боту.")
        if not public and not s.ngrok:
            raise LaunchError("Не найден ngrok. Установите его или поместите ngrok.exe в tools/.")
        print("Собираю API...", flush=True)
        try:
            result = subprocess.run([s.node, str(s.compiler), "-p", str(s.root / "api/tsconfig.json")],
                                    cwd=s.root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            raise LaunchError("Не удалось выполнить сборку API. Проверьте Node.js и npm-зависимости.") from None
        if result.returncode:
            raise LaunchError("Ошибка сборки API. Выполните npm.cmd --prefix api run build для подробностей.")
        self.start("api", [s.node, str(s.root / "api/dist/server.js")], child_env(s.api))
        self.wait_for(lambda: read_json(s.api_url + "/health").get("status") == "ok", "запуск API")
        print("API запущен.", flush=True)
        if not public:
            self.start("ngrok", [s.ngrok, "http", str(s.bot_port), "--log=stdout"], child_env({}))
            public = self.wait_for(lambda: existing_tunnel(s.bot_port), "HTTPS-туннель ngrok")
            print("Ngrok запущен.", flush=True)
        else:
            print("Использую уже запущенный ngrok; при выходе он останется работать.", flush=True)
        set_key(s.root / ".env", "PUBLIC_BASE_URL", public, quote_mode="never")
        s.bot["PUBLIC_BASE_URL"] = public
        # Exact local API addresses avoid unrelated inherited PORT/API environment values.
        s.bot["API_BASE_URL"] = s.api_url
        bot_env = child_env(s.bot)
        self.start("bot", [s.bot_python, "-u", str(s.root / "run.py"), "--bot-child"], bot_env)

        def webhook_ready():
            if not port_open(s.bot_port):
                return False
            info = read_json("https://api.telegram.org/bot" + s.bot["BOT_TOKEN"] + "/getWebhookInfo", timeout=4)
            return info.get("ok") is True and info.get("result", {}).get("url") == public + "/telegram/webhook"

        self.wait_for(webhook_ready, "регистрация webhook Telegram", timeout=40)
        print("Сервер готов. Клиент запускается отдельно через client/start.bat.", flush=True)
        print("Для остановки сервера нажмите Ctrl+C.", flush=True)
        self.monitor()

    def monitor(self) -> None:
        while True:
            for item in self.owned:
                if item.process.poll() is not None:
                    raise LaunchError(f"Процесс {item.name} остановился. Проверьте его локальный журнал.")
            time.sleep(0.25)



def bot_child() -> None:
    if os.name == "nt":
        def interrupt(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGBREAK, interrupt)
    # aiohttp's finally blocks clean up webhook and HTTP sessions on KeyboardInterrupt.
    from bot.app.main import main as bot_main
    bot_main()


def main() -> int:
    if "--bot-child" in sys.argv:
        try:
            bot_child()
            return 0
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print("Бот не запущен:", type(exc).__name__, flush=True)
            return 1
    launcher = None
    try:
        launcher = Launcher(Settings(ROOT))
        launcher.run()
        return 0
    except KeyboardInterrupt:
        print("\nОстанавливаю сервер...", flush=True)
        return 0
    except LaunchError as exc:
        print("Ошибка:", exc, flush=True)
        return 1
    except Exception:
        print("Не удалось запустить сервер. Проверьте настройки и локальные журналы .tmp/launcher/.", flush=True)
        return 1
    finally:
        if launcher is not None:
            launcher.close()


if __name__ == "__main__":
    raise SystemExit(main())
