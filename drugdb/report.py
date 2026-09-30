# -*- coding: utf-8 -*-
"""summary report for eye doctor visit

JP:
眼科受診直前に提出するサマリーを作ります。
出力は Markdown 形式です。端末表示、 Evernote Web へのコピペ、
MCP 連携でのノート作成のいずれにもそのまま使えます。

来院日(既定は今日)から次回来院日(既定は来院日 + 設定の期間)までに
必要な本数を、根拠(足りない日数・在庫残日数・未開封・通常期間・開封分残日数)と
一緒に出します。
"""
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from .drugdb import DrugDb
from .estimate import SPARE_BOTTLES, Requirement, last_days, to_date

WARNING_TEXT = {
    'stock negative': '在庫数がマイナスです。棚卸ししてください',
}

LEVEL_LABEL = {'warning': '[警告]', 'info': '[info]'}

# 名前の表示。代表目薬名(登録名。例: コソプト。固定)と目薬名(実際に支給
# される薬の名前。例: ドルモロール。変わったら開始日とともに記録)
NAME_MODES = ('both', 'representative', 'actual')
NAME_HEAD = {'both': '代表目薬名(目薬名)', 'representative': '代表目薬名',
             'actual': '目薬名'}

# 次回来院日の既定 = 来院日 + この日数(通常は2ヶ月)。
# DB の meta 'spans' に保存でき、変更できる(get_default_span)。
# 以前は「60,28,14」の形で3つ保存していたので、先頭の値を使う
DEFAULT_SPAN = 60
MAX_SPAN_DAYS = 365
# 期間の単位(次回診察日は月単位・週単位で決まるので単位で指定する)。
# 1ヶ月は30日、1週間は7日として日数に換算する(1本程度の余裕を見て計算するので十分)
SPAN_UNITS = {'ヶ月': 30, '週間': 7, '日': 1}
# 入力で受け付ける単位の書き方
_UNIT_ALIASES = {'ヶ月': 'ヶ月', 'か月': 'ヶ月', 'カ月': 'ヶ月', 'ケ月': 'ヶ月',
                 '箇月': 'ヶ月', '月': 'ヶ月', '週間': '週間', '週': '週間',
                 '日': '日', '': '日'}


def span_to_unit(days: int) -> tuple[int, str]:
    """days to (number, unit)

    JP:
    日数を (数, 単位) にする。30の倍数は「ヶ月」、7の倍数は「週間」、他は「日」。
    例: 60→(2, 'ヶ月')、28→(4, '週間')、10→(10, '日')。
    """
    if days % 30 == 0:
        return days // 30, 'ヶ月'
    if days % 7 == 0:
        return days // 7, '週間'
    return days, '日'


def unit_to_span(number, unit: str) -> int:
    """(number, unit) to days

    JP:
    (数, 単位) を日数にする。1〜MAX_SPAN_DAYS 日。
    """
    if unit not in SPAN_UNITS:
        raise ValueError(f'単位が不正です: {unit}')
    try:
        number = int(number)
    except (TypeError, ValueError) as err:
        raise ValueError(f'期間は数字で指定してください: {number}') from err
    if number < 1:
        raise ValueError('期間は1以上にしてください')
    days = number * SPAN_UNITS[unit]
    if days > MAX_SPAN_DAYS:
        raise ValueError(f'期間は{MAX_SPAN_DAYS}日以内にしてください')
    return days


def parse_span(text) -> int:
    """parse '2ヶ月', '8週間', '60日', '60' to days

    JP:
    期間の文字列を日数にする。「2ヶ月」「2か月」「8週間」「8週」「60日」「60」。
    """
    match = re.fullmatch(r'\s*(\d+)\s*(\S*)\s*', str(text))
    unit = _UNIT_ALIASES.get(match.group(2)) if match else None
    if unit is None:
        raise ValueError(f'期間が不正です(例: 2ヶ月、8週間、60日): {text}')
    return unit_to_span(match.group(1), unit)


def span_label(days: int) -> str:
    """label of span days

    JP:
    期間の表示名。 60→2ヶ月、28→4週間、10→10日。
    """
    number, unit = span_to_unit(days)
    return f'{number}{unit}'


