"""Application settings.

API keys are managed in the app (stored in the OS credential store, see
keystore.py); keys in environment variables or a `.env` file also work.
Non-secret preferences (e.g. the chosen model) live in
`<data_dir>/settings.json`. Environment variables win over settings.json.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass(frozen=True)
class GeminiKey:
    """One API key and the Google Cloud project it belongs to.

    Keys sharing a project share that project's quota and rate limiter;
    adding keys to the same project never increases throughput.
    """

    label: str
    project: str
    api_key: str = field(repr=False)


# Known per-model limits per Google Cloud project, as (requests/minute, requests/day).
DEFAULT_MODEL_LIMITS: dict[str, tuple[int, int]] = {
    "gemini-3.5-flash-lite": (15, 500),
    "gemini-3.8-flash": (15, 20),
}


@dataclass
class Settings:
    data_dir: Path = Path("workspace")

    # Rendering
    render_dpi: int = 150
    page_image_format: str = "png"  # png (lossless) or jpg

    # Gemini
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_timeout_s: int = 180
    gemini_temperature: float = 0.4
    gemini_max_attempts: int = 4
    # Parallel requests. A page takes several seconds, so 3 in flight are needed to reach
    # 15 requests/minute; the rate limiter still never exceeds the per-minute limit.
    gemini_concurrency: int = 3
    gemini_default_rpm: int = 15
    gemini_default_rpd: int = 0  # 0 = no app-side daily cap
    gemini_model_limits: dict[str, tuple[int, int]] = field(default_factory=lambda: dict(DEFAULT_MODEL_LIMITS))
    gemini_project_rpm: dict[str, int] = field(default_factory=dict)
    gemini_keys: list[GeminiKey] = field(default_factory=list, repr=False)

    # Generation
    questions_per_page: int = 5  # legacy setting; document-level limits control generation
    abstain_distractor_ratio: float = 0.30

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bndocvqa.sqlite"

    @property
    def originals_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def pages_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.originals_dir, self.pages_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    def secret_values(self) -> list[str]:
        return [k.api_key for k in self.gemini_keys if k.api_key]

    def save_preferences(self) -> None:
        """Persist the user-editable, non-secret settings."""
        prefs = {"gemini_model": self.gemini_model}
        (self.data_dir / "settings.json").write_text(json.dumps(prefs, ensure_ascii=False, indent=2),
                                                     encoding="utf-8")


def parse_dotenv(path: Path) -> dict[str, str]:
    """Minimal .env parser: KEY=VALUE lines, # comments, optional quotes."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[key] = value
    return out


def parse_model_limits(text: str) -> dict[str, tuple[int, int]]:
    """Parse "gemini-a=15/500, gemini-b=5/20" into {model: (rpm, rpd)}.

    Either number may be 0 or empty to use the defaults, e.g. "gemini-a=/500".
    """
    out: dict[str, tuple[int, int]] = {}
    for part in re.split(r"[,;]", text):
        part = part.strip()
        if not part:
            continue
        model, sep, nums = part.partition("=")
        rpm, _, rpd = nums.partition("/")
        if not sep or not model.strip():
            raise ValueError(f"GEMINI_MODEL_LIMITS entry {part!r} must look like model=rpm/rpd")
        out[model.strip()] = (int(rpm.strip() or 0), int(rpd.strip() or 0))
    return out


def _keys_from_env(env: dict[str, str]) -> list[GeminiKey]:
    keys: list[GeminiKey] = []
    if env.get("GEMINI_API_KEY"):
        keys.append(GeminiKey("default", env.get("GEMINI_PROJECT", "default"), env["GEMINI_API_KEY"]))
    numbered = sorted((int(m.group(1)), name) for name in env if (m := re.fullmatch(r"GEMINI_API_KEY_(\d+)", name)))
    for n, name in numbered:
        if env[name]:
            # Without GEMINI_PROJECT_<n>, each key is treated as its own project (own quota).
            keys.append(GeminiKey(f"key{n}", env.get(f"GEMINI_PROJECT_{n}") or f"key{n}", env[name]))
    return keys


def load_settings(data_dir: str | Path | None = None, env: dict[str, str] | None = None,
                  dotenv_path: str | Path | None = ".env", use_keystore: bool | None = None) -> Settings:
    """Build Settings from defaults, settings.json, .env, the environment and the app's key store.

    The key store is read unless `env` is given explicitly (tests) or `use_keystore=False`.
    """
    merged: dict[str, str] = {}
    if dotenv_path is not None:
        merged.update(parse_dotenv(Path(dotenv_path)))
    merged.update(os.environ if env is None else env)

    s = Settings()
    if data_dir is not None:
        s.data_dir = Path(data_dir)
    elif merged.get("BNDOCVQA_DATA_DIR"):
        s.data_dir = Path(merged["BNDOCVQA_DATA_DIR"])

    prefs_file = s.data_dir / "settings.json"
    if prefs_file.is_file():
        prefs = json.loads(prefs_file.read_text(encoding="utf-8"))
        if prefs.get("gemini_model"):
            s.gemini_model = prefs["gemini_model"]

    if merged.get("GEMINI_MODEL"):
        s.gemini_model = merged["GEMINI_MODEL"]
    for env_name, attr, conv in (
        ("GEMINI_TIMEOUT_S", "gemini_timeout_s", int),
        ("GEMINI_CONCURRENCY", "gemini_concurrency", int),
        ("GEMINI_RPM", "gemini_default_rpm", int),
        ("GEMINI_RPD", "gemini_default_rpd", int),
        ("GEMINI_MAX_ATTEMPTS", "gemini_max_attempts", int),
        ("GEMINI_TEMPERATURE", "gemini_temperature", float),
        ("QUESTIONS_PER_PAGE", "questions_per_page", int),
    ):
        if merged.get(env_name):
            setattr(s, attr, conv(merged[env_name]))
    for name, value in merged.items():
        m = re.fullmatch(r"GEMINI_PROJECT_RPM_(.+)", name)
        if m and value:
            s.gemini_project_rpm[m.group(1)] = int(value)
    if merged.get("GEMINI_MODEL_LIMITS"):
        s.gemini_model_limits.update(parse_model_limits(merged["GEMINI_MODEL_LIMITS"]))
    s.gemini_keys = _keys_from_env(merged)
    if use_keystore if use_keystore is not None else env is None:
        from .keystore import KeyStore
        try:
            s.gemini_keys += KeyStore().gemini_keys()
        except Exception:  # an unreadable store must not stop the app
            pass
    return s


__all__ = ["Settings", "GeminiKey", "load_settings", "parse_dotenv", "parse_model_limits", "fields"]
