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
    except Exception as exc:
        # аннотация GitHub Actions: причина видна в сводке проверки без скачивания журнала
        last = STEPS[-1] if STEPS else "до первого шага"
        text = f"Сбой после шага «{last}»: {type(exc).__name__}: {exc}"[:1500]
        print("::error title=Калькулятор e2e::" + text.replace("%", "%25").replace("\r", "").replace("\n", "%0A"))
        raise
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

        def example(n: int):
            page.locator(".test-menu > summary").click()
            page.get_by_role("button", name="Пример 1: старше паспортного" if n == 1 else "Пример 2: моложе паспортного").click()

        def tab(name: str):
            page.get_by_role("tab", name=name).click()

        page.goto(base)
        expect(page.locator(".tabs")).to_be_visible(timeout=60000)
        expect(page.locator(".test-menu")).to_be_visible(timeout=60000)
        top = page.locator(".topbar").inner_text()
        assert "модуль" not in top and "не валидирована" not in top, top
        expect(page.get_by_role("tab")).to_have_count(3)                     # Данные → Анкета → Результаты
        step("модуль загружен (Pyodide); три раздела: данные, анкета, результаты; примеры — в меню тестирования")

        example(1)
        tab("Результаты")
        pheno = page.locator(".age-card").filter(has_text="PhenoAge")
        expect(pheno.locator(".figure-value")).to_have_text("50,1")
        lmb = page.locator(".age-card").filter(has_text="LMB BioAge")
        expect(lmb.locator(".bio-value")).to_have_text("58,6")
        expect(lmb).to_contain_text("Исследовательский статус · не валидирован")
        expect(lmb.locator(".limits")).to_contain_text("Клиническая валидация не проведена")
        body = page.locator("main").inner_text()
        for banned in ("LMB − PhenoAge", "Контроль", "контроль PhenoAge", "Рассчитано", "v0.3"):
            assert banned not in body, banned
        for eng in ("Cardio\n", "Metabolic\n", "Renal\n"):
            assert eng not in page.locator(".branch-grid").first.inner_text(), eng
        page.wait_for_timeout(500)
        page.screenshot(path=SHOTS / "calc_01_example.png", full_page=False)
        step("пример 1: PhenoAge 50,1 (самостоятельно), LMB 58,6 с исследовательским статусом; без сравнения моделей")

        research = page.locator(".research-section")
        expect(research).to_be_visible()
        expect(research.locator("section[aria-labelledby=dv-branches] .dv-row")).to_have_count(7)
        expect(research.locator(".dev-grid .dev-row:not(.dev-head)")).to_have_count(12)
        page.get_by_role("switch", name="Проверочный расчёт Cardio").check()
        check = research.locator(".check-body")
        expect(check).to_contain_text("Популяционная нормализация и перевод в годы не подтверждены")
        expect(check.locator("tbody tr").filter(has_text="Вклад Cardio")).to_contain_text("+0,319")
        expect(check.locator("tbody tr").filter(has_text="LMB BioAge")).to_contain_text("57,19")
        expect(check).not_to_contain_text("PhenoAge")
        page.screenshot(path=SHOTS / "calc_03_profile_full.png", full_page=True)
        page.get_by_role("switch", name="Исследовательский режим").uncheck()
        expect(page.locator(".research-section")).to_have_count(0)
        expect(lmb.locator(".bio-value")).to_have_count(0)
        expect(page.locator(".domain-line")).to_have_count(0)
        expect(pheno.locator(".figure-value")).to_have_text("50,1")             # PhenoAge не зависит от режима
        page.get_by_role("switch", name="Исследовательский режим").check()
        step("исследовательский режим управляет всеми исследовательскими блоками; PhenoAge виден всегда")

        tab("Данные")
        page.get_by_label("Лимфоциты абс.", exact=True).fill("8")
        row = lambda label: page.locator(".calc-row", has=page.get_by_label(label, exact=True))  # noqa: E731
        expect(row("Лимфоциты абс.")).to_have_class("calc-row has-error")
        expect(row("Лимфоциты абс.").locator(".field-error")).to_contain_text("противоречив")
        expect(row("Лейкоциты")).to_have_class("calc-row has-error")
        tab("Результаты")
        expect(pheno).to_contain_text("не рассчитан")
        expect(lmb).to_contain_text("не рассчитана")
        gaps = page.locator(".gaps-card")
        expect(gaps).to_contain_text("Общий анализ крови противоречив")
        page.screenshot(path=SHOTS / "calc_09_cbc_conflict.png", full_page=False)
        gaps.get_by_role("button", name="Лейкоциты").first.click()
        expect(page.get_by_label("Лейкоциты", exact=True)).to_be_focused()
        page.get_by_label("Лимфоциты абс.", exact=True).fill("2,0")
        step("противоречивый ОАК (лимфоциты 8 > лейкоциты 6,3) блокирует NLR, SII, PhenoAge и LMB; ошибка у полей, переход к полю")

        page.get_by_label("Лимфоциты абс.", exact=True).fill("")
        tab("Результаты")
        expect(pheno.locator(".notes")).to_contain_text("не хватает: Лимфоциты абс.")
        assert "Альбумин" not in pheno.locator(".notes").inner_text()
        tab("Данные")
        page.get_by_label("Лимфоциты абс.", exact=True).fill("2,0")
        step("сообщения перечисляют только фактически отсутствующие показатели")

        page.get_by_label("ACR лаборатории", exact=True).fill("2,5")
        src = page.locator("#acr-source")
        expect(src).to_contain_text("выберите источник")
        expect(src).to_contain_text("лаборатория 2,5 мг/ммоль")
        tab("Результаты")
        expect(lmb).to_contain_text("не рассчитана")
        expect(page.locator(".gaps-card")).to_contain_text("Есть два значения ACR")
        tab("Данные")
        page.get_by_role("radio", name="Расчёт по альбумину и креатинину").click()
        tab("Результаты")
        expect(lmb.locator(".bio-value")).to_have_text("58,6")
        expect(page.locator(".branch").filter(has_text="Почечный профиль")).to_contain_text("источник: расчёт по альбумину и креатинину мочи")
        step("конфликт ACR требует выбора источника; источник указан в результатах")

        tab("Данные")
        page.get_by_label("Перелом бедра", exact=True).fill("10")
        expect(row("Перелом бедра").locator(".field-error")).to_contain_text("больше риска основных")
        page.get_by_label("Перелом бедра", exact=True).fill("1,0")
        expect(page.locator(".calc-row.has-error")).to_have_count(0)
        step("FRAX 6,5 % / 10 % — ошибка у полей; 6,5 % / 1,0 % — принято")

        cr = page.get_by_label("Единица: Креатинин сыворотки")
        expect(cr.locator("option")).to_have_count(2)                          # мкмоль/л и мг/дл, без дублей
        expect(page.get_by_label("Единица: Лейкоциты")).to_have_count(0)        # синонимы ×10⁹/л — одна единица
        cr.select_option("mg/dL")
        confirm = page.locator(".unit-confirm")
        expect(confirm).to_contain_text("Как сменить единицу")
        confirm.get_by_role("button", name="Пересчитать значение").click()
        expect(page.get_by_label("Креатинин сыворотки", exact=True)).to_have_value("0,791855")
        cr.select_option("umol/L")
        page.locator(".unit-confirm").get_by_role("button", name="Пересчитать значение").click()
        expect(page.get_by_label("Креатинин сыворотки", exact=True)).to_have_value("70")
        step("единицы без дублей; смена единицы — явный выбор «пересчитать» или «без пересчёта»")

        tab("Анкета")
        counter = page.get_by_role("tab", name="Анкета").locator(".num").inner_text()
        done, total = (int(x) for x in counter.split("/"))
        assert done == total, counter                                           # без МПК производитель денситометра не нужен
        expect(page.get_by_label("Производитель денситометра (для МПК в г/см²)")).to_have_count(0)
        step(f"анкета: счётчик {counter} учитывает только применимые вопросы")

        tab("Данные")
        page.get_by_label("Окружность талии", exact=True).fill("82")             # изменение прямо перед обновлением
        page.reload()
        expect(page.get_by_label("ACR лаборатории", exact=True)).to_have_value("2,5", timeout=60000)
        expect(page.get_by_role("radio", name="Расчёт по альбумину и креатинину")).to_have_attribute("aria-checked", "true")
        expect(page.locator(".draft-status")).to_contain_text("Черновик сохранён")
        expect(page.locator(".alert")).to_contain_text("Восстановлен черновик")
        step("обновление страницы восстанавливает черновик; статус сохранения виден")

        with page.expect_download() as dl:
            page.get_by_role("button", name="Сохранить в файл").click()
        saved = dl.value.path()
        page.get_by_role("button", name="Очистить").click()
        expect(page.locator(".topbar")).to_contain_text("Возраст —")
        page.locator("input[type=file]").set_input_files(saved)
        expect(page.get_by_label("ACR лаборатории", exact=True)).to_have_value("2,5")
        import json, tempfile
        legacy = json.loads(open(saved, encoding="utf-8").read())
        legacy["lmb_minus_phenoage"] = 8.5                                     # устаревшее поле сравнения
        legacy["form"]["pheno_control"] = {"compare": True}
        tmp = Path(tempfile.mkdtemp()) / "old-case.json"
        tmp.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        page.get_by_role("button", name="Очистить").click()
        page.locator("input[type=file]").set_input_files(str(tmp))
        expect(page.locator(".alert")).to_contain_text("Открыт файл old-case.json")
        tab("Результаты")
        expect(lmb.locator(".bio-value")).to_have_text("58,6")
        step("файл сохраняется и открывается; старый файл с полями сравнения открывается, лишнее игнорируется")

        page.get_by_role("button", name="Сформировать отчёт").click()
        report = page.locator(".report")
        expect(report).to_contain_text("PhenoAge")
        expect(report).to_contain_text("основные 6,5 % · бедро 1 %")
        expect(report).to_contain_text("официальный FRAX")
        expect(report).to_contain_text("источник: расчёт по альбумину и креатинину мочи")
        expect(report).not_to_contain_text("LMB − PhenoAge")
        expect(report.locator(".cardio-check")).to_have_count(0)
        page.screenshot(path=SHOTS / "calc_07_report.png", full_page=True)
        page.emulate_media(media="print")
        expect(page.locator(".tabs")).to_be_hidden()
        expect(page.locator(".topbar")).to_be_hidden()
        page.pdf(path=str(SHOTS / "calc_report.pdf"), format="A4")
        page.emulate_media(media="screen")
        page.get_by_role("button", name="К результатам").click()
        step("отчёт по кнопке: PhenoAge, оба риска FRAX (перенесены из официального), источник ACR; печать в PDF")

        example(2)
        tab("Результаты")
        expect(pheno.locator(".figure-value")).to_have_text("38,1")
        expect(lmb.locator(".bio-value")).to_have_text("46,9")
        page.screenshot(path=SHOTS / "calc_06_younger.png", full_page=False)
        step("пример 2: PhenoAge 38,1, LMB 46,9")

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
