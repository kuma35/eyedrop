# -*- coding: utf-8 -*-
"""summary report for eye doctor visit

JP:
眼科受診直前に提出するサマリーを作ります。
出力は Markdown 形式です。端末表示、 Evernote Web へのコピペ、
MCP 連携でのノート作成のいずれにもそのまま使えます。
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from .drugdb import DrugDb
from .estimate import (MAX_PRESCRIPTION, SPARE_BOTTLES, Requirement,
                       last_days, to_date)

WARNING_TEXT = {
    'stock negative': '在庫数がマイナスです。棚卸ししてください',
}

LEVEL_LABEL = {'warning': '[警告]', 'info': '[info]'}

# 名前の表示。代表目薬名(登録名。例: コソプト。固定)と目薬名(実際に支給
# される薬の名前。例: ドルモロール。変わったら開始日とともに記録)
NAME_MODES = ('both', 'representative', 'actual')
NAME_HEAD = {'both': '代表目薬名(目薬名)', 'representative': '代表目薬名',
             'actual': '目薬名'}

# 次回来院までに必要な本数申告の期間(日数)。毎回すべて推定する。
# 通常は2ヶ月。病状により2週間と1ヶ月(4週間)。
# 表の列の順(通常を未開封のすぐ隣にするため先頭が通常)。
# DB の meta 'spans' に「60,28,14」の形で保存でき、変更できる(get_spans)
DEFAULT_SPANS = (60, 28, 14)
DEFAULT_SPAN = DEFAULT_SPANS[0]
MAX_SPAN_DAYS = 365
# 期間の単位(次回診察日は月単位・週単位で決まるので単位で指定する)。
# 1ヶ月は30日、1週間は7日として日数に換算する(1本程度の余裕を見て計算するので十分)
SPAN_UNITS = {'ヶ月': 30, '週間': 7, '日': 1}


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
    (数, 単位) を日数にする。
    """
    if unit not in SPAN_UNITS:
        raise ValueError(f'単位が不正です: {unit}')
    try:
        number = int(number)
    except (TypeError, ValueError) as err:
        raise ValueError(f'期間は数字で指定してください: {number}') from err
    if number < 1:
        raise ValueError('期間は1以上にしてください')
    return number * SPAN_UNITS[unit]


def snap_span(days: float) -> int:
    """round days to a natural unit (months or weeks)

    JP:
    日数をきりのよい単位に丸める。1ヶ月前後以上は月、1週以上は週、それ未満は日。
    例: 30→30(1ヶ月)、15→14(2週)、45→42(6週)。
    """
    days = max(1, round(days))
    months = round(days / 30)
    if months >= 1 and abs(months * 30 - days) <= 3:
        return months * 30
    if days >= 7:
        return round(days / 7) * 7
    return days


def span_label(days: int, style: str = 'full', normal: bool = False) -> str:
    """label of span days

    JP:
    期間の表示名。 60→2ヶ月、28→1ヶ月(4週間)、14→2週間、それ以外は N日。
    style: 'full'(Markdown 等)、'short'(アプリの2段見出し)、'plain'(テキスト版)。
    normal なら通常の期間として「(通常)」を付ける(full のみ)。
    """
    if days == 28:
        label = {'short': '1ヶ月\n(4週間)', 'plain': '1ヶ月'}.get(
            style, '1ヶ月(4週間)')
    elif days % 30 == 0:
        label = f'{days // 30}ヶ月'
    elif days % 7 == 0:
        label = f'{days // 7}週間'
    else:
        label = f'{days}日'
    if normal and style == 'full':
        label += '(通常)'
    return label


def parse_spans(text) -> tuple[int, ...]:
    """parse '60,28,14' to (60, 28, 14)

    JP:
    期間の文字列を日数のタプルにする。1〜365日の整数、重複なし。
    """
    try:
        spans = tuple(int(v) for v in str(text).replace('、', ',').split(',')
                      if v.strip())
    except ValueError as err:
        raise ValueError(f'期間は日数(数字)で指定してください: {text}') \
            from err
    if not spans:
        raise ValueError('期間を指定してください')
    for days in spans:
        if not 1 <= days <= MAX_SPAN_DAYS:
            raise ValueError(f'期間は1〜{MAX_SPAN_DAYS}日にしてください: {days}')
    if len(set(spans)) != len(spans):
        raise ValueError('同じ期間が重なっています')
    return spans


