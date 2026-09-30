# -*- coding: utf-8 -*-
"""export summary as prompt + JSON for chat AI

JP:
チャットAI 用の書き出し
=======================

次回来院までに必要な本数と目薬在庫のデータを JSON にし、 Evernote AI への指示
(プロンプト)と一緒にテキストにします。スマホ版はこれをクリップボードに
コピーし、ユーザーがチャットAI(Android の Evernote アプリの Evernote AI など)に貼り付けます。

プロンプトは試行錯誤しながら直すので AI_PROMPT にまとめてあります。
"""
import json

from .estimate import SPARE_BOTTLES
from .report import Report, notices, remaining_text

# Evernote AI への指示。 {json} に JSON が入る
AI_PROMPT = """\
以下の JSON は、目薬の在庫と眼科受診時に処方をお願いする本数のデータです。
このデータから、次の2つの表を含むノート本文を日本語で作ってください。

1. 「次回来院までに必要な本数」の表
   列: 代表目薬名 / 必要本数 / 足りない日数 / 在庫残日数 / 未開封 / 通常期間 / 開封分残日数
   必要本数のセルは「必要本数」の値をそのまま書く(随時使用の目薬は「随時」、
   推定できない目薬は「相談」)。
2. 「目薬在庫」の表(随時使用の目薬は除く)
   列: 代表目薬名 / 未開封 / 開封日 / 推定残日数 / 通常日数

守ること:
- 数値・日付・目薬名は JSON のとおりに書き、計算し直したり丸めたりしない。
- JSON に無い目薬や情報を付け加えない。
- 表の前に見出し「目薬 受診前サマリー」と、来院日・次回来院日({visit} / {next})を付ける。
- 最後に「注意」の配列があれば箇条書きで載せる。

```json
{json}
```
"""


def remaining_value(req):
    """remaining days as number, or '超過N日' text, or None

    JP:
    推定残日数。数値。推定を超えて使用中なら「超過N日」の文字列。
    """
    if req.remaining is None:
        return None
    if 'over estimate' in req.info:
        return remaining_text(req)
    return req.remaining


def to_ai_data(report: Report) -> dict:
    """summary data for AI (JSON serializable)

    JP:
    Evernote AI に渡すデータ。キーは日本語(表の列名と同じ言葉)。
    """
    drugs = []
    for line in report.lines:
        req = line.req
        if req.as_needed:
            need = '随時'
        elif req.need is None:
            need = '相談'
        else:
            need = req.need
        item = {
            '代表目薬名': line.name,
            '目薬名': line.current_name,
            '必要本数': need,
            '足りない日数': req.short_days,
            '在庫残日数': req.stock_days,
            '未開封': req.stock,
            '通常期間': req.normal,
            '開封分残日数': req.opened_left,
            '随時使用': req.as_needed,
            '開封日': req.opened.isoformat() if req.opened else None,
            '経過日数': req.elapsed,
            '推定残日数': remaining_value(req),
            '通常日数': line.last_days,
        }
        drugs.append(item)
    notes = [f'{line.name}: {text}' for line in report.lines
             for _, text in notices(line)]
    return {
        '来院日': report.today.isoformat(),
        '次回来院日': report.next_visit.isoformat(),
        '次回来院日まで(日)': report.span,
        '予備本数': SPARE_BOTTLES,
        '目薬': drugs,
        '注意': notes,
    }


def to_ai_prompt(report: Report, prompt: str = AI_PROMPT) -> str:
    """prompt text with JSON for Evernote AI

    JP:
    Evernote AI に貼り付けるテキスト(指示 + JSON)。
    """
    data = json.dumps(to_ai_data(report), ensure_ascii=False, indent=1)
    return prompt.replace('{visit}', report.today.isoformat()) \
        .replace('{next}', report.next_visit.isoformat()) \
        .replace('{json}', data)
