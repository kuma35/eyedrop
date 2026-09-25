# -*- coding: utf-8 -*-
"""import from eyedrop-stock.ods spreadsheet

JP:
これまで手作業で管理していた LibreOffice Calc のシート
(build/toybox/eyedrop-stock.ods)を取り込みます。
標準ライブラリのみ(zipfile + ElementTree)で読みます。

シート1枚が薬1つ。シート名を登録名とします。
2行目の見出しで列を特定します。

- 登録名(ID) / 現在の薬の名前 / 現在の名前利用開始日: 別名とメモ
- 開封日 / (終了日): ライフタイム。開封日の左の列に文字(「中断→」
  「再開→」等)があればイレギュラー扱い
- 日付 / 入庫数 / 出庫数 / 棚卸? / 残高 / 備考: 在庫

日付セルは表示が「3月5日」のように年が無くても office:date-value に
年月日が入っているのでそれを使います。
"""
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .drugdb import DrugDb

NS = {
    'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
    'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
    'office': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
}
MAX_COLUMNS = 64

HEADERS = {
    'reg_name': '登録名(ID)',
    'alias': '現在の薬の名前',
    'alias_start': '現在の名前利用開始日',
    'open': '開封日',
    'end': '(終了日)',
    'date': '日付',
    'in': '入庫数',
    'out': '出庫数',
    'inventory': '棚卸?',
    'balance': '残高',
    'note': '備考',
}


def _q(prefix: str, name: str) -> str:
    return f'{{{NS[prefix]}}}{name}'


@dataclass
class Cell:
    """spreadsheet cell value

    JP:
    セルの値。 value は date / float / str / None。
    """
    text: str = ''
    value: object = None


def _cell(elem) -> Cell:
    text = '\n'.join(''.join(p.itertext())
                     for p in elem.findall(_q('text', 'p'))).strip()
    kind = elem.get(_q('office', 'value-type'))
    value = None
    if kind == 'date':
        value = date.fromisoformat(elem.get(_q('office', 'date-value'))[:10])
    elif kind == 'float':
        value = float(elem.get(_q('office', 'value')))
    elif text:
        value = text
    return Cell(text, value)


def read_sheets(path) -> dict[str, list[list[Cell]]]:
    """read all sheets as rows of cells

    JP:
    全シートを {シート名: 行のリスト} で読む。
    """
    with zipfile.ZipFile(path) as ods:
        root = ET.fromstring(ods.read('content.xml'))
    sheets = {}
    for table in root.iter(_q('table', 'table')):
        rows = []
        for row in table.iter(_q('table', 'table-row')):
            cells = []
            for elem in row:
                if elem.tag not in (_q('table', 'table-cell'),
                                    _q('table', 'covered-table-cell')):
                    continue
                repeat = int(elem.get(
                    _q('table', 'number-columns-repeated'), '1'))
                cell = _cell(elem)
                for _ in range(min(repeat, MAX_COLUMNS - len(cells))):
                    cells.append(cell)
            while cells and cells[-1].value is None:
                cells.pop()
            # 行の繰り返し(number-rows-repeated)は空行か書式だけの行なので
            # 1行として扱う
            rows.append(cells)
        while rows and not rows[-1]:
            rows.pop()
        sheets[table.get(_q('table', 'name'))] = rows
    return sheets


def _as_date(cell: Optional[Cell]) -> Optional[date]:
    if cell is None:
        return None
    if isinstance(cell.value, date):
        return cell.value
    match = re.match(r'(\d{4})[/年-](\d{1,2})[/月-](\d{1,2})', cell.text)
    if match:
        return date(*map(int, match.groups()))
    return None


def _as_int(cell: Optional[Cell]) -> Optional[int]:
    if cell is None or cell.value is None:
        return None
    if isinstance(cell.value, float):
        return int(cell.value)
    return int(cell.text) if cell.text.isdigit() else None


@dataclass
class SheetResult:
    """import result for one sheet

    JP:
    シート1枚分の取り込み結果。
    """
    name: str
    aliases: int = 0
    notes: int = 0
    lifetimes: int = 0
    stocks: int = 0
    ended: Optional[date] = None
    mismatches: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class _Row:
    """row accessor by header name"""
    def __init__(self, cells: list[Cell], columns: dict[str, int]):
        self.cells = cells
        self.columns = columns

    def __getitem__(self, key) -> Optional[Cell]:
        index = self.columns.get(key) if isinstance(key, str) else key
        if index is None or index < 0 or index >= len(self.cells):
            return None
        return self.cells[index]

    def text(self, key) -> str:
        """cell text ('' if no cell)"""
        cell = self[key]
        return cell.text if cell else ''


def _find_columns(rows: list[list[Cell]]):
    """find header row, return (header index, {key: column})

    JP:
    見出し行を探して (見出し行番号, {キー: 列番号}) を返す。無ければ None。
    """
    for index, cells in enumerate(rows[:5]):
        texts = [c.text for c in cells]
        if HEADERS['open'] in texts and HEADERS['date'] in texts:
            return index, {key: texts.index(title)
                           for key, title in HEADERS.items()
                           if title in texts}
    return None