def get_spans(db: DrugDb) -> tuple[int, ...]:
    """spans for required count (from db meta or default)

    JP:
    次回来院までに必要な本数の期間。 DB の設定(meta 'spans')、無ければ DEFAULT_SPANS。
    """
    value = db.get_meta('spans')
    if not value:
        return DEFAULT_SPANS
    try:
        return parse_spans(value)
    except ValueError:
        return DEFAULT_SPANS


def set_spans(db: DrugDb, spans) -> tuple[int, ...]:
    """save spans (first is the usual one)

    JP:
    次回来院までに必要な本数の期間を保存する。先頭が通常の期間。
    """
    spans = parse_spans(','.join(str(d) for d in spans))
    db.set_meta('spans', ','.join(str(d) for d in spans))
    return spans


def default_sub_spans(normal: int) -> tuple[int, int, int]:
    """normal span and its half and quarter

    JP:
    通常の期間から、その半分と更に半分を既定として作る。単位に合わせて丸める。
    例: 60(2ヶ月)→(60, 30, 14)=2ヶ月・1ヶ月・2週。
    """
    return normal, snap_span(normal / 2), snap_span(normal / 4)


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
    # 期間パターンごとの必要数 (SPAN_PATTERNS と同じ順)
    patterns: list[Requirement] = field(default_factory=list)


@dataclass
class Report:
    """summary for next visit

    JP:
    次回受診までのサマリー。
    """
    today: date
    next_visit: date
    span: int
    margin_days: int
    lines: list[ReportLine]
    name_mode: str = 'both'   # NAME_MODES 参照
    spans: tuple[int, ...] = DEFAULT_SPANS   # 次回来院までに必要な本数の期間

    def span_labels(self, style: str = 'full') -> list[str]:
        """labels of spans (first is usual)"""
        return [span_label(days, style, normal=index == 0)
                for index, days in enumerate(self.spans)]

    @property
    def title(self) -> str:
        """note title"""
        return f'目薬 受診前サマリー {self.today.isoformat()}'


def make_report(db: DrugDb, today=None, span: Optional[int] = None,
                next_visit=None, margin_days: int = 0,
                name_mode: str = 'both', spans=None, **kwargs) -> Report:
    """make summary report

    JP:
    サマリーを作る。次回受診日は span(日数)または next_visit(日付)で指定。
    使用終了した薬は含めない。 name_mode は名前の表示(NAME_MODES)。
    """
    if name_mode not in NAME_MODES:
        raise ValueError(f'name_mode が不正です: {name_mode}')
    spans = tuple(spans) if spans else get_spans(db)
    today = to_date(today) or date.today()
    if next_visit is not None:
        next_visit = to_date(next_visit)
        span = (next_visit - today).days
    else:
        span = spans[0] if span is None else span
        next_visit = today + timedelta(days=span)
    lines = []
    for drug in db.list_drugs(active_only=True):
        req = db.requirement(drug['drug_id'], span=span, today=today,
                             margin_days=margin_days, **kwargs)
        patterns = [db.requirement(drug['drug_id'], span=days, today=today,
                                   margin_days=margin_days, **kwargs)
                    for days in spans]
        lines.append(ReportLine(
            drug['drug_id'], drug['name'], db.current_name(drug['drug_id']),
            req, last_days(db.lifetimes(drug['drug_id'], as_of=today)),
            patterns))
    return Report(today, next_visit, span, margin_days, lines, name_mode,
                  spans)


def _fmt_days(value) -> str:
    return '-' if value is None else f'{value:.0f}'


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
            over = req.elapsed - req.estimate.days
            text += f' (推定より{over:.0f}日長く使えています)'
        else:
            text += f' {remaining_label}約{req.remaining:.0f}日'
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
    result = [('warning', WARNING_TEXT.get(w, w)) for w in req.warnings
              if w != 'over prescription limit']
    if req.shortage:
        result.append(('warning', f'処方上限{MAX_PRESCRIPTION}本では'
                                  f'次回受診までに{req.shortage}本不足します'))
    if 'over max_days' in req.info:
        result.append(('info', f'開封から{req.elapsed}日経過。廃棄期限'
                               f'({discard_label(req.max_days)})を過ぎています'))
    return result


