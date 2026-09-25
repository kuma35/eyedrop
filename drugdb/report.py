# -*- coding: utf-8 -*-
"""summary report for eye doctor visit

JP:
眼科受診直前に提出するサマリーを作ります。
テキスト(端末表示・コピー用)と、 Evernote に取り込める ENEX 形式を
出力できます。

ENEX は Evernote の「ファイル > 読み込む」(Import)で取り込めます。
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import escape
from typing import Optional

from .drugdb import DrugDb
from .estimate import Requirement, to_date

WARNING_TEXT = {
    'stock negative': '在庫数がマイナスです。棚卸ししてください',
}

LEVEL_LABEL = {'warning': '[警告]', 'info': '[info]'}


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
        span = 60 if span is None else span
        next_visit = today + timedelta(days=span)
    lines = []
    for drug in db.list_drugs(active_only=True):
        req = db.requirement(drug['drug_id'], span=span, today=today,
                             margin_days=margin_days, **kwargs)
        lines.append(ReportLine(drug['drug_id'], drug['name'],
                                db.current_name(drug['drug_id']), req))
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
    result = [('warning', WARNING_TEXT.get(w, w)) for w in req.warnings]
    if 'over max_days' in req.info:
        result.append(('info', f'開封から{req.elapsed}日経過。推奨使用期限の'
                               f'{req.max_days}日を過ぎています(廃棄推奨)'))
    return result


def estimate_text(req: Requirement) -> str:
    """estimated days per bottle text

    JP:
    1本あたりの推定日数。随時使用なら参考値である旨を付ける。
    """
    basis = req.estimate.basis + ('・随時使用のため参考値' if req.as_needed
                                  else '')
    return f'1本あたり推定 {_fmt_days(req.estimate.days)}日 ({basis})'


def to_text(report: Report) -> str:
    """plain text summary

    JP:
    テキスト形式のサマリー。
    """
    out = [report.title,
           f'次回受診予定: {report.next_visit.isoformat()}'
           f' ({report.span}日後'
           + (f' + 余裕{report.margin_days}日' if report.margin_days else '')
           + ')',
           '',
           '■ お願い']
    out += [f'・{request_sentence(line)}' for line in report.lines]
    out += ['', '■ 詳細']
    for line in report.lines:
        req = line.req
        out.append(f'・{_display_name(line)}')
        out.append(f'    未開封在庫 {req.stock}本 / {opened_text(req)}')
        out.append(f'    {estimate_text(req)}')
        out += [f'    {LEVEL_LABEL[level]} {text}'
                for level, text in notices(line)]
    return '\n'.join(out) + '\n'


def to_enml(report: Report) -> str:
    """ENML (Evernote note content)

    JP:
    Evernote のノート本文(ENML)。
    """
    def cell(text, tag='td'):
        return (f'<{tag} style="border:1px solid #888;padding:4px">'
                f'{escape(str(text))}</{tag}>')

    head = ''.join(cell(h, 'th') for h in (
        '薬', '未開封在庫', '開封中', '推定日数/本', '必要本数', '依頼数'))
    rows = []
    for line in report.lines:
        req = line.req
        rows.append('<tr>' + ''.join(cell(v) for v in (
            _display_name(line), req.stock, opened_text(req),
            _fmt_days(req.estimate.days) + ('(参考)' if req.as_needed
                                            else ''),
            '-' if req.need is None else req.need,
            '-' if req.request is None else req.request)) + '</tr>')
    sentences = ''.join(f'<li>{escape(request_sentence(line))}</li>'
                        for line in report.lines)
    warns = ''.join(
        f'<li>{LEVEL_LABEL[level]} {escape(_display_name(line))}:'
        f' {escape(text)}</li>'
        for line in report.lines for level, text in notices(line))
    body = (
        f'<div>次回受診予定: {report.next_visit.isoformat()}'
        f' ({report.span}日後)</div>'
        f'<h3>お願い</h3><ul>{sentences}</ul>'
        f'<h3>詳細</h3>'
        f'<table style="border-collapse:collapse">'
        f'<tr>{head}</tr>{"".join(rows)}</table>'
        + (f'<h3>注意</h3><ul>{warns}</ul>' if warns else ''))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="no"?>'
            '<!DOCTYPE en-note SYSTEM '
            '"http://xml.evernote.com/pub/enml2.dtd">'
            f'<en-note>{body}</en-note>')


def to_enex(report: Report, tags: tuple[str, ...] = ('eyedrop',),
            now: Optional[datetime] = None) -> str:
    """ENEX (Evernote export format) containing one note

    JP:
    ノート1つを含む ENEX(Evernote のインポート形式)。
    """
    now = now or datetime.now(timezone.utc)
    stamp = now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    tag_xml = ''.join(f'<tag>{escape(t)}</tag>' for t in tags)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE en-export SYSTEM '
        '"http://xml.evernote.com/pub/evernote-export4.dtd">\n'
        f'<en-export export-date="{stamp}" application="eyedrop"'
        ' version="1.0">\n'
        f'<note><title>{escape(report.title)}</title>'
        f'<content><![CDATA[{to_enml(report)}]]></content>'
        f'<created>{stamp}</created><updated>{stamp}</updated>'
        f'{tag_xml}</note>\n'
        '</en-export>\n')