def _import_names(db: DrugDb, drug_id: int, name: str, data: list[_Row],
                  result: SheetResult):
    """import aliases and notes from name columns

    JP:
    名称欄から別名とメモを取り込む。
    """
    for index, row in enumerate(data):
        a_text, b_text = row.text('reg_name'), row.text('alias')
        alias_start = _as_date(row['alias_start'])
        if alias_start and b_text:
            if b_text != name or index > 0:
                db.add_alias(drug_id, b_text, alias_start)
                result.aliases += 1
            continue
        if index == 0:
            continue
        note_date = _as_date(row['reg_name'])
        text = b_text if note_date or not a_text else ' '.join(
            t for t in (a_text, b_text) if t)
        if text:
            db.add_note(drug_id, text, note_date)
            result.notes += 1


def _irregular_mark(row: _Row) -> str:
    """irregular mark text left of open date (e.g. '中断→')

    JP:
    名称欄の右から開封日の左までの日付でない文字(「中断→」等)。
    ただし名前が書いてある行の利用開始日欄(「?」等)は名称欄の続き。
    """
    open_col = row.columns['open']
    first = row.columns.get('alias_start', open_col - 2)
    if row.text('alias'):
        first += 1
    marks = [row.text(col) for col in range(first, open_col)
             if _as_date(row[col]) is None]
    return ' '.join(m for m in marks if m)


def _import_lifetimes(db: DrugDb, drug_id: int, data: list[_Row],
                      result: SheetResult) -> Optional[date]:
    """import lifetimes, return last end date

    JP:
    ライフタイムを取り込み、最後の終了日を返す。
    """
    last_end = None
    today = date.today()
    for row in data:
        use_start = _as_date(row['open'])
        if use_start is None:
            continue
        use_end = _as_date(row['end'])
        if use_start > today or (use_end and use_end < use_start):
            result.warnings.append(
                f'ライフタイムの日付が不正: {use_start} 〜 {use_end}')
        mark = _irregular_mark(row)
        db.add_lifetime(drug_id, use_start, use_end, bool(mark),
                        mark or None)
        result.lifetimes += 1
        last_end = use_end
    return last_end


def _import_stock(db: DrugDb, drug_id: int, data: list[_Row],
                  result: SheetResult):
    """import stock records and check balance

    JP:
    在庫記録を取り込み、シートの残高と計算残高を照合する。
    """
    previous = None
    today = date.today()
    for row in data:
        stock_date = _as_date(row['date'])
        if stock_date is None:
            continue
        if stock_date > today:
            result.warnings.append(f'在庫の日付が未来: {stock_date}')
        elif previous and stock_date < previous:
            result.warnings.append(
                f'在庫の日付順が逆: {previous} の次に {stock_date}')
        previous = stock_date
        note = row.text('note') or None
        balance = _as_int(row['balance'])
        records = []
        if row.text('inventory').lower() == 'yes':
            records.append(('inventory', balance or 0))
        records += [(kind, _as_int(row[kind])) for kind in ('in', 'out')]
        for kind, qty in records:
            if qty or kind == 'inventory':
                db.add_stock(drug_id, kind, qty, stock_date, note)
                result.stocks += 1
                note = None
        if balance is not None:
            ours = db.balance(drug_id, as_of=stock_date)
            if ours != balance:
                result.mismatches.append(
                    f'{stock_date}: シート残高 {balance} / 計算残高 {ours}')


def import_sheet(db: DrugDb, name: str,
                 rows: list[list[Cell]]) -> Optional[SheetResult]:
    """import one sheet as one drug

    JP:
    シート1枚を薬1つとして取り込む。見出しが無いシートは None。
    """
    found = _find_columns(rows)
    if found is None:
        return None
    header_index, columns = found
    data = [_Row(cells, columns) for cells in rows[header_index + 1:]]
    result = SheetResult(name)

    start = _as_date(data[0]['alias_start']) if data else None
    drug_id = db.add_drug(name, start_date=start or date.today())
    _import_names(db, drug_id, name, data, result)
    last_end = _import_lifetimes(db, drug_id, data, result)
    _import_stock(db, drug_id, data, result)

    # 開封中が無ければ使用終了とみなす(ライフタイム実績がある薬のみ)
    if result.lifetimes and db.opened(drug_id) is None and last_end:
        db.update_drug(drug_id, end_date=last_end)
        result.ended = last_end
    return result


def import_ods(db: DrugDb, path) -> list[SheetResult]:
    """import all drug sheets

    JP:
    薬のシートを全て取り込む。既に同名の薬があるシートは飛ばす。
    """
    existing = {row['name'] for row in db.list_drugs()}
    results = []
    for name, rows in read_sheets(path).items():
        if name in existing:
            continue
        result = import_sheet(db, name, rows)
        if result is not None:
            results.append(result)
    return results
