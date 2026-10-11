"""Сквозная проверка браузерного калькулятора (статический сайт dist-calc, расчёт в Pyodide).

Сервер базы не нужен: страница раздаётся простым статическим сервером, как на GitHub Pages.
Запуск из lmb-web: npm run calc:bundle && npm run calc:build && python3 e2e/run_calc_e2e.py
"""
from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
DIST = WEB / "dist-calc"
SHOTS = WEB / "e2e" / "screens"
STEPS = []


def step(name: str) -> None:
    STEPS.append(name)
    print(f"  ✓ {name}")


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".wasm": "application/wasm", ".mjs": "text/javascript", ".js": "text/javascript",
                      ".json": "application/json", ".py": "text/plain; charset=utf-8"}

    def log_message(self, *a):
        pass


def main() -> int:
    if not (DIST / "index.html").exists():
        raise SystemExit("Нет dist-calc: npm run calc:bundle && npm run calc:build")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(DIST)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"
    try:
        run(base)
    finally:
        srv.shutdown()
    print(f"Сценарий пройден: {len(STEPS)} шагов")
    return 0


def run(base: str) -> None:
    from playwright.sync_api import expect, sync_playwright

    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU", accept_downloads=True)
        page = ctx.new_page()
        errors, requests = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: requests.append(r.url))

        page.goto(base)
        expect(page.locator(".topbar")).to_contain_text("модуль 0.4.0", timeout=60000)
        expect(page.get_by_text("Профиль появится здесь")).to_be_visible()
        step("модуль загружен в браузер (Pyodide), версия показана")

        page.get_by_role("button", name="Синтетический пример").click()
        expect(page.locator(".branch")).to_have_count(9)
        metabolic = page.locator(".branch").filter(has_text="Metabolic")
        expect(metabolic.locator(".domain-line")).to_contain_text("0,36")
        expect(page.locator(".integral")).to_contain_text("не рассчитан")
        brain = page.locator(".branch").filter(has_text="Brain")
        expect(brain.locator(".index-val").first).to_contain_text("4")
        bone = page.locator(".branch").filter(has_text="Bone")
        expect(bone).to_contain_text("6,5")
        page.wait_for_timeout(600)
        page.screenshot(path=SHOTS / "calc_01_example.png", full_page=False)
        step("синтетический пример: 9 веток, Metabolic 0,36, CAIDE 4, FRAX 6,5 %, итог заблокирован")

        page.get_by_label("ЛПВП", exact=True).fill("abc")
        expect(page.get_by_role("status").filter(has_text="Проверьте ввод")).to_contain_text("ЛПВП: не число")
        page.get_by_label("ЛПВП", exact=True).fill("1,5")
        page.get_by_label("Инсулин натощак", exact=True).fill("")
        expect(metabolic.locator(".domain-line")).to_contain_text("не хватает")
        step("ошибка ввода показана; пустой инсулин → Metabolic не считается (без подстановки)")

        page.get_by_label("Инсулин натощак", exact=True).fill("8")
        expect(metabolic.locator(".domain-line")).to_contain_text("0,36")
        with page.expect_download() as dl:
            page.get_by_role("button", name="Сохранить в файл").click()
        saved = dl.value.path()
        page.get_by_role("button", name="Очистить").click()
        expect(page.get_by_text("Профиль появится здесь")).to_be_visible()
        page.locator("input[type=file]").set_input_files(saved)
        expect(metabolic.locator(".domain-line")).to_contain_text("0,36")
        step("случай сохранён в файл, очищен и открыт снова")

        external = [u for u in requests if not u.startswith(base) and not u.startswith("data:") and not u.startswith("blob:")]
        assert not external, f"запросы за пределы сайта: {external[:5]}"
        step("никаких запросов за пределы сайта: данные не покидают браузер")

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        page.screenshot(path=SHOTS / "calc_02_mobile.png", full_page=False)
        if errors:
            raise AssertionError(f"Ошибки JavaScript: {errors}")
        step("нет ошибок JavaScript")
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