def get_default_span(db: DrugDb) -> int:
    """default days from visit to next visit (db meta or default)

    JP:
    次回来院日の既定(来院日から何日後か)。 DB の設定(meta 'spans' の先頭)、
    無ければ DEFAULT_SPAN。
    """
    value = (db.get_meta('spans') or '').replace('、', ',').split(',')[0]
    try:
        days = int(value)
    except ValueError:
        return DEFAULT_SPAN
    return days if 1 <= days <= MAX_SPAN_DAYS else DEFAULT_SPAN


def set_default_span(db: DrugDb, days: int) -> int:
    """save default days from visit to next visit

    JP:
    次回来院日の既定(来院日から何日後か)を保存する。
    """
    days = int(days)
    if not 1 <= days <= MAX_SPAN_DAYS:
        raise ValueError(f'期間は1〜{MAX_SPAN_DAYS}日にしてください: {days}')
    db.set_meta('spans', str(days))
    return days


BASIS_TEXT = {
    'past years': '過去年値',
    'default': '想定使用日数(default_days)',
    'no data': '実績なし',
}


@dataclass
class ReportLine:
    """one drug line in summary

    JP:
    サマリーの1行(薬1つ分)。
    """
    drug_id: int
    name: str
    current_name: str
    req: Requirement
    last_days: Optional[int] = None  # 直近の使い切り日数


@dataclass
class Report:
    """summary for next visit

    JP:
    次回来院までのサマリー。 today は来院日(在庫・開封中はこの日時点)。
    """
    today: date
    next_visit: date
    span: int
    margin_days: int
    lines: list[ReportLine]
    name_mode: str = 'both'   # NAME_MODES 参照

    title = '目薬 受診前サマリー'

    @property
    def visit_text(self) -> str:
        """visit date text"""
        return f'来院日 {self.today.isoformat()}'

    @property
    def next_visit_text(self) -> str:
        """next visit date text with days after"""
        return f'次回来院日 {self.next_visit.isoformat()}({self.span}日後)'


def make_report(db: DrugDb, today=None, span: Optional[int] = None,
                next_visit=None, margin_days: int = 0,
                name_mode: str = 'both', **kwargs) -> Report:
    """make summary report

    JP:
    サマリーを作る。 today は来院日(省略時今日)。
    次回来院日は next_visit(日付)または span(来院日から何日後か)で指定。
    どちらも無ければ設定の期間(get_default_span)後。
    使用終了した薬は含めない。 name_mode は名前の表示(NAME_MODES)。
    """
    if name_mode not in NAME_MODES:
        raise ValueError(f'name_mode が不正です: {name_mode}')
    today = to_date(today) or date.today()
    if next_visit is not None:
        next_visit = to_date(next_visit)
        span = (next_visit - today).days
    else:
        span = get_default_span(db) if span is None else span
        next_visit = today + timedelta(days=span)
    if span < 1:
        raise ValueError('次回来院日は来院日より後の日付にしてください')
    lines = []
    for drug in db.list_drugs(active_only=True):
        req = db.requirement(drug['drug_id'], span=span, today=today,
                             margin_days=margin_days, **kwargs)
        lines.append(ReportLine(
            drug['drug_id'], drug['name'], db.current_name(drug['drug_id']),
            req, last_days(db.lifetimes(drug['drug_id'], as_of=today))))
    return Report(today, next_visit, span, margin_days, lines, name_mode)


def line_name(line: ReportLine, mode: str = 'both') -> str:
    """drug name for display by name mode

    JP:
    表示する名前。 mode は NAME_MODES のいずれか。
    'both' は「代表目薬名(目薬名)」(同じなら代表目薬名だけ)。
    """
    if mode == 'representative':
        return line.name
    if mode == 'actual':
        return line.current_name
    if line.current_name == line.name:
        return line.name
    return f'{line.name}({line.current_name})'


def opened_text(req: Requirement, remaining_label: str = '推定残り') -> str:
    """opened bottle status text

    JP:
    開封中の状態。例: 「9/10開封 15日経過 推定残り約11日」
    remaining_label で「推定残り」の文言を変えられる。
    """
    if req.opened is None:
        return '開封中なし'
    text = f'{req.opened.month}/{req.opened.day}開封 {req.elapsed}日経過'
    if req.remaining is not None:
        if 'over estimate' in req.info:
            over = req.elapsed - req.normal
            text += f' (推定より{over}日長く使えています)'
        else:
            text += f' {remaining_label}約{req.remaining}日'
    return text


