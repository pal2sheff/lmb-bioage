"""Сквозная проверка интерфейса врача на синтетических данных.

Поднимает временный PostgreSQL, применяет миграции, создаёт клинику и врача с TOTP,
запускает сервер с собранным интерфейсом и проходит сценарий в Chromium (Playwright):
вход → новый пациент → визит → анализы → исправление → анкета → FRAX вручную → расчёт →
второй визит без анкеты: ручной FRAX с файлом результата → скачивание файла → расчёт.
Снимки экрана сохраняются в e2e/screens/. Все данные выдуманы.

Запуск из lmb-web: npm run build && python3 e2e/run_e2e.py
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
SERVER = WEB.parent / "lmb-server"
ENGINE = WEB.parent / "lmb-engine"
SHOTS = WEB / "e2e" / "screens"
sys.path[:0] = [str(SERVER), str(ENGINE)]

import pyotp  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402

from tests.pgcluster import PgCluster  # noqa: E402

PORT = 8765
PASSWORD = "demo-password-2026"
SECRET = pyotp.random_base32()
EMAIL = "doctor@demo.lmb"
STEPS = []
SYNTHETIC_PDF = b"%PDF-1.4\n% LMB-E2E-SYNTHETIC FRAX result (fictional)\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def step(name):
    STEPS.append(name)
    print(f"  ✓ {name}")


def main() -> int:
    cluster = PgCluster().start()
    try:
        os.environ.update({
            "LMB_DATABASE_URL": cluster.url("lmb_app", driver="postgresql+psycopg"),
            "LMB_ADMIN_DATABASE_URL": cluster.url("lmb_admin", driver="postgresql+psycopg"),
            "LMB_FIELD_KEY": Fernet.generate_key().decode(),
            "LMB_INDEX_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
            "LMB_COOKIE_SECURE": "false", "LMB_ENVIRONMENT": "test", "LMB_ARGON2_PROFILE": "test",
            "LMB_STATIC_DIR": str(WEB / "dist"),
            "LMB_FILES_DIR": os.path.join(cluster.dir, "files"),
            "LMB_FILES_KEY": Fernet.generate_key().decode(),
        })
        env = dict(os.environ, PYTHONPATH=f"{SERVER}:{ENGINE}")
        subprocess.run(["alembic", "upgrade", "head"], cwd=SERVER, env=env, check=True, capture_output=True)

        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from lmb_server.bootstrap import create_clinic, create_user
        from lmb_server.security import encrypt
        with Session(create_engine(os.environ["LMB_ADMIN_DATABASE_URL"])) as s, s.begin():
            c = create_clinic(s, "Love my body (демо)")
            u = create_user(s, c.id, EMAIL, "Доктор Демо", PASSWORD, ["doctor"])
            u.totp_secret_enc, u.totp_enabled = encrypt(SECRET), True

        import uvicorn

        from lmb_server.main import create_app
        server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=PORT, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        while not server.started:
            time.sleep(0.1)
        try:
            run_browser()
        finally:
            server.should_exit = True
            time.sleep(0.5)
    finally:
        cluster.stop()
    print(f"Сценарий пройден: {len(STEPS)} шагов")
    return 0


def run_browser() -> None:
    from playwright.sync_api import expect, sync_playwright

    SHOTS.mkdir(parents=True, exist_ok=True)
    base = f"http://127.0.0.1:{PORT}"
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page(viewport={"width": 1360, "height": 900}, locale="ru-RU", color_scheme="light")
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(base)
        expect(page.get_by_role("heading", name="Вход")).to_be_visible()
        page.screenshot(path=SHOTS / "01_login.png")
        page.get_by_label("Электронная почта").fill(EMAIL)
        page.get_by_label("Пароль").fill(PASSWORD)
        page.get_by_label("Код из приложения-аутентификатора").fill("000000")
        page.get_by_role("button", name="Войти").click()
        expect(page.get_by_role("alert")).to_contain_text("второго фактора")
        step("неверный код второго фактора отклонён")
        page.get_by_label("Код из приложения-аутентификатора").fill(pyotp.TOTP(SECRET).now())
        page.get_by_role("button", name="Войти").click()
        expect(page.get_by_role("heading", name="Пациенты")).to_be_visible()
        step("вход с паролем и TOTP")

        page.get_by_role("button", name="Новый пациент").click()
        dlg = page.locator("dialog")
        dlg.get_by_label("Фамилия").fill("Синтетическая")
        dlg.get_by_label("Имя").fill("Айгерим")
        dlg.get_by_label("ИИН").fill("600101400123")
        dlg.get_by_label("Дата рождения").fill("1960-01-15")
        dlg.get_by_label("Пол (для алгоритмов)").select_option("female")
        page.screenshot(path=SHOTS / "02_new_patient.png")
        dlg.get_by_role("button", name="Создать карточку").click()
        expect(page.get_by_role("heading", name="Синтетическая Айгерим")).to_be_visible()
        expect(page.get_by_text("ИИН ********0123")).to_be_visible()
        page.get_by_role("link", name="Пациенты").click()
        page.get_by_label("Поиск пациента").fill("синтетическая")
        page.get_by_role("button", name="Найти").click()
        expect(page.get_by_role("link", name="Синтетическая Айгерим")).to_be_visible()
        page.get_by_label("Поиск пациента").fill("Синтет")
        page.get_by_role("button", name="Найти").click()
        expect(page.get_by_text("Пациенты не найдены.")).to_be_visible()
        page.get_by_label("Поиск пациента").fill("СИНТЕТИЧЕСКАЯ")
        page.get_by_role("button", name="Найти").click()
        page.get_by_role("link", name="Синтетическая Айгерим").click()
        expect(page.get_by_role("heading", name="Синтетическая Айгерим")).to_be_visible()
        step("карточка создана, ИИН замаскирован; ФИО зашифровано, поиск по полной фамилии")

        page.get_by_label("Дата обследования").fill("2026-10-10")
        page.get_by_role("button", name="Открыть визит").click()
        expect(page.get_by_role("tab", name="Анализы и измерения")).to_be_visible()
        step("визит открыт")

        values = {"Рост": ("160", None), "Масса тела": ("62", None), "Окружность талии": ("82", None),
                  "Систолическое АД": ("132", None), "Глюкоза натощак": ("5,4", None),
                  "Инсулин натощак": ("8,1", None), "Триглицериды": ("1,3", None), "Общий холестерин": ("5,6", None),
                  "ЛПВП": ("1,4", None), "Креатинин сыворотки": ("71", None), "Альбумин мочи": ("12", None),
                  "Креатинин мочи": ("8,5", None), "АСТ": ("24", None), "АЛТ": ("21", None),
                  "Тромбоциты": ("238", None), "Нейтрофилы абс.": ("3,6", None), "Лимфоциты абс.": ("2,0", None),
                  "T-показатель шейки бедра (референс NHANES III)": ("-1,8", None)}
        for name, (v, _) in values.items():
            row = page.locator(".obs-row").filter(has=page.locator(".obs-name", has_text=name)).first
            row.get_by_label(name, exact=True).fill(v)
            row.get_by_role("button", name="Сохранить").click()
            expect(row.get_by_text("ред. 1")).to_be_visible()
        step(f"внесено {len(values)} показателей с десятичной запятой")

        row = page.locator(".obs-row").filter(has=page.locator(".obs-name", has_text="Масса тела")).first
        row.get_by_role("button", name="Исправить").click()
        row.get_by_label("Масса тела", exact=True).fill("63")
        row.get_by_role("button", name="Сохранить").click()
        expect(page.get_by_text("Укажите причину исправления")).to_be_visible()
        page.get_by_placeholder("Причина исправления (обязательно)").fill("Повторное взвешивание")
        row.get_by_role("button", name="Сохранить").click()
        expect(row.get_by_text("ред. 2")).to_be_visible()
        page.get_by_label("показать историю редакций").check()
        expect(page.locator(".obs-old").filter(has_text="Масса тела")).to_be_visible()
        page.screenshot(path=SHOTS / "03_observations.png", full_page=True)
        step("исправление с причиной, история редакций сохранена")

        page.get_by_role("tab", name="Анкета").click()
        answers = {
            "Анализ сдан натощак": "Да", "Креатинин стандартизован по IDMS": "Да",
            "Острая инфекция или значимое воспаление": "Нет", "Острое изменение функции почек": "Нет",
            "Острое поражение печени": "Нет", "Сахарный диабет": "Нет", "Инсулинотерапия": "Нет",
            "Установленное атеросклеротическое ССЗ": "Нет", "Известная хроническая болезнь почек": "Нет",
            "Семейная гиперхолестеринемия": "Нет", "Очень высокий отдельный фактор риска": "Нет",
            "Текущее курение": "Нет", "Алкоголь": "Нет", "Предшествующий низкоэнергетический перелом": "Да",
            "Перелом бедра у матери или отца": "Нет", "Пероральные глюкокортикоиды": "Нет",
            "Подтверждённый ревматоидный артрит": "Нет", "Заболевание, тесно связанное с остеопорозом": "Нет",
            "Физическая активность не менее 2 раз": "Активен",
        }
        for label, opt in answers.items():
            grp = page.locator(".q-row").filter(has=page.locator(".q-label", has_text=label)).first
            grp.get_by_role("radio", name=opt, exact=True).click()
        page.get_by_label("Полные годы обучения (школа, колледж, вуз)").fill("12")
        page.screenshot(path=SHOTS / "04_questionnaire.png", full_page=True)
        page.get_by_role("button", name="Сохранить изменения").click()
        expect(page.get_by_text("Ответы сохранены")).to_be_visible()
        step("анкета: «да / нет / не знаю»")

        page.get_by_role("tab", name="FRAX").click()
        expect(page.get_by_text("Что будет отправлено")).to_be_visible()
        expect(page.locator(".kv")).to_contain_text("66")
        expect(page.locator(".kv")).not_to_contain_text("Синтетическая")
        page.get_by_role("button", name="Запросить FRAX").click()
        expect(page.get_by_text("интеграция с FRAX не подключена")).to_be_visible()
        step("автоматический FRAX: честный статус «интеграция не подключена»")
        page.get_by_label("Основные остеопоротические переломы, %").fill("140")
        page.get_by_label("Перелом бедра, %").fill("2,1")
        page.get_by_role("button", name="Внести и подтвердить").click()
        expect(page.get_by_role("alert")).to_be_visible()
        page.get_by_label("Основные остеопоротические переломы, %").fill("11,4")
        page.get_by_role("button", name="Внести и подтвердить").click()
        expect(page.get_by_text("● действует")).to_be_visible()
        page.screenshot(path=SHOTS / "05_frax.png", full_page=True)
        step("ручной FRAX: 140 % отклонено, 11,4 % принято и действует")

        page.get_by_role("tab", name="Профиль").click()
        page.get_by_role("button", name="Рассчитать по текущим данным").click()
        expect(page.locator(".branch:not(.future)")).to_have_count(9)
        bone = page.locator(".branch").filter(has_text="Профиль риска переломов")
        expect(bone).to_contain_text("11,4")
        expect(bone).to_contain_text("из официального калькулятора FRAX")
        renal = page.locator(".branch").filter(has_text="Почечный профиль")
        expect(renal.locator(".index-val").first).not_to_have_text("—")
        assert "Z " not in page.locator(".branch-grid").inner_text()       # Z — только на диаграмме
        brain = page.locator(".branch").filter(has_text="Когнитивно-сосудистый профиль")
        expect(brain).to_contain_text("вне области модели CAIDE")           # 66 лет: CAIDE 39–64
        charts = page.locator("section[aria-labelledby=dv-branches]")       # графики общие с калькулятором, видны сразу
        expect(charts.locator(".dv-row").filter(has_text="Почечный")).not_to_have_class("dv-row is-missing")
        expect(charts.locator(".dv-row.is-missing").filter(has_text="Когнитивно")).to_contain_text("вне области")
        expect(page.locator(".dev-grid .dev-row").filter(has_text="eGFR")).to_have_count(1)
        card = page.locator(".age-summary")
        expect(card.locator(".figure").first).to_contain_text("66")                 # календарный возраст
        expect(card).to_contain_text("не рассчитан")                                # 66 лет: вне области 40–64
        expect(card.locator(".why")).to_contain_text("вне технической области тестирования 40–64")
        assert "Клинический итог" not in page.locator("main").inner_text()        # статус — в «О методике»
        pheno = page.locator(".pheno-card:not(.age-side)")                                         # самостоятельный показатель
        expect(pheno).to_contain_text("не рассчитан")                               # нет входов PhenoAge
        expect(pheno.locator(".short-notes")).to_contain_text("не хватает")
        expect(page.locator("main")).not_to_contain_text("LMB − PhenoAge")
        page.get_by_role("button", name="О методике", exact=True).click()
        expect(page.locator("#method")).to_contain_text("Клинический итог не рассчитан")
        expect(page.locator("#method")).to_contain_text("Редакция модели")
        page.keyboard.press("Escape")
        expect(page.locator("#method")).to_have_count(0)
        page.get_by_role("button", name="Проверить воспроизводимость").click()
        expect(page.get_by_text("результат совпадает полностью")).to_be_visible()
        page.wait_for_timeout(800)  # дождаться анимации появления карточек
        page.screenshot(path=SHOTS / "06_profile.png", full_page=True)
        step("профиль 9 веток без Z в карточках, графики сразу, LMB: неприменим вне 40–64 (с причиной), PhenoAge — отдельно, без входов не считается, статус и метаданные в «О методике», расчёт воспроизводится")

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        page.screenshot(path=SHOTS / "07_profile_mobile.png", full_page=False)
        page.set_viewport_size({"width": 1360, "height": 900})

        # второй визит: анкета и измерения не заполнены, ручной FRAX всё равно доступен
        page.locator(".crumbs a", has_text="Синтетическая").click()
        page.get_by_label("Дата обследования").fill("2026-10-09")
        page.get_by_role("button", name="Открыть визит").click()
        page.get_by_role("tab", name="FRAX").click()
        expect(page.get_by_text("заполнены не полностью")).to_be_visible()
        expect(page.get_by_role("button", name="Запросить FRAX")).to_be_disabled()
        page.get_by_label("Основные остеопоротические переломы, %").fill("10,2")
        page.get_by_label("Перелом бедра, %").fill("1,9")
        page.get_by_role("button", name="Внести и подтвердить").click()
        expect(page.get_by_role("alert")).to_contain_text("с МПК")      # выбор «с МПК / без МПК» обязателен
        page.get_by_role("radio", name="без МПК").click()
        page.get_by_label("Файл результата (PDF, PNG или JPEG)").set_input_files(
            files=[{"name": "frax_synthetic.pdf", "mimeType": "application/pdf", "buffer": SYNTHETIC_PDF}])
        page.get_by_role("button", name="Внести и подтвердить").click()
        expect(page.get_by_text("файл сохранён на сервере клиники")).to_be_visible()
        expect(page.get_by_text("● действует")).to_be_visible()
        expect(page.locator("table.ledger")).to_contain_text("анкета неполная")
        with page.expect_download() as dl:
            page.get_by_role("link", name="скачать").click()
        assert Path(dl.value.path()).read_bytes() == SYNTHETIC_PDF
        stored = list(Path(os.environ["LMB_FILES_DIR"]).rglob("*.lmbenc"))
        assert len(stored) == 1 and b"LMB-E2E-SYNTHETIC" not in stored[0].read_bytes()
        page.screenshot(path=SHOTS / "08_frax_manual_file.png", full_page=True)
        step("ручной FRAX без анкеты, с файлом: файл на диске зашифрован и скачивается без изменений")

        page.get_by_role("tab", name="Профиль").click()
        page.get_by_role("button", name="Рассчитать по текущим данным").click()
        bone = page.locator(".branch").filter(has_text="Профиль риска переломов")
        expect(bone).to_contain_text("10,2")
        expect(bone).to_contain_text("без полного набора")
        step("ручной результат применён в расчёте с предупреждением о неполных входах")
        if errors:
            raise AssertionError(f"Ошибки JavaScript: {errors}")
        step("нет ошибок JavaScript")
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
