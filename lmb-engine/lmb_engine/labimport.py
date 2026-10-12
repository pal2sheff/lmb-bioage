"""Импорт лабораторных результатов из таблиц (CSV, XLSX) и текстовых строк PDF.

Модуль только распознаёт строки и предлагает соответствие полям приложения; перенос
подтверждает врач. Ничего не рассчитывается и не «исправляется»:
- значения «< …» и «> …» сохраняются с знаком сравнения, а не превращаются в точное число;
- проценты лейкоформулы не подставляются вместо абсолютных значений;
- RDW-SD не подставляется вместо RDW-CV;
- креатинин и альбумин крови и мочи различаются по названию и единице;
- единица, не входящая в утверждённые для поля, отмечается для проверки.

Работает на стандартной библиотеке Python (в браузере — в Pyodide): файл не покидает компьютер.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
import zipfile
from typing import Iterable, Optional
from xml.etree import ElementTree as ET

from .units import INPUTS

# ---------------------------------------------------------------- единицы
# Нормализованная запись единицы (нижний регистр, без пробелов, µ/μ → u) → код единицы справочника.
_UNIT_PATTERNS = [
    (r"^ммоль/л$|^mmol/l$", "mmol/L"),
    (r"^(мкмоль|мкм|umol)/л$|^umol/l$", "umol/L"),
    (r"^мг/дл$|^mg/dl$", "mg/dL"),
    (r"^г/л$|^g/l$", "g/L"),
    (r"^г/дл$|^g/dl$", "g/dL"),
    (r"^мг/л$|^mg/l$", "mg/L"),
    (r"^(е|e)д/л$|^ме/л$|^u/l$|^iu/l$|^me/л$", "U/L"),
    (r"^(мк(е|e)д|мкме|uiu|uu|мкмe)/мл$|^(uiu|uu)/ml$|^м(е|e)д/л$|^mu/l$|^miu/l$", "uU/mL"),
    (r"^пмоль/л$|^pmol/l$", "pmol/L"),
    (r"^(x|х|\*)?10(\^|\*|е|e)?9/(л|l)$|^тыс/мкл$|^(x|х|\*)?10(\^|\*|е|e)?3/(мкл|ul)$|^гига/л$", "10^9/L"),
    (r"^%$", "%"),
    (r"^(фл|fl)$", "fL"),
    (r"^мг/ммоль$|^mg/mmol$", "mg/mmol"),
    (r"^мг/г$|^mg/g$", "mg/g"),
    (r"^(лет|год|года|years?)$", "years"),
]


def _norm_unit(s: str) -> str:
    s = s.strip().lower().replace(" ", "").replace("µ", "u").replace("μ", "u")
    s = s.replace("⁹", "^9").replace("³", "^3").replace("×", "x").replace("ё", "е")
    return s.strip(".,;")


def unit_code(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    n = _norm_unit(s)
    for pat, code in _UNIT_PATTERNS:
        if re.match(pat, n):
            return code
    return None


def _looks_like_unit(s: str) -> bool:
    n = _norm_unit(s)
    return unit_code(s) is not None or bool(re.match(r"^[a-zа-я%^*/0-9]{1,12}/[a-zа-я0-9.]{1,6}$", n))


# ---------------------------------------------------------------- показатели
URINE = r"моч|urine|\burin"
# (код поля, шаблон названия, шаблон исключения); порядок важен: частные правила раньше общих.
_RULES = [
    ("acr_lab", r"альбумин\w*\s*/\s*креатинин|альбумин\w*-креатинин\w* отнош|отношение\s+альбумин|\bacr\b|\bакс\b", None),
    ("u_albumin", r"микроальбумин|\bmau\b|\bmalb\b|альбумин\w*.*(" + URINE + ")|(" + URINE + ").*альбумин", None),
    ("u_creatinine", r"креатинин\w*.*(" + URINE + ")|(" + URINE + ").*креатинин|\bucrea", r"клиренс|/"),
    ("albumin_serum", r"альбумин|\balb\b|albumin", r"микро|глобулин|преальбумин|/|" + URINE),
    ("creatinine_serum", r"креатинин|\bcrea|creatinine", r"клиренс|скф|egfr|/|" + URINE),
    ("glucose_fasting", r"глюкоз|\bglu\b|glucose",
     r"гемоглобин|hba1c|толерант|нагрузк|через\s*\d|после|" + URINE),
    ("insulin_fasting", r"инсулин|insulin", r"антител|после|через|индекс|homa|c-пептид|igf|инсулиноподоб"),
    ("tg", r"триглицерид|\btg\b|\btrig", None),
    ("hdl", r"лпвп|\bhdl|высокой плотности|\bлвп\b", r"не-лпвп|non"),
    ("tc", r"холестерин|\bchol\b|\btc\b|cholesterol",
     r"лпвп|лпнп|лпонп|hdl|ldl|vldl|не-лпвп|non|высокой|низкой|ремнант|коэффициент|индекс|атероген"),
    ("ast", r"\bаст\b|\bast\b|аспартат|\bасат\b|\bgot\b", r"/"),
    ("alt", r"\bалт\b|\balt\b|аланин|\bалат\b|\bgpt\b", r"/"),
    ("rdw", r"\brdw|ширина распределения эритроцит", None),
    ("mcv", r"\bmcv\b|средний объем эритроцит", None),
    ("platelets", r"тромбоцит|\bplt\b", r"объем|\bmpv|\bpdw|\bpct|тромбокрит|агрегац|антител"),
    ("wbc", r"лейкоцит|\bwbc\b", r"формул|п/зр|в поле|осадок|кал|" + URINE),
    ("neutrophils_abs", r"нейтрофил|\bneu", r"палочк|сегмент|юные|миелоц|лимфоцит|/"),
    ("lymphocytes_abs", r"лимфоцит|\blym", r"атипичн|реактивн|нейтроф|субпопул|\bcd\d|/"),
    ("crp", r"[сc]-?реактивн|\bсрб\b|\bcrp\b|hs-?crp|вч-?срб", None),
    ("alp", r"щелочн\w*\s+фосфатаз|\bщф\b|\balp\b|\balkp\b", r"костн"),
    ("lqone_bioage_years", r"биологическ\w*\s+возраст", r"отклонени"),
    ("lqone_reliability_pct", r"достоверност\w*\s+измерени", None),
]
_LQONE_MARK = r"lq\s*one|lq1|геронтологическ|достоверност\w*\s+измерени|стрессов\w* нагрузк"
_PCT_FIELDS = ("neutrophils_abs", "lymphocytes_abs")
ACR_UNITS = ("mg/mmol", "mg/g")


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("ё", "е")).strip()


def field_name(code: str) -> str:
    if code == "acr_lab":
        return "ACR лаборатории"
    return INPUTS[code].name_ru if code in INPUTS else code


def allowed_units(code: str) -> tuple:
    if code == "acr_lab":
        return ACR_UNITS
    return tuple(INPUTS[code].conversions)


def match_field(name: str, lqone_doc: bool) -> Optional[str]:
    n = _norm_name(name)
    for code, inc, exc in _RULES:
        if code.startswith("lqone_") and not lqone_doc:
            continue
        if re.search(inc, n) and not (exc and re.search(exc, n)):
            return code
    return None


# ---------------------------------------------------------------- значения и даты
_NUM = r"[<>≤≥]?\s*[-−]?\d+(?:[.,]\d+)?"
_NUM_CELL = re.compile(r"^\s*(?P<cmp>[<>≤≥])?\s*(?P<num>[-−]?\d+(?:[.,]\d+)?)\s*(?:[↑↓*HLВНhl!]{1,2})?\s*$")
_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")
_DATE_LABEL = r"дата\s*(взятия|забора|исследования|выполнения|анализа|регистрации|измерения)|дата|взят|date"


def parse_value(cell: str) -> Optional[tuple]:
    """«5,2» → ('', '5,2'); «< 0.5» → ('<', '0,5'); иначе None. Знак сравнения сохраняется."""
    m = _NUM_CELL.match(cell or "")
    if not m:
        return None
    cmp_ = {"≤": "<", "≥": ">"}.get(m.group("cmp") or "", m.group("cmp") or "")
    return cmp_, m.group("num").replace(".", ",").replace("−", "-")


def parse_date(s: str) -> Optional[dt.date]:
    m = _DATE.search(s or "")
    if not m:
        return None
    try:
        if m.group(1):
            return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        return dt.date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
    except ValueError:
        return None


def _excel_date(cell: str) -> Optional[dt.date]:
    try:
        x = float(cell.replace(",", "."))
    except ValueError:
        return None
    if 20000 < x < 80000:
        return dt.date(1899, 12, 30) + dt.timedelta(days=int(x))
    return None


# ---------------------------------------------------------------- чтение файлов
def rows_from_csv(data: bytes) -> list:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Не удалось определить кодировку CSV (ожидается UTF-8 или Windows-1251)")
    sample = text[:4096]
    delim = max(";\t,", key=lambda d: sample.count(d)) if any(d in sample for d in ";\t,") else ";"
    return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text), delimiter=delim)]


_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def rows_from_xlsx(data: bytes) -> list:
    """Все листы книги подряд; ячейки — текст как в файле (числа — с точкой)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ValueError("Файл не похож на книгу Excel (XLSX)") from e
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % _NS["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            if r.tag == _REL + "Relationship"}
    rows = []
    for sh in wb.findall("m:sheets/m:sheet", _NS):
        target = rels.get(sh.get("{%s}id" % _NS["r"]), "")
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        if path not in z.namelist():
            continue
        for row in ET.fromstring(z.read(path)).iter("{%s}row" % _NS["m"]):
            cells: dict = {}
            for c in row.findall("m:c", _NS):
                t = c.get("t")
                v = c.find("m:v", _NS)
                if t == "s" and v is not None:
                    val = shared[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter("{%s}t" % _NS["m"]))
                else:
                    val = v.text if v is not None and v.text is not None else ""
                cells[_col_index(c.get("r", "A1"))] = val.strip()
            if cells:
                rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
    return rows


def rows_from_lines(lines: Iterable[str]) -> list:
    """Строки текстового слоя PDF: ячейки разделены табуляцией (крупный промежуток) или 2+ пробелами."""
    return [[c.strip() for c in re.split(r"\t|\s{2,}", ln) if c.strip()] for ln in lines if ln.strip()]


# ---------------------------------------------------------------- разбор строк
def _header_columns(row: list) -> Optional[dict]:
    low = [_norm_name(c) for c in row]
    cols = {}
    for i, c in enumerate(low):
        if "name" not in cols and re.search(r"показател|исследован|тест|наименован|анализ|parameter|test", c):
            cols["name"] = i
        elif "value" not in cols and re.search(r"результат|значени|result|value", c):
            cols["value"] = i
        elif "unit" not in cols and re.search(r"ед\.?\s*изм|единиц|^ед\.?$|unit", c):
            cols["unit"] = i
        elif "date" not in cols and re.search(_DATE_LABEL, c):
            cols["date"] = i
    return cols if "name" in cols and "value" in cols else None


def _split_inline(cells: list) -> list:
    """Одна ячейка «Глюкоза 5,2 ммоль/л 3,9–5,5» → отдельные ячейки (для строк PDF без табуляции)."""
    if len(cells) != 1:
        return cells
    m = re.match(r"^(?P<name>.*?[A-Za-zА-Яа-яЁё%#.)\]])\s+(?P<val>" + _NUM + r")(?:\s+(?P<rest>.*))?$", cells[0])
    if not m:
        return cells
    rest = (m.group("rest") or "").split()
    return [m.group("name"), m.group("val")] + rest


def parse_rows(rows: list) -> dict:
    """Строки таблицы → записи «название, значение, единица, дата» (без сопоставления полям)."""
    text_all = " ".join(" ".join(r) for r in rows)
    lqone_doc = bool(re.search(_LQONE_MARK, _norm_name(text_all)))
    doc_date = None
    for r in rows[:40]:
        joined = " ".join(r)
        if re.search(_DATE_LABEL, _norm_name(joined)) and parse_date(joined):
            doc_date = parse_date(joined)
            break
    cols = None
    out = []
    for idx, raw in enumerate(rows):
        cells = [c for c in raw]
        if not any(c.strip() for c in cells):
            continue
        hc = _header_columns(cells)
        if hc:
            cols = hc
            continue
        name = value = unit = None
        row_date = None
        if cols and len(cells) > cols["value"]:
            name = cells[cols["name"]] if cols["name"] < len(cells) else ""
            value = parse_value(cells[cols["value"]])
            if "unit" in cols and cols["unit"] < len(cells):
                unit = cells[cols["unit"]] or None
            if "date" in cols and cols["date"] < len(cells):
                row_date = parse_date(cells[cols["date"]]) or _excel_date(cells[cols["date"]])
            if value is None:
                # «5,2 ммоль/л» в одной ячейке
                m = re.match(r"^\s*(" + _NUM + r")\s+(\S+)\s*$", cells[cols["value"]])
                if m:
                    value, unit = parse_value(m.group(1)), unit or m.group(2)
        else:
            cells = _split_inline([c for c in cells if c.strip()])
            name_parts = []
            i = 0
            while i < len(cells) and parse_value(cells[i]) is None:
                name_parts.append(cells[i])
                i += 1
            if i < len(cells):
                value = parse_value(cells[i])
                if i + 1 < len(cells) and _looks_like_unit(cells[i + 1]):
                    unit = cells[i + 1]
            name = " ".join(name_parts)
            row_date = parse_date(" ".join(cells[i + 1:])) if i < len(cells) else None
        if value is None:
            # границы ячеек не распознаны (строка PDF): «Название 78 Ед/л» разбирается целиком
            parts = _split_inline([" ".join(c for c in raw if c.strip())])
            if len(parts) > 1 and parse_value(parts[1]) is not None:
                name, value = parts[0], parse_value(parts[1])
                unit = parts[2] if len(parts) > 2 and _looks_like_unit(parts[2]) else None
                row_date = row_date or parse_date(" ".join(parts[2:]))
        if not name or value is None or not re.search(r"[A-Za-zА-Яа-яЁё]", name):
            continue
        # единица в названии: «Глюкоза (ммоль/л)» или «Глюкоза, ммоль/л»
        if not unit:
            m = re.search(r"[(,]\s*([^()]{1,14}/[^()\s]{1,6}|%)\s*\)?\s*$", name)
            if m and unit_code(m.group(1)):
                unit = m.group(1)
        out.append({"row": idx, "name": name.strip(), "comparator": value[0], "value": value[1],
                    "unit_raw": unit, "date": (row_date or doc_date)})
    return {"entries": out, "doc_date": doc_date, "lqone_doc": lqone_doc}


def _percent_kind(name: str, unit: Optional[str]) -> Optional[str]:
    """Для лейкоформулы: «abs», «pct» или None (неясно)."""
    u = unit_code(unit)
    n = _norm_name(name)
    if u == "%" or re.search(r"%|\bпроц", n):
        return "pct"
    if u == "10^9/L" or re.search(r"#|\bабс|\babs", n):
        return "abs"
    return None


def candidates(rows: list, encounter_date: Optional[dt.date] = None) -> dict:
    """Предложение переноса: для каждой распознанной строки — поле, значение, единица, дата и статус.

    status: ok — можно перенести; check — нужна проверка (перенос не выбран по умолчанию);
    skip — не переносится (причина в reason). selected — выбор по умолчанию.
    """
    parsed = parse_rows(rows)
    items, unmatched = [], []
    for e in parsed["entries"]:
        code = match_field(e["name"], parsed["lqone_doc"])
        if code is None:
            unmatched.append(e["name"])
            continue
        unit = unit_code(e["unit_raw"])
        status, reason = "ok", ""
        if code in _PCT_FIELDS:
            kind = _percent_kind(e["name"], e["unit_raw"])
            if kind == "pct":
                status, reason = "skip", "процент лейкоформулы — нужны абсолютные значения ×10⁹/л"
            elif kind is None:
                status, reason = "check", "не указано, абсолютное это значение или процент"
            elif unit is None:
                unit = "10^9/L"
        if code == "rdw":
            n = _norm_name(e["name"])
            if re.search(r"rdw\W*sd", n) or unit == "fL":
                status, reason = "skip", "RDW-SD (фл) не подставляется вместо RDW-CV (%)"
            elif unit is None and re.search(r"rdw\W*cv", n):
                unit = "%"
        if code == "lqone_bioage_years" and unit is None:
            unit = "years"          # «Биологический возраст, лет» — единица в названии строки отчёта
        if code == "lqone_reliability_pct" and unit is None:
            unit = "%"
        if code == "creatinine_serum" and unit == "mmol/L":
            status, reason = "check", "единица ммоль/л характерна для креатинина мочи — проверьте материал"
        if code == "albumin_serum" and unit == "mg/L":
            status, reason = "check", "единица мг/л характерна для альбумина мочи — проверьте материал"
        if status != "skip":
            if unit is None:
                status, reason = "check", ("единица не указана — проверьте" if not e["unit_raw"]
                                           else f"единица «{e['unit_raw']}» не распознана — проверьте")
            elif code in INPUTS and unit in INPUTS[code].rejected_units:
                status, reason = "skip", INPUTS[code].rejected_units[unit]
            elif unit not in allowed_units(code):
                status, reason = "check", f"единица «{e['unit_raw']}» не подходит для поля"
        if status == "ok" and e["comparator"]:
            reason = "значение за пределом определения: переносится со знаком «" + e["comparator"] + "», не как точное число"
        transferable = status != "skip" and unit is not None and unit in allowed_units(code)
        items.append({**e, "code": code, "field": field_name(code), "unit": unit, "status": status, "reason": reason,
                      "transferable": transferable,
                      "selected": False, "alternative": False,
                      "date": e["date"].isoformat() if e["date"] else None,
                      "date_differs": bool(e["date"] and encounter_date and e["date"] != encounter_date)})

    # повторы одного поля: по умолчанию — дата обследования, иначе ближайшая к ней; остальные — альтернативы
    by_code: dict = {}
    for it in items:
        if it["status"] != "skip":
            by_code.setdefault(it["code"], []).append(it)
    for code, group in by_code.items():
        def dist(it):
            if not it["date"] or not encounter_date:
                return 10 ** 6
            return abs((dt.date.fromisoformat(it["date"]) - encounter_date).days)
        best = min(group, key=lambda it: (dist(it), it["row"]))
        for it in group:
            it["alternative"] = it is not best
            it["selected"] = it is best and it["status"] == "ok" and it["transferable"]
        values = {(it["comparator"], it["value"], it["unit"]) for it in group}
        dates = {it["date"] for it in group}
        if len(group) > 1:
            note = ("несколько дат: " if len(dates) > 1 else "повтор показателя") + \
                   ("" if len(values) > 1 else " (значения совпадают)")
            for it in group:
                it["duplicate"] = note
    return {"items": items, "unmatched": sorted(set(unmatched)),
            "doc_date": parsed["doc_date"].isoformat() if parsed["doc_date"] else None,
            "lqone_doc": parsed["lqone_doc"]}


def import_file(name: str, data: bytes, encounter_date: Optional[dt.date] = None) -> dict:
    low = name.lower()
    if low.endswith(".csv") or low.endswith(".txt"):
        rows = rows_from_csv(data)
    elif low.endswith(".xlsx"):
        rows = rows_from_xlsx(data)
    else:
        raise ValueError("Поддерживаются CSV и XLSX; PDF читается в браузере (текстовый слой)")
    return candidates(rows, encounter_date)