def discard_label(days: int) -> str:
    """discard period label

    JP:
    廃棄期限の表示。医師・目薬の説明に合わせて7の倍数は「4週間」、他は「N日」。
    """
    return f'{days // 7}週間' if days % 7 == 0 else f'{days}日'


def notices(line: ReportLine) -> list[tuple[str, str]]:
    """warning and info texts as (level, text)

    JP:
    警告と情報を (レベル, 文) で返す。レベルは 'warning' か 'info'。
    推定超過(over estimate)は開封中の状態(opened_text)に出すので除く。
    """
    req = line.req
    result = [('warning', WARNING_TEXT.get(w, w)) for w in req.warnings]
    if 'over max_days' in req.info:
        result.append(('info', f'開封から{req.elapsed}日経過。廃棄期限'
                               f'({discard_label(req.max_days)})を過ぎています'))
    return result


def estimate_text(req: Requirement) -> str:
    """normal days per bottle text

    JP:
    通常期間(1本あたりの推定日数)とその根拠。随時使用なら参考値である旨を付ける。
    """
    est = req.estimate
    if est.basis.startswith('recent'):
        basis = f'直近{len(est.samples)}本の平均 {est.samples}'
    else:
        basis = BASIS_TEXT.get(est.basis, est.basis)
    if req.as_needed:
        basis += '・随時使用のため参考値'
    days = '-' if req.normal is None else f'{req.normal}日'
    return f'通常期間 {days} ({basis})'


def _md_cell(value) -> str:
    """escape text for markdown table cell"""
    return str(value).replace('|', '\\|').replace('\n', ' ')


def remaining_text(req: Requirement) -> str:
    """estimated remaining days text for stock table

    JP:
    推定残日数(来院日時点)。推定を超えて使用中なら「超過N日」。推定できなければ空。
    """
    if req.remaining is None:
        return ''
    if 'over estimate' in req.info:
        return f'超過{req.elapsed - req.normal}日'
    return str(req.remaining)


def need_cell(req: Requirement) -> str:
    """required count cell

    JP:
    必要本数(処方をお願いする本数)のセル。処方不要は「0」。
    随時使用は「随時」、推定不能は「相談」。
    """
    if req.as_needed:
        return '随時'
    if req.need is None:
        return '相談'
    return str(req.need)


def basis_cells(req: Requirement) -> list:
    """basis cells: short days, stock days, unopened, normal, opened left

    JP:
    必要本数の根拠のセル [足りない日数, 在庫残日数, 未開封, 通常期間, 開封分残日数]。
    随時使用・推定不能は未開封以外を空欄にする。
    """
    if req.stock_days is None:
        return ['', '', req.stock, '', '']
    return [req.short_days, req.stock_days, req.stock, req.normal,
            req.opened_left]


BASIS_HEADS = ['足りない日数', '在庫残日数', '未開封', '通常期間', '開封分残日数']

# 必要本数と根拠の説明(Markdown とテキスト版で共通)
NEED_NOTES = [
    '必要本数…処方をお願いする本数。足りない日数 ÷ 通常期間 を切り上げ、'
    f'予備{SPARE_BOTTLES}本を足した本数(0未満は0)。0 は処方不要',
    '足りない日数…次回来院日までの日数 − 在庫残日数。マイナスは余る日数',
    '在庫残日数…来院日の時点で残っている目薬の日数'
    '(開封分残日数 + 未開封 × 通常期間)',
    '未開封…来院日の時点で未開封の本数',
    '通常期間…1本を何日で使い切るか(イレギュラーを除く直近3本の平均)',
    '開封分残日数…来院日の時点での、いま使っている1本の残り日数'
    '(通常期間 − (来院日 − 開封日)。使い切っている・開封中なしは0)',
]


def need_table(report: Report) -> list[str]:
    """'次回来院までに必要な本数' table lines (markdown)

    JP:
    「次回来院までに必要な本数」の表。必要本数に続いて根拠の列。
    """
    mode = report.name_mode
    out = ['## 次回来院までに必要な本数', '',
           f"| {NAME_HEAD[mode]} | 必要本数 | {' | '.join(BASIS_HEADS)} |",
           '|---|---:|' + '---:|' * len(BASIS_HEADS)]
    for line in report.lines:
        cells = ' | '.join(str(v) for v in basis_cells(line.req))
        out.append(f'| {_md_cell(line_name(line, mode))}'
                   f' | {need_cell(line.req)} | {cells} |')
    out += [''] + [f'- {text}' for text in NEED_NOTES]
    return out


