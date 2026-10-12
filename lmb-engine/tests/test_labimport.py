"""Импорт лабораторных результатов: распознавание, различение материалов и единиц, «<»/«>», повторы и даты."""
import datetime as dt
import io
import zipfile

from lmb_engine.labimport import candidates, import_file, parse_value, rows_from_lines, unit_code

ENC = dt.date(2026, 10, 10)


def by_code(res, code):
    return [i for i in res["items"] if i["code"] == code]


def one(res, code):
    items = by_code(res, code)
    assert len(items) == 1, (code, items)
    return items[0]


def test_units():
    assert unit_code("ммоль/л") == "mmol/L"
    assert unit_code("мкмоль/л") == "umol/L"
    assert unit_code("×10^9/л") == "10^9/L"
    assert unit_code("10*9/л") == "10^9/L"
    assert unit_code("10⁹/л") == "10^9/L"
    assert unit_code("мкЕд/мл") == "uU/mL"
    assert unit_code("мкМЕ/мл") == "uU/mL"
    assert unit_code("Ед/л") == "U/L"
    assert unit_code("фл") == "fL"
    assert unit_code("мг/ммоль") == "mg/mmol"
    assert unit_code("попугаи/л") is None


def test_comparator_kept():
    assert parse_value("< 0.5") == ("<", "0,5")
    assert parse_value(">300") == (">", "300")
    assert parse_value("≤1") == ("<", "1")
    assert parse_value("5,2") == ("", "5,2")
    assert parse_value("3,9 - 5,5") is None


TABLE = [
    ["Лаборатория (синтетический пример)"],
    ["Дата взятия: 10.10.2026"],
    ["Показатель", "Результат", "Ед. изм.", "Референс"],
    ["Глюкоза", "5,2", "ммоль/л", "3,9-5,5"],
    ["Инсулин", "8", "мкЕд/мл", "2,6-24,9"],
    ["Креатинин", "70", "мкмоль/л", "44-80"],
    ["Креатинин в разовой порции мочи", "10", "ммоль/л", ""],
    ["Альбумин", "44", "г/л", "35-52"],
    ["Микроальбумин (моча)", "20", "мг/л", "<30"],
    ["Альбумин/креатинин мочи", "2,5", "мг/ммоль", "<3"],
    ["Нейтрофилы, абс.", "3,5", "×10^9/л", ""],
    ["Нейтрофилы, %", "55,6", "%", ""],
    ["Лимфоциты #", "2,0", "10^9/л", ""],
    ["Лимфоциты %", "31,7", "%", ""],
    ["RDW-CV", "13,4", "%", ""],
    ["RDW-SD", "42,1", "фл", ""],
    ["С-реактивный белок (высокочувствительный)", "< 0,5", "мг/л", ""],
    ["Холестерин ЛПВП", "1,5", "ммоль/л", ""],
    ["Холестерин общий", "5,4", "ммоль/л", ""],
    ["Холестерин ЛПНП", "3,2", "ммоль/л", ""],
    ["Ферритин", "80", "нг/мл", ""],
]


def test_table_mapping():
    r = candidates(TABLE, ENC)
    assert r["doc_date"] == "2026-10-10"
    assert one(r, "glucose_fasting")["value"] == "5,2" and one(r, "glucose_fasting")["selected"]
    assert one(r, "insulin_fasting")["unit"] == "uU/mL"
    # кровь и моча различаются
    assert one(r, "creatinine_serum")["value"] == "70"
    assert one(r, "u_creatinine")["value"] == "10"
    assert one(r, "albumin_serum")["value"] == "44"
    assert one(r, "u_albumin")["value"] == "20"
    assert one(r, "acr_lab")["unit"] == "mg/mmol"
    # абсолютные значения переносятся, проценты — нет
    assert [i["value"] for i in by_code(r, "neutrophils_abs") if i["status"] == "ok"] == ["3,5"]
    assert any(i["status"] == "skip" and "процент" in i["reason"] for i in by_code(r, "neutrophils_abs"))
    assert [i["value"] for i in by_code(r, "lymphocytes_abs") if i["selected"]] == ["2,0"]
    # RDW-CV — да, RDW-SD — нет
    rdw = by_code(r, "rdw")
    assert [i["value"] for i in rdw if i["selected"]] == ["13,4"]
    assert any(i["status"] == "skip" and "RDW-SD" in i["reason"] for i in rdw)
    # «<» сохраняется
    crp = one(r, "crp")
    assert crp["comparator"] == "<" and crp["value"] == "0,5" and "не как точное число" in crp["reason"]
    # ЛПНП и ферритин не подставляются никуда
    assert one(r, "tc")["value"] == "5,4" and one(r, "hdl")["value"] == "1,5"
    assert "Холестерин ЛПНП" in r["unmatched"] and "Ферритин" in r["unmatched"]


