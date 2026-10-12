"""Сквозная проверка браузерного калькулятора (статический сайт dist-calc, расчёт в Pyodide).

Сервер базы не нужен: страница раздаётся простым статическим сервером, как на GitHub Pages.
Запуск из lmb-web: npm run calc:bundle && npm run calc:build && python3 e2e/run_calc_e2e.py
"""
from __future__ import annotations

import functools
import http.server
import io
import re
import tempfile
import zipfile
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


CSV_ROWS = [
    ["Показатель", "Результат", "Ед. изм.", "Референс"],
    ["Глюкоза", "5,2", "ммоль/л", "3,9-5,5"],
    ["Креатинин", "70", "мкмоль/л", "44-80"],
    ["Креатинин в разовой порции мочи", "10", "ммоль/л", ""],
    ["Альбумин", "44", "г/л", "35-52"],
    ["Микроальбумин (моча)", "20", "мг/л", "<30"],
    ["Нейтрофилы, абс.", "3,5", "10*9/л", ""],
    ["Нейтрофилы, %", "55,6", "%", ""],
    ["RDW-CV", "13,4", "%", ""],
    ["RDW-SD", "42,1", "фл", ""],
    ["С-реактивный белок (высокочувствительный)", "<0,5", "мг/л", ""],
    ["Ферритин", "80", "нг/мл", ""],
]


def _xlsx(rows) -> bytes:
    def cell(r, c, v):
        ref = f"{chr(65 + c)}{r + 1}"
        if isinstance(v, str):
            return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'
        return f'<c r="{ref}"><v>{v}</v></c>'
    sheet = "".join(f'<row r="{r + 1}">' + "".join(cell(r, c, v) for c, v in enumerate(row)) + "</row>"
                    for r, row in enumerate(rows))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   '<sheet name="Анализы" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
                   '2006/relationships"><Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
                   '</Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
                   f'2006/main"><sheetData>{sheet}</sheetData></worksheet>')
    return buf.getvalue()