def estimate_text(req: Requirement) -> str:
    """estimated days per bottle text

    JP:
    1本あたりの推定日数。随時使用なら参考値である旨を付ける。
    """
    est = req.estimate
    if est.basis.startswith('recent'):
        basis = f'直近{len(est.samples)}本の平均 {est.samples}'
    else:
        basis = BASIS_TEXT.get(est.basis, est.basis)
    if req.as_needed:
        basis += '・随時使用のため参考値'
    return f'1本あたり推定 {_fmt_days(req.estimate.days)}日 ({basis})'


def _md_cell(value) -> str:
    """escape text for markdown table cell"""
    return str(value).replace('|', '\\|').replace('\n', ' ')


def remaining_text(req: Requirement) -> str:
    """estimated remaining days text for stock table

    JP:
    推定残日数。推定を超えて使用中なら「超過N日」。推定できなければ空。
    """
    if req.remaining is None:
        return ''
    if 'over estimate' in req.info:
        return f'超過{req.elapsed - req.estimate.days:.0f}日'
    return f'{req.remaining:.0f}'


def pattern_cell(req: Requirement) -> str:
    """request cell for pattern table

    JP:
    申告表のセル。処方が必要なら「必要2」(2 は依頼数)、不要なら空欄。
    随時使用は「随時」、推定不能は「相談」。
    """
    if req.as_needed:
        return '随時'
    if req.need is None:
        return '相談'
    if req.shortage:
        return f'必要{req.request}(不足{req.shortage})'
    return f'必要{req.request}' if req.request else ''


def pattern_table(report: Report) -> list[str]:
    """'次回来院までに必要な本数' table lines (markdown)

    JP:
    「次回来院までに必要な本数」の表。期間パターンごとの依頼数(必要本数)。
    """
    heads = ' | '.join(report.span_labels())
    mode = report.name_mode
    out = ['## 次回来院までに必要な本数', '',
           f'| {NAME_HEAD[mode]} | 未開封 | {heads} |',
           '|---|---:|' + '---:|' * len(report.spans)]
    for line in report.lines:
        cells = ' | '.join(pattern_cell(r) for r in line.patterns)
        out.append(f'| {_md_cell(line_name(line, mode))} | {line.req.stock}'
                   f' | {cells} |')
    out += ['',
            f'- 必要N…処方をお願いする本数(期間中に使う本数 + 予備{SPARE_BOTTLES}'
            ' − 未開封)。空欄は処方不要',
            f'- 1回の処方は最大{MAX_PRESCRIPTION}本(健康保険の制限)。'
            '超える分は「不足N」',
            '- 期間中に使う本数は開封中の推定残日数を差し引いて計算']
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
            '- 未開封個数…現時点で未開封の個数',
            '- 開封分開封日…現在使用しているのを開封した日',
            '- 経過日数…開封分開封日から今日までの日数',
            '- 推定残日数…イレギュラーでない過去の使い切り日数(直近の平均)から'
            '推定した残り日数',
            '- 日数…直近の使い切り日数(途中廃棄やイレギュラーの場合は空欄)']
    return out


def to_plain_text(report: Report) -> str:
    """plain text summary (for apps that paste as plain text)

    JP:
    テキスト版のサマリー。 Evernote の Android アプリのように、貼り付けると
    書式なしのテキストになるところでも読みやすいよう、記号の少ない1行1薬の形。
    処方不要は「不要」。
    """
    mode = report.name_mode
    labels = report.span_labels('plain')
    out = [report.title, '',
           f"■ 次回来院までに必要な本数({' / '.join(labels)})"]
    for line in report.lines:
        head = f'{line_name(line, mode)}  未開封{line.req.stock}'
        if line.req.as_needed:
            out.append(f'{head}  随時使用')
            continue
        cells = [f'{label}:{pattern_cell(req) or "不要"}'
                 for label, req in zip(labels, line.patterns)]
        out.append('  '.join([head] + cells))
    out += [f'(必要N…処方をお願いする本数。予備{SPARE_BOTTLES}本込み・'
            f'1回の処方は最大{MAX_PRESCRIPTION}本)',
            '',
            '■ 目薬在庫']
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
    out = [f'# {report.title}', '']
    out += pattern_table(report)
    out += [''] + stock_table(report)
    notes = [f'- {LEVEL_LABEL[level]} {line_name(line, mode)}: {text}'
             for line in report.lines for level, text in notices(line)]
    if notes:
        out += ['', '## 注意', ''] + notes
    out += ['', '## 推定の根拠', '']
    out += [f'- {line_name(line, mode)}: {estimate_text(line.req)}'
            for line in report.lines]
    return '\n'.join(out) + '\n'