def stock_table(report: Report) -> list[str]:
    """'目薬在庫' table lines (markdown)

    JP:
    「目薬在庫」の表。随時使用の薬は含めない。
    """
    mode = report.name_mode
    # 既定(both)でもこの表は代表目薬名だけ(ods のノート形式)
    head = NAME_HEAD['representative'] if mode == 'both' else NAME_HEAD[mode]
    out = ['## 目薬在庫', '',
           f'| {head} | 未開封個数 | 開封分開封日 | 経過日数'
           ' | 推定残日数 | 日数 |',
           '|---|---:|---|---:|---:|---:|']
    for line in report.lines:
        req = line.req
        if req.as_needed:
            continue
        opened = f'{req.opened.month}/{req.opened.day}' if req.opened else ''
        days = '' if line.last_days is None else line.last_days
        elapsed = '' if req.elapsed is None else req.elapsed
        # 既定(both)ではユーザーの ods と同じく代表目薬名
        name = line.name if mode == 'both' else line_name(line, mode)
        out.append(f'| {_md_cell(name)} | {req.stock} | {opened}'
                   f' | {elapsed} | {remaining_text(req)} | {days} |')
    out += ['',
            '- 未開封個数…来院日の時点で未開封の個数',
            '- 開封分開封日…現在使用しているのを開封した日',
            '- 経過日数…開封分開封日から来院日までの日数',
            '- 推定残日数…来院日の時点で現在使っている1本の推定残り日数'
            '(通常期間 − 経過日数)',
            '- 日数…直近の使い切り日数(途中廃棄やイレギュラーの場合は空欄)']
    return out


def to_plain_text(report: Report) -> str:
    """plain text summary (for apps that paste as plain text)

    JP:
    テキスト版のサマリー。 Evernote の Android アプリのように、貼り付けると
    書式なしのテキストになるところでも読みやすいよう、記号の少ない1行1薬の形。
    """
    mode = report.name_mode
    out = [report.title, report.visit_text, report.next_visit_text, '',
           '■ 次回来院までに必要な本数']
    for line in report.lines:
        req = line.req
        head = f'{line_name(line, mode)}  必要本数{need_cell(req)}'
        if req.as_needed:
            out.append(f'{head}  未開封{req.stock}')
            continue
        cells = [f'{label}{value}' for label, value
                 in zip(BASIS_HEADS, basis_cells(req)) if value != '']
        out.append('  '.join([head] + cells))
    out += [f'・{text}' for text in NEED_NOTES]
    out += ['', '■ 目薬在庫']
    for line in report.lines:
        req = line.req
        if req.as_needed:
            continue
        parts = [line_name(line, mode), f'未開封{req.stock}']
        if req.opened:
            parts.append(f'開封日{req.opened.month}/{req.opened.day}')
        if remaining_text(req):
            parts.append(f'残日数{remaining_text(req)}')
        if line.last_days is not None:
            parts.append(f'通常日数{line.last_days}')
        out.append('  '.join(parts))
    notes = [f'・{LEVEL_LABEL[level]} {line_name(line, mode)}: {text}'
             for line in report.lines for level, text in notices(line)]
    if notes:
        out += ['', '■ 注意'] + notes
    return '\n'.join(out) + '\n'


def to_markdown(report: Report) -> str:
    """markdown summary

    JP:
    Markdown 形式のサマリー。
    """
    mode = report.name_mode
    out = [f'# {report.title}', '',
           f'- {report.visit_text}', f'- {report.next_visit_text}', '']
    out += need_table(report)
    out += [''] + stock_table(report)
    notes = [f'- {LEVEL_LABEL[level]} {line_name(line, mode)}: {text}'
             for line in report.lines for level, text in notices(line)]
    if notes:
        out += ['', '## 注意', ''] + notes
    out += ['', '## 推定の根拠', '']
    out += [f'- {line_name(line, mode)}: {estimate_text(line.req)}'
            for line in report.lines]
    return '\n'.join(out) + '\n'