def lab_fixtures(browser) -> dict:
    """Синтетические лабораторные файлы (данные выдуманы): CSV в Windows-1251, XLSX, PDF с текстовым слоем, «скан»."""
    d = Path(tempfile.mkdtemp())
    out = {"csv": d / "lab_synthetic.csv", "xlsx": d / "lab_synthetic.xlsx", "pdf": d / "lab_synthetic.pdf",
           "png": d / "lab_scan.png"}
    out["csv"].write_bytes("\n".join(";".join(r) for r in CSV_ROWS).encode("cp1251"))
    out["xlsx"].write_bytes(_xlsx([["Показатель", "Результат", "Ед. изм.", "Дата"],
                                   ["Глюкоза", 5.9, "ммоль/л", "01.09.2026"],
                                   ["Глюкоза", 5.2, "ммоль/л", "10.10.2026"],
                                   ["Тромбоциты", 240, "10^9/л", "10.10.2026"]]))
    p = browser.new_page()
    rows = [("АЛТ", "20", "Ед/л"), ("АСТ", "22", "Ед/л"), ("Щелочная фосфатаза", "78", "Ед/л"), ("MCV", "91", "фл")]
    p.set_content("<html><body style='font-family:Arial'><h3>Синтетическая лаборатория</h3>"
                  "<p>Дата взятия: 10.10.2026</p><table cellpadding='6'><tr><th>Исследование</th><th>Результат</th>"
                  "<th>Ед. изм.</th></tr>" + "".join(f"<tr><td>{a}</td><td>{v}</td><td>{u}</td></tr>" for a, v, u in rows)
                  + "</table></body></html>")
    p.pdf(path=str(out["pdf"]), format="A4")
    p.set_content("<div style='width:200px;height:80px;background:#ddd'></div>")
    out["png"].write_bytes(p.screenshot())
    p.close()
    return out


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
        pheno = page.locator(".pheno-card")
        expect(pheno.locator(".figure-value")).to_contain_text("50,1")
        lmb = page.locator(".age-summary")
        expect(lmb.locator(".bio-value")).to_contain_text("58,6")
        expect(lmb).to_contain_text("+3,6")
        expect(lmb).to_contain_text("55")
        branches = page.locator("section[aria-labelledby=dv-branches]")
        deviation = page.locator("section[aria-labelledby=dv-dev]")
        expect(branches.locator(".dv-row")).to_have_count(7)               # графики видны сразу, без раскрытия
        expect(deviation.locator(".dev-grid .dev-row")).to_have_count(12)
        expect(page.locator(".branch:not(.future)")).to_have_count(9)
        body = page.locator("main").inner_text()
        for banned in ("LMB − PhenoAge", "Контроль", "Рассчитано", "v0.3", "sha256", "Исследовательский статус",
                       "не валидирован", "Исследовательская модель", "Клинический итог не рассчитан",
                       "целевая популяция", "Проверочный расчёт", "Оценка системы", "Z eGFR", "сверен"):
            assert banned not in body, banned
        for eng in ("Cardio\n", "Metabolic\n", "Renal\n"):
            assert eng not in page.locator(".branch-grid").inner_text(), eng
        for w, h in [(1440, 900), (1366, 768)]:                              # ноутбук: возраст и графики в первом экране
            page.set_viewport_size({"width": w, "height": h})
            bottom = page.evaluate("Math.max(...[...document.querySelectorAll('.charts-grid .dv-card, .age-summary')]"
                                   ".map(e => e.getBoundingClientRect().bottom))")
            assert bottom <= h, f"{w}×{h}: инфографика заканчивается на {bottom:.0f}px"
        page.set_viewport_size({"width": 1440, "height": 900})
        page.wait_for_timeout(300)
        page.screenshot(path=SHOTS / "calc_01_example.png", full_page=False)
        step("пример 1: календарный 55, LMB 58,6, разница +3,6; PhenoAge 50,1 отдельно; оба графика видны сразу и помещаются в первый экран ноутбука; служебных надписей нет")

        branches.get_by_role("button", name="Почечный").click()
        parts = branches.locator(".dv-parts")
        expect(parts.locator(".dv-part").filter(has_text="ACR")).to_contain_text("+1,01")
        expect(parts.locator(".dv-part").filter(has_text="eGFR")).to_contain_text("+0,89")
        deviation.get_by_role("button", name="eGFR: Z +1,4, неблагоприятнее").click()
        expect(deviation.locator(".dev-detail")).to_contain_text("ожидаемое 100,2")
        expect(deviation.locator(".dev-detail svg")).to_be_visible()
        page.locator(".branch").filter(has_text="Сердечно-сосудистый профиль").get_by_label("Подробнее: SCORE2", exact=True).click()
        expect(page.locator(".branch .info-body").first).to_contain_text("SCORE2 (ESC 2021)")
        step("по нажатию: вклад системы по показателям (Почечный: ACR +1,01, eGFR +0,89), возрастной график показателя, формула индекса")

        method = page.locator("#method")
        method.locator("> summary").click()
        expect(method).to_contain_text("Клиническая валидация не проведена")
        expect(method).to_contain_text("целевая популяция модели не утверждена")
        expect(method).to_contain_text("научный статус: не валидирована")
        page.get_by_role("switch", name="Проверочный расчёт Cardio").check()
        check = method.locator(".check-body")
        expect(check).to_contain_text("Популяционная нормализация и перевод в годы не подтверждены")
        expect(check.locator("tbody tr").filter(has_text="Вклад Cardio")).to_contain_text("+0,319")
        expect(check.locator("tbody tr").filter(has_text="LMB BioAge")).to_contain_text("57,19")
        expect(check).not_to_contain_text("PhenoAge")
        page.get_by_role("switch", name="Проверочный расчёт Cardio").uncheck()
        page.screenshot(path=SHOTS / "calc_03_profile_full.png", full_page=True)
        page.get_by_role("switch", name="Расчётная оценка LMB и инфографика").uncheck()
        expect(page.locator(".charts-grid")).to_have_count(0)
        expect(lmb.locator(".bio-value")).to_have_count(0)
        expect(pheno.locator(".figure-value")).to_contain_text("50,1")      # PhenoAge не зависит от режима
        page.get_by_role("switch", name="Расчётная оценка LMB и инфографика").check()
        expect(branches.locator(".dv-row")).to_have_count(7)
        method.locator("> summary").click()
        step("«О методике»: статус, валидация, область, настройки режима и проверочный расчёт Cardio (+0,319; 57,19); PhenoAge виден всегда")

        tab("Данные")
        page.get_by_label("Альбумин сыворотки", exact=True).fill("1000")
        row = lambda label: page.locator(".calc-row", has=page.get_by_label(label, exact=True))  # noqa: E731
        expect(row("Альбумин сыворотки").locator(".field-error")).to_contain_text("вне допустимого диапазона")
        tab("Результаты")
        expect(pheno).to_contain_text("не рассчитан")
        expect(pheno.locator(".sn-error")).to_have_text("Проверьте альбумин сыворотки")
        expect(lmb.locator(".bio-value")).to_contain_text("58,6")                 # LMB от альбумина не зависит
        page.screenshot(path=SHOTS / "calc_10_albumin.png", full_page=False)
        pheno.get_by_role("button", name="Проверьте альбумин сыворотки").click()
        expect(page.get_by_label("Альбумин сыворотки", exact=True)).to_be_focused()
        page.get_by_label("Альбумин сыворотки", exact=True).fill("44")
        tab("Результаты")
        expect(pheno.locator(".figure-value")).to_contain_text("50,1")
        step("альбумин 1000: в карточке PhenoAge «Проверьте альбумин сыворотки» с переходом к полю, подробности у поля; LMB не затронут")

        tab("Данные")
        page.get_by_label("Лимфоциты абс.", exact=True).fill("8")
        expect(row("Лимфоциты абс.")).to_have_class("calc-row has-error")
        expect(row("Лимфоциты абс.").locator(".field-error")).to_contain_text("противоречив")
        expect(row("Лейкоциты")).to_have_class("calc-row has-error")
        tab("Результаты")
        expect(pheno).to_contain_text("не рассчитан")
        expect(lmb).to_contain_text("не рассчитан")
        gaps = page.locator(".gaps-card")
        expect(gaps).to_contain_text("Общий анализ крови противоречив")
        page.screenshot(path=SHOTS / "calc_09_cbc_conflict.png", full_page=False)
        gaps.get_by_role("button", name="Лейкоциты").first.click()
        expect(page.get_by_label("Лейкоциты", exact=True)).to_be_focused()
        page.get_by_label("Лимфоциты абс.", exact=True).fill("2,0")
        step("противоречивый ОАК (лимфоциты 8 > лейкоциты 6,3) блокирует NLR, SII, PhenoAge и LMB; ошибка у полей, переход к полю")

        page.get_by_label("Лимфоциты абс.", exact=True).fill("")
        tab("Результаты")
        expect(pheno.locator(".short-notes")).to_contain_text("не хватает: Лимфоциты абс.")
        assert "Альбумин" not in pheno.locator(".short-notes").inner_text()
        tab("Данные")
        page.get_by_label("Лимфоциты абс.", exact=True).fill("2,0")
        step("сообщения перечисляют только фактически отсутствующие показатели")

        page.get_by_label("ACR лаборатории", exact=True).fill("2,5")
        src = page.locator("#acr-source")
        expect(src).to_contain_text("выберите источник")
        expect(src).to_contain_text("лаборатория 2,5 мг/ммоль")
        tab("Результаты")
        expect(lmb).to_contain_text("не рассчитан")
        expect(page.locator(".gaps-card")).to_contain_text("Есть два значения ACR")
        tab("Данные")
        page.get_by_role("radio", name="Расчёт по альбумину и креатинину").click()
        tab("Результаты")
        expect(lmb.locator(".bio-value")).to_contain_text("58,6")
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

        files = lab_fixtures(b)
        lab = page.get_by_label("Файл анализов")
        lab.set_input_files(str(files["csv"]))
        review = page.locator(".import-review")
        expect(review).to_contain_text("Импорт анализов: lab_synthetic.csv")
        rrow = lambda name: review.locator("tbody tr").filter(has=page.get_by_text(name, exact=True))  # noqa: E731
        expect(rrow("Креатинин").locator("td").nth(5)).to_have_text("Креатинин сыворотки")
        expect(rrow("Креатинин в разовой порции мочи").locator("td").nth(5)).to_have_text("Креатинин мочи")
        expect(rrow("Альбумин").locator("td").nth(5)).to_have_text("Альбумин сыворотки")
        expect(rrow("Микроальбумин (моча)").locator("td").nth(5)).to_have_text("Альбумин мочи")
        expect(rrow("Нейтрофилы, абс.").locator("input")).to_be_checked()
        expect(rrow("С-реактивный белок (высокочувствительный)").locator("td").nth(2)).to_have_text("<0,5")
        review.locator("summary").click()
        skipped = review.locator(".import-skipped")
        expect(skipped).to_contain_text("Нейтрофилы, % 55,6 % — процент лейкоформулы")
        expect(skipped).to_contain_text("RDW-SD 42,1 фл — RDW-SD (фл) не подставляется")
        expect(skipped).to_contain_text("Ферритин — не используется")
        page.screenshot(path=SHOTS / "calc_11_import_review.png", full_page=False)
        review.get_by_role("button", name="Перенести выбранное").click()
        expect(page.get_by_label("С-реактивный белок (высокочувствительный)", exact=True)).to_have_value("<0,5")
        expect(row("С-реактивный белок (высокочувствительный)").locator(".field-error")).to_contain_text("предела определения")
        expect(page.get_by_role("radio", name="Расчёт по альбумину и креатинину")).to_have_attribute("aria-checked", "true")
        tab("Результаты")
        expect(pheno.locator(".sn-error")).to_contain_text("Проверьте С-реактивный белок")
        tab("Данные")
        page.get_by_label("С-реактивный белок (высокочувствительный)", exact=True).fill("1,8")
        step("импорт CSV: кровь и моча различаются, проценты лейкоформулы и RDW-SD не переносятся, «<0,5» сохранён со знаком; выбор источника ACR не изменился")

        lab.set_input_files(str(files["xlsx"]))
        expect(review).to_contain_text("lab_synthetic.xlsx")
        glu = review.locator("tbody tr").filter(has_text="Глюкоза")
        expect(glu).to_have_count(2)
        expect(glu.filter(has_text="10.10.2026").locator("input")).to_be_checked()
        expect(glu.filter(has_text="01.09.2026").locator("input")).not_to_be_checked()
        expect(glu.first).to_contain_text("несколько дат")
        review.get_by_role("button", name="Отмена").click()
        lab.set_input_files(str(files["pdf"]))
        expect(review).to_contain_text("lab_synthetic.pdf")
        expect(review.locator("tbody tr").filter(has_text="Щелочная фосфатаза")).to_contain_text("78")
        expect(review.locator("tbody tr").filter(has_text="АЛТ")).to_contain_text("Ед/л")
        review.get_by_role("button", name="Перенести выбранное").click()
        expect(page.get_by_label("Щелочная фосфатаза", exact=True)).to_have_value("78")
        lab.set_input_files(str(files["png"]))
        expect(page.locator(".alert")).to_contain_text("нет текстового слоя")
        expect(review).to_have_count(0)
        step("импорт XLSX (повтор с разными датами — выбрана дата обследования), текстового PDF; скан — сообщение о ручном переносе")

        page.get_by_label("Биологический возраст (LQ One)", exact=True).fill("52")
        page.get_by_label("Достоверность измерения (LQ One)", exact=True).fill("140")
        expect(row("Достоверность измерения (LQ One)").locator(".field-error")).to_contain_text("вне допустимого диапазона")
        page.get_by_label("Достоверность измерения (LQ One)", exact=True).fill("87")
        page.get_by_label("Модель аппарата", exact=True).fill("LQ One (синтетика)")
        page.get_by_label("Версия программы", exact=True).fill("1.0")
        page.get_by_label("Дата измерения", exact=True).fill("2026-10-10")
        tab("Результаты")
        adaptive = page.locator(".branch").filter(has_text="Адаптационный и вегетативный профиль")
        expect(adaptive.locator(".index-val")).to_contain_text("52")
        expect(adaptive).to_contain_text("по заключению LQ One · аппарат LQ One (синтетика) · версия 1.0 · достоверность 87 %")
        expect(lmb.locator(".bio-value")).to_contain_text("58,6")                 # в LMB не входит
        future = page.locator(".branch.future")
        expect(future).to_contain_text("Респираторный профиль")
        expect(future).to_contain_text("в работе")
        expect(page.locator(".branch:not(.future)")).to_have_count(9)
        step("LQ One: ручной ввод биологического возраста, модели, версии, достоверности и даты — показан в адаптационном профиле, в LMB не входит; респираторный профиль — «в работе»")

        page.locator("section[aria-labelledby=dv-dev]").get_by_role("button", name=re.compile("^SCORE2: Z")).click()
        ticks = [t.replace(",", ".").replace("−", "-") for t in page.locator(".dev-detail .traj-tick").all_text_contents()]
        values = [float(t) for t in ticks if re.fullmatch(r"-?\d+(\.\d+)?", t)]
        assert values and min(values) >= 0, f"отрицательная отметка шкалы риска: {ticks}"
        page.screenshot(path=SHOTS / "calc_12_score2_scale.png", full_page=False)
        step(f"шкала риска SCORE2 без отрицательных отметок: {', '.join(ticks)}")

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
        page.locator("input[type=file][accept^='.json']").set_input_files(saved)
        expect(page.get_by_label("ACR лаборатории", exact=True)).to_have_value("2,5")
        import json, tempfile
        legacy = json.loads(open(saved, encoding="utf-8").read())
        legacy["lmb_minus_phenoage"] = 8.5                                     # устаревшее поле сравнения
        legacy["form"]["pheno_control"] = {"compare": True}
        tmp = Path(tempfile.mkdtemp()) / "old-case.json"
        tmp.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        page.get_by_role("button", name="Очистить").click()
        page.locator("input[type=file][accept^='.json']").set_input_files(str(tmp))
        expect(page.locator(".alert")).to_contain_text("Открыт файл old-case.json")
        tab("Результаты")
        expect(lmb.locator(".bio-value")).to_contain_text("58,6")
        step("файл сохраняется и открывается; старый файл с полями сравнения открывается, лишнее игнорируется")

        page.get_by_role("button", name="Сформировать отчёт").click()
        report = page.locator(".report")
        expect(report).to_contain_text("PhenoAge")
        expect(report).to_contain_text("основные 6,5 % · бедро 1 %")
        expect(report).to_contain_text("официальный FRAX")
        expect(report).to_contain_text("источник: расчёт по альбумину и креатинину мочи")
        expect(report).not_to_contain_text("LMB − PhenoAge")
        expect(report.locator(".cardio-check")).to_have_count(0)
        expect(report.locator(".report-method")).to_contain_text("О методике")
        expect(report.locator(".report-model .dv-row")).to_have_count(7)                 # диаграмма вкладов
        expect(report.locator(".report-model .model-table")).to_contain_text("Оценка системы")
        main_table = report.locator(".report-table:not(.compact)")
        expect(main_table.locator("thead")).not_to_contain_text("Оценка системы")
        expect(report).to_contain_text("Биологический возраст LQ One")
        expect(report).to_contain_text("Респираторный профиль")
        rtext = report.inner_text()
        assert rtext.count("Клиническая валидация не проведена") == 1, "методика в отчёте повторяется"
        assert rtext.index("О методике") > rtext.index("Клинические индексы и показатели"), "методика — в конце отчёта"
        page.screenshot(path=SHOTS / "calc_07_report.png", full_page=True)
        page.emulate_media(media="print")
        expect(page.locator(".tabs")).to_be_hidden()
        expect(page.locator(".topbar")).to_be_hidden()
        page.pdf(path=str(SHOTS / "calc_report.pdf"), format="A4")
        page.emulate_media(media="screen")
        page.get_by_role("button", name="К результатам").click()
        step("отчёт по кнопке: PhenoAge, оба риска FRAX (перенесены из официального), источник ACR; методика — одним блоком в конце; печать в PDF")

        example(2)
        tab("Результаты")
        expect(pheno.locator(".figure-value")).to_contain_text("38,1")
        expect(lmb.locator(".bio-value")).to_contain_text("46,9")
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
