from pathlib import Path

from app.core.config import Settings


ROOT = Path(__file__).resolve().parents[2]


def _env_keys(path: Path) -> set[str]:
    return {
        line.split("=", 1)[0]
        for raw_line in path.read_text(encoding="utf-8").splitlines()
        if (line := raw_line.strip()) and not line.startswith("#") and "=" in line
    }


def test_env_example_matches_settings_fields():
    assert _env_keys(ROOT / ".env.example") == set(Settings.model_fields)
