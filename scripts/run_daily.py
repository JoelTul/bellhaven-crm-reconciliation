"""Unattended, read-only daily pipeline using persistent local state."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def load_environment(path):
    """Read only supported literal KEY=value settings; execute no shell code."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or key not in {"BELLHAVEN_API_TOKEN", "BELLHAVEN_BASE_URL", "BELLHAVEN_DATA_DIR"}:
            raise ValueError("Unsupported setting in .env; use literal BELLHAVEN settings only")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not os.environ.get(key):
            os.environ[key] = value


def main():
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    load_environment(ROOT / ".env")
    token = os.environ.get("BELLHAVEN_API_TOKEN", "").strip()
    if not token or token == "YOUR_PERSONAL_TOKEN_HERE":
        raise SystemExit("Configure BELLHAVEN_API_TOKEN in the environment or the ignored .env file first")
    from bellhaven.pipeline import main as pipeline
    data = Path(os.environ.get("BELLHAVEN_DATA_DIR", ROOT / "data")).resolve()
    sys.argv = ["bellhaven.pipeline", "--data-dir", str(data)]
    pipeline()


if __name__ == "__main__":
    main()
