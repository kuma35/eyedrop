# -*- coding: utf-8 -*-
"""export summary as prompt + JSON for Evernote AI

JP:
Evernote AI 用の書き出し
========================

来院時必要本数と目薬在庫のデータを JSON にし、 Evernote AI への指示
(プロンプト)と一緒にテキストにします。スマホ版はこれをクリップボードに
コピーし、ユーザーが Android の Evernote アプリの Evernote AI に貼り付けます。

プロンプトは試行錯誤しながら直すので AI_PROMPT にまとめてあります。
"""
import json

from .report import (MAX_PRESCRIPTION, SPAN_PATTERNS, SPARE_BOTTLES, Report,
                     notices, remaining_text)

# Evernote AI への指示。 {json} に JSON が入る
AI_PROMPT = """\
以下の JSON は、目薬の在庫と眼科受診時に処方をお願いする本数のデータです。
このデータから、次の2つの表を含むノート本文を日本語で作ってください。

1. 「来院時必要本数」の表
   列: 代表目薬名 / 未開封 / 2ヶ月(通常) / 1ヶ月(4週間) / 2週間
   各期間のセルには「処方依頼本数」が1以上なら「必要N」、0なら空欄、
   随時使用の目薬は「随時」、推定できない目薬は「相談」と書く。
2. 「目薬在庫」の表(随時使用の目薬は除く)
   列: 代表目薬名 / 未開封 / 開封日 / 推定残日数 / 通常日数

守ること:
- 数値・日付・目薬名は JSON のとおりに書き、計算し直したり丸めたりしない。
- JSON に無い目薬や情報を付け加えない。
- 表の前に見出し「目薬 受診前サマリー {date}」を付ける。
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
    return round(req.remaining)


def to_ai_data(report: Report) -> dict:
    """summary data for AI (JSON serializable)

    JP:
    Evernote AI に渡すデータ。キーは日本語(表の列名と同じ言葉)。
    """
    labels = [label for label, _ in SPAN_PATTERNS]
    drugs = []
    for line in report.lines:
        req = line.req
        item = {
            '代表目薬名': line.name,
            '目薬名': line.current_name,
            '未開封': req.stock,
            '随時使用': req.as_needed,
            '開封日': req.opened.isoformat() if req.opened else None,
            '経過日数': req.elapsed,
            '推定残日数': remaining_value(req),
            '通常日数': line.last_days,
            '1本あたり推定日数': None if req.estimate.days is None
            else round(req.estimate.days),
            '処方依頼本数': {},
        }
        for label, pattern in zip(labels, line.patterns):
            if pattern.as_needed:
                value = '随時'
            elif pattern.need is None:
                value = '相談'
            else:
                value = pattern.request
            item['処方依頼本数'][label] = value
            if pattern.shortage:
                item.setdefault('不足本数', {})[label] = pattern.shortage
        drugs.append(item)
    notes = [f'{line.name}: {text}' for line in report.lines
             for _, text in notices(line)]
    return {
        '基準日': report.today.isoformat(),
        '次回受診予定': report.next_visit.isoformat(),
        '処方のきまり': {
            '1回の処方の上限本数': MAX_PRESCRIPTION,
            '予備本数': SPARE_BOTTLES,
        },
        '目薬': drugs,
        '注意': notes,
    }


def to_ai_prompt(report: Report, prompt: str = AI_PROMPT) -> str:
    """prompt text with JSON for Evernote AI

    JP:
    Evernote AI に貼り付けるテキスト(指示 + JSON)。
    """
    data = json.dumps(to_ai_data(report), ensure_ascii=False, indent=1)
    return prompt.replace('{date}', report.today.isoformat()) \
        .replace('{json}', data)
