"""Run this client independently with its own Python environment."""
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


def main() -> int:
    os.chdir(ROOT)
    # Only this client folder is needed, including when it is copied elsewhere.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if not (ROOT / ".env").is_file():
        print("Создайте .env из .env.example и задайте API_BASE_URL и BOT_USERNAME.")
        return 1
    try:
        import flet as ft
        from app.main import main as app_main
    except ModuleNotFoundError:
        print("Не установлены зависимости клиента. Выполните: .venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        return 1
    ft.run(app_main)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
