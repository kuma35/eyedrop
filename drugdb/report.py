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

# 来院時必要本数申告の期間パターン (表示名, 日数)。毎回すべて推定する。
# 通常は2ヶ月。病状により2週間と4週間(1ヶ月)
SPAN_PATTERNS = (
    ('2週間', 14),
    ('4週間(1ヶ月)', 28),
    ('2ヶ月(通常)', 60),
)
DEFAULT_SPAN = 60

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

    @property
    def title(self) -> str:
        """note title"""
        return f'目薬 受診前サマリー {self.today.isoformat()}'


def make_report(db: DrugDb, today=None, span: Optional[int] = None,
                next_visit=None, margin_days: int = 0,
                **kwargs) -> Report:
    """make summary report

    JP:
    サマリーを作る。次回受診日は span(日数)または next_visit(日付)で指定。
    使用終了した薬は含めない。
    """
    today = to_date(today) or date.today()
    if next_visit is not None:
        next_visit = to_date(next_visit)
        span = (next_visit - today).days
    else:
        span = DEFAULT_SPAN if span is None else span
        next_visit = today + timedelta(days=span)
    lines = []
    for drug in db.list_drugs(active_only=True):
        req = db.requirement(drug['drug_id'], span=span, today=today,
                             margin_days=margin_days, **kwargs)
        patterns = [db.requirement(drug['drug_id'], span=days, today=today,
                                   margin_days=margin_days, **kwargs)
                    for _, days in SPAN_PATTERNS]
        lines.append(ReportLine(
            drug['drug_id'], drug['name'], db.current_name(drug['drug_id']),
            req, last_days(db.lifetimes(drug['drug_id'], as_of=today)),
            patterns))
    return Report(today, next_visit, span, margin_days, lines)


def _fmt_days(value) -> str:
    return '-' if value is None else f'{value:.0f}'


def _display_name(line: ReportLine) -> str:
    if line.current_name == line.name:
        return line.name
    return f'{line.name}({line.current_name})'


def request_sentence(line: ReportLine) -> str:
    """sentence for the doctor

    JP:
    先生に伝える文。
    例: 「コソプト: 必要3本・在庫1本なので 2本 ください」
    """
    req = line.req
    name = _display_name(line)
    if req.as_needed:
        text = f'{name}: 随時使用・在庫{req.stock}本'
        if req.estimate.days is not None:
            text += f' (参考: 1本約{req.estimate.days:.0f}日)'
        return text
    if req.need is None:
        return f'{name}: 在庫{req.stock}本(使用実績なし。必要数は相談)'
    if req.shortage:
        return (f'{name}: 必要{req.need}本・在庫{req.stock}本なので'
                f' {req.request}本 ください(処方上限{MAX_PRESCRIPTION}本。'
                f'{req.shortage}本不足)')
    if req.request:
        return (f'{name}: 必要{req.need}本・在庫{req.stock}本なので'
                f' {req.request}本 ください')
    return f'{name}: 必要{req.need}本・在庫{req.stock}本 (処方不要)'


def opened_text(req: Requirement) -> str:
    """opened bottle status text

    JP:
    開封中の状態。例: 「9/10開封 15日経過 残り約11日」
    """
    if req.opened is None:
        return '開封中なし'
    text = f'{req.opened.month}/{req.opened.day}開封 {req.elapsed}日経過'
    if req.remaining is not None:
        if 'over estimate' in req.info:
            over = req.elapsed - req.estimate.days
            text += f' (推定より{over:.0f}日長く使えています)'
        else:
            text += f' 残り約{req.remaining:.0f}日'
    return text


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
        result.append(('info', f'開封から{req.elapsed}日経過。推奨使用期限の'
                               f'{req.max_days}日を過ぎています(廃棄推奨)'))
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
    """'来院時必要本数' table lines (markdown)

    JP:
    「来院時必要本数」の表。期間パターンごとの依頼数(必要本数)。
    """
    heads = ' | '.join(f'{label}' for label, _ in SPAN_PATTERNS)
    out = ['## 来院時必要本数', '',
           f'| 目薬名 | 未開封 | {heads} |',
           '|---|---:|' + '---:|' * len(SPAN_PATTERNS)]
    for line in report.lines:
        cells = ' | '.join(pattern_cell(r) for r in line.patterns)
        out.append(f'| {_md_cell(_display_name(line))} | {line.req.stock}'
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
    out = ['## 目薬在庫', '',
           '| 目薬名 | 未開封個数 | 開封分開封日 | 経過日数 | 推定残日数 | 日数 |',
           '|---|---:|---|---:|---:|---:|']
    for line in report.lines:
        req = line.req
        if req.as_needed:
            continue
        opened = f'{req.opened.month}/{req.opened.day}' if req.opened else ''
        days = '' if line.last_days is None else line.last_days
        elapsed = '' if req.elapsed is None else req.elapsed
        out.append(f'| {_md_cell(line.name)} | {req.stock} | {opened}'
                   f' | {elapsed} | {remaining_text(req)} | {days} |')
    out += ['',
            '- 未開封個数…現時点で未開封の個数',
            '- 開封分開封日…現在使用しているのを開封した日',
            '- 経過日数…開封分開封日から今日までの日数',
            '- 推定残日数…イレギュラーでない過去の使い切り日数(直近の平均)から'
            '推定した残り日数',
            '- 日数…直近の使い切り日数(途中廃棄やイレギュラーの場合は空欄)']
    return out


def to_markdown(report: Report) -> str:
    """markdown summary

    JP:
    Markdown 形式のサマリー。
    依頼がある行(「◯本 ください」)は太字にする。
    """
    span = f'{report.span}日後'
    if report.margin_days:
        span += f' + 余裕{report.margin_days}日'
    out = [f'# {report.title}', '',
           f'次回受診予定: **{report.next_visit.isoformat()}** ({span})', '']
    out += pattern_table(report)
    out += [''] + stock_table(report)
    out += ['', '## お願い', '']
    for line in report.lines:
        sentence = request_sentence(line)
        out.append(f'- **{sentence}**' if line.req.request else
                   f'- {sentence}')
    out += ['', '## 詳細', '',
            '| 薬 | 未開封在庫 | 開封中 | 推定日数/本 | 必要本数 | 依頼数 |',
            '|---|---:|---|---:|---:|---:|']
    for line in report.lines:
        req = line.req
        days = _fmt_days(req.estimate.days) + ('(参考)' if req.as_needed
                                               else '')
        out.append('| ' + ' | '.join(_md_cell(v) for v in (
            _display_name(line), req.stock, opened_text(req), days,
            '-' if req.need is None else req.need,
            '-' if req.request is None else req.request)) + ' |')
    notes = [f'- {LEVEL_LABEL[level]} {_display_name(line)}: {text}'
             for line in report.lines for level, text in notices(line)]
    if notes:
        out += ['', '## 注意', ''] + notes
    out += ['', '## 推定の根拠', '']
    out += [f'- {_display_name(line)}: {estimate_text(line.req)}'
            for line in report.lines]
    return '\n'.join(out) + '\n'