def test_duplicates_and_dates():
    rows = [["Показатель", "Результат", "Ед.", "Дата"],
            ["Глюкоза", "5,9", "ммоль/л", "01.09.2026"],
            ["Глюкоза", "5,2", "ммоль/л", "09.10.2026"],
            ["АЛТ", "20", "Ед/л", "09.10.2026"]]
    r = candidates(rows, ENC)
    g = by_code(r, "glucose_fasting")
    chosen = [i for i in g if i["selected"]]
    assert len(chosen) == 1 and chosen[0]["value"] == "5,2"            # ближайшая к дате обследования
    assert all(i.get("duplicate", "").startswith("несколько дат") for i in g)
    assert one(r, "alt")["date_differs"] is True


def test_unit_checks():
    rows = [["Креатинин", "0,07", "ммоль/л"], ["Инсулин", "55", "пмоль/л"], ["АСТ", "22", ""],
            ["Лейкоциты", "6,3", "×10^9/л"], ["Нейтрофилы", "3,5", ""]]
    r = candidates(rows, ENC)
    assert one(r, "creatinine_serum")["status"] == "check"             # ммоль/л — похоже на мочу
    assert one(r, "insulin_fasting")["status"] == "skip"               # пмоль/л без утверждённой конверсии
    assert one(r, "ast")["status"] == "check" and not one(r, "ast")["selected"]
    assert one(r, "wbc")["selected"]
    assert one(r, "neutrophils_abs")["status"] == "check"              # неясно: абсолютное или процент


def test_pdf_lines_inline():
    lines = ["ООО «Синтетическая лаборатория»   Дата взятия: 10.10.2026",
             "Глюкоза 5,2 ммоль/л 3,9–5,5",
             "Щелочная фосфатаза\t78\tЕд/л\t40-150",
             "Лимфоциты, абс.  2,0  ×10^9/л",
             "MCV 91 фл 80-100"]
    r = candidates(rows_from_lines(lines), ENC)
    assert one(r, "glucose_fasting")["value"] == "5,2"
    assert one(r, "alp")["value"] == "78"
    assert one(r, "lymphocytes_abs")["unit"] == "10^9/L"
    assert one(r, "mcv")["unit"] == "fL"


def test_lqone_report_only_in_lqone_document():
    lqone = ["Результаты автоматической интерпретации стрессовой нагрузки", "Достоверность измерения 87 %",
             "Геронтологическая кривая", "Биологический возраст, лет 52", "Отклонение биологического возраста, лет -3"]
    r = candidates(rows_from_lines(lqone), ENC)
    assert one(r, "lqone_bioage_years")["value"] == "52" and one(r, "lqone_bioage_years")["unit"] == "years"
    assert one(r, "lqone_reliability_pct")["value"] == "87"
    other = candidates(rows_from_lines(["Биологический возраст 40 лет"]), ENC)
    assert not by_code(other, "lqone_bioage_years")


def _xlsx(rows):
    def col(i):
        return chr(65 + i)
    sheet = "".join(
        f'<row r="{r + 1}">' + "".join(
            f'<c r="{col(c)}{r + 1}" t="inlineStr"><is><t>{v}</t></is></c>' if isinstance(v, str)
            else f'<c r="{col(c)}{r + 1}"><v>{v}</v></c>' for c, v in enumerate(row)) + "</row>"
        for r, row in enumerate(rows))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   '<sheet name="Лист1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
                   '2006/relationships"><Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
                   '</Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
                   f'2006/main"><sheetData>{sheet}</sheetData></worksheet>')
    return buf.getvalue()


def test_xlsx_and_csv_files():
    data = _xlsx([["Показатель", "Результат", "Ед. изм.", "Дата"],
                  ["Триглицериды", 1.3, "ммоль/л", 46305],      # дата Excel 10.10.2026
                  ["Тромбоциты", 240, "10^9/л", 46305]])
    r = import_file("lab.xlsx", data, ENC)
    assert one(r, "tg")["value"] == "1,3" and one(r, "tg")["date"] == "2026-10-10"
    assert one(r, "platelets")["selected"]
    csv_bytes = "Показатель;Результат;Ед.\nАЛТ;20;Ед/л\nАСТ;22;Ед/л\n".encode("cp1251")
    r = import_file("lab.csv", csv_bytes, ENC)
    assert one(r, "alt")["value"] == "20" and one(r, "ast")["value"] == "22"


def test_pdf_row_without_cell_border():
    """pdf.js склеил название и значение пробелом: строка разбирается целиком."""
    r = candidates(rows_from_lines(["Исследование\tРезультат\tЕд. изм.", "Щелочная фосфатаза 78\tЕд/л",
                                    "АЛТ\t20\tЕд/л"]), ENC)
    assert one(r, "alp")["value"] == "78" and one(r, "alp")["unit"] == "U/L"
    assert one(r, "alt")["value"] == "20"
