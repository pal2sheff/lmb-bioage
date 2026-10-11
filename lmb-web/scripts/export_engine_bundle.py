"""Готовит файлы для браузерного калькулятора (calc.html).

Копирует расчётный модуль lmb_engine и его конфигурацию без изменений, выгружает справочник
полей и анкеты из lmb_server.catalog и копирует среду Pyodide из node_modules. Браузер
запускает тот же Python-код, что и сервер, — отдельной реализации формул нет.

Запуск из lmb-web: python3 scripts/export_engine_bundle.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
ROOT = WEB.parent
ENGINE = ROOT / "lmb-engine"
SERVER = ROOT / "lmb-server"
OUT = WEB / "calc-public"
PYODIDE_FILES = ("pyodide.mjs", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json")

sys.path[:0] = [str(ENGINE), str(SERVER)]


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    eng_out = OUT / "engine"
    files = []
    for src in sorted((ENGINE / "lmb_engine").glob("*.py")):
        files.append(("lmb_engine/" + src.name, src))
    for src in sorted((ENGINE / "config").rglob("*.json")):
        files.append(("config/" + src.relative_to(ENGINE / "config").as_posix(), src))
    files.append(("bridge.py", WEB / "src" / "calc" / "bridge.py"))
    manifest = []
    for rel, src in files:
        dst = eng_out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        manifest.append({"path": rel, "sha256": hashlib.sha256(src.read_bytes()).hexdigest()})

    from lmb_engine import __version__ as engine_version
    from lmb_engine.model import config_sha256, load_config
    from lmb_server.catalog import observation_definitions, ui_catalog
    cfg = load_config(str(ENGINE / "config" / "model_v0.3.json"))
    (eng_out / "manifest.json").write_text(json.dumps({
        "engine_version": engine_version, "model_version": cfg["version"],
        "model_config_sha256": config_sha256(cfg), "files": manifest}, ensure_ascii=False, indent=1), encoding="utf-8")
    (eng_out / "catalog.json").write_text(json.dumps(ui_catalog(observation_definitions()), ensure_ascii=False),
                                          encoding="utf-8")

    py_out = OUT / "pyodide"
    py_out.mkdir(parents=True)
    src_dir = WEB / "node_modules" / "pyodide"
    for name in PYODIDE_FILES:
        shutil.copyfile(src_dir / name, py_out / name)
    print(f"Готово: {len(manifest)} файлов модуля {engine_version}, Pyodide → {OUT}")


if __name__ == "__main__":
    main()
