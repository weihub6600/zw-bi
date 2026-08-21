from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = PROJECT_ROOT / "VERSION"


def get_app_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


APP_VERSION = get_app_version()
