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
        expect(page.get_by_role("tab", name="Данные обследования")).to_be_visible(timeout=60000)
        expect(page.locator("#c-birth")).to_be_visible(timeout=60000)
        top = page.locator(".topbar").inner_text()
        assert "модуль" not in top and "не валидирована" not in top, top
        step("модуль загружен в браузер (Pyodide); разделы и верхняя панель без служебных надписей")

        page.get_by_role("button", name="Пример 1: старше паспортного").click()
        expect(page.locator(".topbar")).to_contain_text("55 лет")
        expect(page.locator(".topbar")).to_contain_text("Женский")
        expect(page.locator(".topbar")).to_contain_text("10.10.2026")
        page.screenshot(path=SHOTS / "calc_00_data.png", full_page=False)
        page.get_by_role("tab", name="Профиль систем").click()
        expect(page.locator(".branch")).to_have_count(9)
        metabolic = page.get_by_role("article", name="Метаболический профиль")
        expect(metabolic.locator(".domain-line")).to_contain_text("0,36")
        expect(page.locator(".status-line")).to_contain_text("не рассчитан")
        card = page.locator(".research-card")
        expect(card.locator(".bio-value")).to_have_text("58,6")
        expect(card.locator(".research-chip")).to_contain_text("Исследовательский статус")
        expect(card.locator(".limits")).to_contain_text("Клиническая валидация не проведена")
        expect(card.locator(".pheno")).to_contain_text("50,1")
        expect(page.get_by_role("article", name="Когнитивно-сосудистый профиль").locator(".index-val").first).to_contain_text("4")
        expect(page.get_by_role("article", name="Профиль риска переломов")).to_contain_text("6,5")
        body = page.locator("main").inner_text()
        assert "v0.3" not in body and "local_synthetic" not in body, "служебные данные вне «Подробностей»"
        page.wait_for_timeout(500)
        page.screenshot(path=SHOTS / "calc_01_example.png", full_page=False)
        step("пример 1: статус клинического итога строкой; исследовательская карточка 55 → 58,6, ограничения, PhenoAge 50,1")

        branches = page.locator("section[aria-labelledby=dv-branches]")
        expect(branches.locator(".dv-row")).to_have_count(7)
        expect(branches.locator(".dv-row").filter(has_text="Метаболический")).to_contain_text("+0,54")  # 1,5 × 0,36
        expect(branches).to_contain_text("равна разнице биологического и паспортного")
        rows = page.locator(".dev-grid .dev-row:not(.dev-head)")
        expect(rows).to_have_count(12)
        expect(rows.filter(has_text="SCORE2")).to_contain_text("от авторского ожидания")
        expect(page.locator(".traj").first).to_be_hidden()                    # возрастные графики свёрнуты
        page.get_by_text("Возрастные графики показателей").click()
        expect(page.locator(".traj")).to_have_count(12)
        expect(page.locator(".traj").first).to_be_visible()
        page.locator(".traj-section").scroll_into_view_if_needed()
        page.screenshot(path=SHOTS / "calc_04_trajectories.png", full_page=False)
        page.screenshot(path=SHOTS / "calc_03_profile_full.png", full_page=True)
        step("графики: вклад 7 систем, вклад показателей, сводная диаграмма 12 показателей, возрастные графики — по раскрытию")

        page.get_by_role("switch").uncheck()
        expect(page.locator(".research-card")).to_have_count(0)
        expect(page.locator(".status-line")).to_be_visible()
        page.get_by_role("switch").check()
        expect(card.locator(".bio-value")).to_have_text("58,6")
        step("явный переключатель исследовательского расчёта: выключение скрывает карточку, клинический статус остаётся")

        page.get_by_role("tab", name="Данные обследования").click()
        page.get_by_role("button", name="Пример 2: моложе паспортного").click()
        page.get_by_role("tab", name="Профиль систем").click()
        expect(card.locator(".bio-value")).to_have_text("46,9")
        expect(card).to_contain_text("ниже календарного")
        expect(card.locator(".pheno")).to_contain_text("38,1")
        page.wait_for_timeout(400)
        page.screenshot(path=SHOTS / "calc_06_younger.png", full_page=False)
        step("пример 2: 50 → 46,9 (ниже календарного), PhenoAge 38,1")

        page.get_by_role("tab", name="Данные обследования").click()
        page.get_by_role("button", name="Пример 1: старше паспортного").click()
        page.get_by_label("ЛПВП", exact=True).fill("abc")
        expect(page.locator(".field-error")).to_contain_text("не число")
        expect(page.locator(".tab-count")).to_have_text("1")
        page.get_by_role("tab", name="Анкета").click()
        expect(page.get_by_role("radiogroup", name="Текущее курение")).to_be_visible()
        page.get_by_role("tab", name="Данные обследования").click()
        expect(page.get_by_label("ЛПВП", exact=True)).to_have_value("abc")            # ввод сохраняется между разделами
        page.get_by_label("ЛПВП", exact=True).fill("1,5")
        page.get_by_label("Инсулин натощак", exact=True).fill("")
        page.get_by_role("tab", name="Профиль систем").click()
        expect(metabolic.locator(".domain-line")).to_contain_text("не хватает")
        expect(card).to_contain_text("не рассчитана")
        expect(card.locator(".reason-list")).to_contain_text("Метаболический профиль: не хватает входов")
        step("ошибка ввода показана в поле и на вкладке; данные сохраняются между разделами; без инсулина итог не считается")

        page.get_by_role("tab", name="Данные обследования").click()
        page.get_by_label("Инсулин натощак", exact=True).fill("8")
        page.get_by_role("tab", name="Отчёт").click()
        report = page.locator(".report")
        expect(report.locator(".report-table").first).to_contain_text("Метаболический профиль")
        expect(report.locator(".research-card .bio-value")).to_have_text("58,6")
        expect(report).to_contain_text("Разница с календарным возрастом")
        expect(page.get_by_role("button", name="Печать отчёта")).to_be_visible()
        page.screenshot(path=SHOTS / "calc_07_report.png", full_page=True)
        page.emulate_media(media="print")
        expect(page.locator(".tabs")).to_be_hidden()
        expect(page.locator(".topbar")).to_be_hidden()
        page.pdf(path=str(SHOTS / "calc_report.pdf"), format="A4")
        page.emulate_media(media="screen")
        step("отчёт врача: таблица систем, исследовательская оценка и вклады; печать без панелей (PDF)")

        page.get_by_role("tab", name="Данные обследования").click()
        with page.expect_download() as dl:
            page.get_by_role("button", name="Сохранить в файл").click()
        saved = dl.value.path()
        page.get_by_role("button", name="Очистить").click()
        expect(page.locator(".topbar")).to_contain_text("Возраст —")
        page.locator("input[type=file]").set_input_files(saved)
        page.get_by_role("tab", name="Профиль систем").click()
        expect(metabolic.locator(".domain-line")).to_contain_text("0,36")
        step("случай сохранён в файл, очищен и открыт снова")

        external = [u for u in requests if not u.startswith(base) and not u.startswith("data:") and not u.startswith("blob:")]
        assert not external, f"запросы за пределы сайта: {external[:5]}"
        step("никаких запросов за пределы сайта: данные не покидают браузер")

        for w, h, name in [(834, 1112, "calc_02_tablet.png"), (390, 844, "calc_02_mobile.png")]:
            page.set_viewport_size({"width": w, "height": h})
            page.wait_for_timeout(300)
            overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            assert overflow <= 1, f"горизонтальная прокрутка {overflow}px при ширине {w}"
            page.screenshot(path=SHOTS / name, full_page=False)
        if errors:
            raise AssertionError(f"Ошибки JavaScript: {errors}")
        step("нет ошибок JavaScript; планшет и телефон без горизонтальной прокрутки")
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
