"""Phase 1 setup verification for Digital Wingman.

Checks imports, configuration, and (optionally) AI backend connectivity
without requiring a running emulator.

Usage:
  python verify_setup.py
  python verify_setup.py --check-backend
"""

from __future__ import annotations

import argparse
import importlib
import os
import shutil
import sys
from pathlib import Path


def _ok(msg: str) -> None:
    print(f"  OK  {msg}")


def _warn(msg: str) -> None:
    print(f"  WARN  {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL  {msg}")


def check_python() -> bool:
    print("Python")
    v = sys.version_info
    if v >= (3, 10):
        _ok(f"{v.major}.{v.minor}.{v.micro}")
        return True
    _fail(f"need 3.10+, have {v.major}.{v.minor}.{v.micro}")
    return False


def check_imports() -> bool:
    print("Imports")
    modules = [
        "adb",
        "config",
        "judge_common",
        "main",
        "metrics",
        "vision",
        "modes",
        "judge",
        "judge_ollama",
        "judge_gemini",
    ]
    ok = True
    for name in modules:
        try:
            importlib.import_module(name)
            _ok(name)
        except Exception as e:
            _fail(f"{name}: {e}")
            ok = False
    return ok


def check_config() -> bool:
    print("Config")
    import config

    _ok(f"RUN_MODE={config.RUN_MODE}")
    _ok(f"HUMAN_APPROVAL={config.HUMAN_APPROVAL}, AUTO_ACTION={config.AUTO_ACTION}")
    _ok(f"DRY_RUN={config.DRY_RUN}")
    _ok(f"JUDGE_BACKEND={config.JUDGE_BACKEND}")
    _ok(f"OLLAMA_MODEL={getattr(config, 'OLLAMA_MODEL', '?')}")
    _ok(f"OLLAMA_HOST={getattr(config, 'OLLAMA_HOST', None) or 'http://localhost:11434'}")
    _ok(f"ADB_SERIAL={getattr(config, 'ADB_SERIAL', None) or '(auto)'}")
    _ok(f"SCREEN={config.SCREEN_WIDTH}x{config.SCREEN_HEIGHT}")
    _ok(f"ACTIVE_MODE={config.ACTIVE_MODE}")
    ok = True
    data_profile = getattr(config, "DATA_DIR", config.BASE_DIR / "data") / "aryan_profile.yaml"
    example_profile = data_profile.with_name("user_profile.example.yaml")
    if data_profile.is_file():
        _ok("aryan_profile.yaml present")
    elif example_profile.is_file():
        _warn("using example profile — copy it to aryan_profile.yaml and customize it")
    else:
        _warn(f"missing {data_profile} and {example_profile}")
        ok = False
    from wingman.self_profile import load_cached_self_profile

    cached = load_cached_self_profile()
    if cached:
        _ok("private self-profile cache present")
    else:
        _warn("no private self-profile cache — optional: python wingman_session.py --self-scan")
    if config.RUN_MODE == "dry_run":
        _ok("dry-run mode will not tap Hinge")
    else:
        _warn(f"RUN_MODE={config.RUN_MODE!r} may perform Hinge actions")
    return ok


def check_adb() -> bool:
    print("ADB")
    adb_bin = shutil.which("adb")
    if not adb_bin:
        _warn("adb not on PATH — install Android SDK platform-tools")
        return False
    _ok(f"found at {adb_bin}")
    try:
        import adb as adb_mod
        devices = adb_mod.list_devices()
        if not devices:
            _warn("no devices in `adb devices`")
            return False
        _ok(f"connected: {', '.join(devices)}")
        import config
        preferred = getattr(config, "ADB_SERIAL", None)
        if preferred:
            if preferred in devices:
                _ok(f"ADB_SERIAL {preferred} is connected")
            else:
                _warn(f"ADB_SERIAL {preferred} not in connected list")
                return False
    except Exception as e:
        _warn(f"device check failed: {e}")
        return False
    return True


def check_env() -> bool:
    print("Environment")
    import config

    if Path(".env").exists():
        _ok(".env present (optional)")
        from dotenv import load_dotenv
        load_dotenv()
    else:
        _ok(".env not present")

    active = getattr(config, "JUDGE_BACKEND", "anthropic")
    if active == "anthropic":
        if os.environ.get("ANTHROPIC_API_KEY"):
            _ok("ANTHROPIC_API_KEY set")
        else:
            _warn("ANTHROPIC_API_KEY not set")
            return False
    elif active == "gemini":
        if os.environ.get("GEMINI_API_KEY"):
            _ok("GEMINI_API_KEY set")
        else:
            _warn("GEMINI_API_KEY not set")
            return False
    elif active == "ollama":
        host = getattr(config, "OLLAMA_HOST", None) or os.environ.get(
            "OLLAMA_HOST", "http://localhost:11434"
        )
        if host.startswith("https://"):
            if os.environ.get("OLLAMA_API_KEY"):
                _ok("OLLAMA_API_KEY set (cloud)")
            else:
                _warn("OLLAMA_API_KEY not set for Ollama Cloud")
                return False
        else:
            _ok(f"local Ollama host {host} (no API key needed)")
    env_backend = os.environ.get("JUDGE_BACKEND")
    if env_backend:
        _ok(f"JUDGE_BACKEND env override={env_backend}")
    return True


def check_backend() -> bool:
    print("AI backend")
    import config
    from judge_common import load_backend

    backend = load_backend()
    _ok(f"loaded {backend.__name__}")

    if config.JUDGE_BACKEND == "ollama":
        try:
            client = backend._client()
            listed = client.list()
            models = listed.get("models", []) if isinstance(listed, dict) else getattr(
                listed, "models", []
            )
            names = []
            for m in models:
                name = m.get("name") if isinstance(m, dict) else getattr(m, "model", "")
                if name:
                    names.append(name)
            if names:
                _ok(f"Ollama models available: {', '.join(names[:5])}")
            else:
                _warn("Ollama reachable but no models listed — run `ollama pull qwen2.5-vl`")
        except Exception as e:
            _fail(f"Ollama connectivity: {e}")
            return False
    elif config.JUDGE_BACKEND == "anthropic":
        try:
            import anthropic

            client = anthropic.Anthropic()
            # Lightweight auth check — list is not available; a minimal call
            # would cost money. Just verify client constructs.
            _ok("Anthropic client initialized (skipping paid API ping)")
            del client
        except Exception as e:
            _fail(f"Anthropic: {e}")
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Digital Wingman Phase 1 setup")
    parser.add_argument(
        "--check-backend",
        action="store_true",
        help="Also test AI backend connectivity",
    )
    args = parser.parse_args()

    print("Digital Wingman — Phase 1 verification\n")
    results = [
        check_python(),
        check_imports(),
        check_config(),
        check_adb(),
    ]
    results.append(check_env())
    if args.check_backend:
        results.append(check_backend())

    print()
    if all(results):
        print("All checks passed.")
        return 0
    print("Some checks failed — see WARN/FAIL above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
