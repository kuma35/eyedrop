# -*- coding: utf-8 -*-
"""lifetime estimation and required count calculation

JP:
DB に依存しない計算ロジック。

推定使用日数
------------

直近の実績の方が平均より適切なことが多いので、
イレギュラーでない終了済みライフタイムのうち直近 window 件の平均を使う。
ただし極端に短い実績(中央値 * short_ratio 未満)は除外する。
直近実績が無ければ年次更新で退避した過去年値(lifetime_summary)、
それも無ければ drug.default_days を使う。
開封後の廃棄期限(max_days)は推定の上限にはしない(うっかり使い続ける
こともあるので実績どおりに推定する)。超過は info として知らせるだけ。

必要本数
--------

推定使用日数は整数日に四捨五入して通常期間とし、以下すべてこの値で計算する
(サマリーに出す根拠の数字でそのまま検算できるように)。

来院日の時点で

- 開封分残日数 = 通常期間 - (来院日 - 開封日)
  (既に通常期間を超えて使っている1本は 0。開封中が無ければ 0)
- 在庫残日数 = 開封分残日数 + 未開封本数 * 通常期間
- 足りない日数 = 次回来院日までの日数(span) - 在庫残日数
- 必要本数 = 足りない日数 / 通常期間 を切り上げ + 予備(0未満は0)

必要本数は処方をお願いする本数で、予備 SPARE_BOTTLES(1本程度の余裕)を含める。
1回の処方の上限本数は条件が不明なので設けない(医師に確認できたら改めて実装)。

随時使用(as_needed)の薬は毎日使うものではないので必要本数を計算しない。
推定使用日数は参考値として表示するだけ。

warnings は対処が必要な警告、 info は知らせるだけの情報。
"""
import math
from dataclasses import dataclass, field
from datetime import date
from statistics import median
from typing import Iterable, Optional, Sequence

DEFAULT_WINDOW = 3
# 必要本数に加える予備(余裕)の本数
SPARE_BOTTLES = 1
DEFAULT_SHORT_RATIO = 0.7


def to_date(value) -> Optional[date]:
    """convert ISO string to date (None passes through)

    JP:
    'YYYY-MM-DD' 文字列を date に変換。 date/None はそのまま返す。
    """
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


def days_between(start, end) -> int:
    """days from start to end

    JP:
    開始日から終了日までの日数(終了日 - 開始日)。
    """
    return (to_date(end) - to_date(start)).days


def regular_rows(lifetimes: Iterable, short_ratio: float =
                 DEFAULT_SHORT_RATIO) -> list[tuple[object, int]]:
    """valid lifetime rows with days, in given order

    JP:
    イレギュラーでなく終了済みのライフタイムを (行, 日数) で返す。
    中央値 * short_ratio 未満の極端に短いものは除外する。
    lifetimes の要素は use_start, use_end, irregular を持つ mapping。
    """
    pairs = [(row, days_between(row['use_start'], row['use_end']))
             for row in lifetimes
             if row['use_end'] is not None and not row['irregular']]
    pairs = [(row, d) for row, d in pairs if d > 0]
    if not pairs:
        return []
    threshold = median(d for _, d in pairs) * short_ratio
    return [(row, d) for row, d in pairs if d >= threshold]


def regular_days(lifetimes: Iterable, short_ratio: float =
                 DEFAULT_SHORT_RATIO) -> list[int]:
    """list of valid lifetime days, in given order (oldest first)

    JP:
    妥当なライフタイムの日数(regular_rows 参照)。
    """
    return [d for _, d in regular_rows(lifetimes, short_ratio)]


def last_days(lifetimes: Sequence) -> Optional[int]:
    """days of the most recently finished lifetime

    JP:
    直近の使い切り日数。 lifetimes は開封日の古い順。
    終了済みのうち一番新しいものがイレギュラー(途中廃棄等)なら None。
    """
    finished = [row for row in lifetimes if row['use_end'] is not None]
    if not finished or finished[-1]['irregular']:
        return None
    return days_between(finished[-1]['use_start'], finished[-1]['use_end'])


def summarize(days: Sequence[int]) -> Optional[dict]:
    """summary of days (count, avg, min, max)

    JP:
    日数列の要約。空なら None。
    """
    if not days:
        return None
    return {
        'count': len(days),
        'avg_days': sum(days) / len(days),
        'min_days': min(days),
        'max_days': max(days),
    }


@dataclass
class Estimate:
    """estimated lifetime and its basis

    JP:
    推定使用日数とその根拠。
    """
    days: Optional[float]
    basis: str
    samples: list[int] = field(default_factory=list)


def estimate_days(lifetimes: Iterable, summaries: Iterable = (),
                  default_days: Optional[int] = None,
                  window: int = DEFAULT_WINDOW,
                  short_ratio: float = DEFAULT_SHORT_RATIO) -> Estimate:
    """estimate how many days one bottle lasts

    JP:
    1本が何日もつかを推定する。
    """
    days = regular_days(lifetimes, short_ratio)
    if days:
        recent = days[-window:]
        est = Estimate(sum(recent) / len(recent),
                       f'recent {len(recent)}', recent)
    else:
        total = count = 0
        for row in summaries:
            total += row['avg_days'] * row['count']
            count += row['count']
        if count:
            est = Estimate(total / count, 'past years')
        elif default_days:
            est = Estimate(float(default_days), 'default')
        else:
            est = Estimate(None, 'no data')
    return est


@dataclass
class Requirement:
    """required count until next visit for one drug

    JP:
    1つの薬の次回受診までの必要数。
    """
    stock: int
    estimate: Estimate
    opened: Optional[date] = None    # 開封中の開封日
    elapsed: Optional[int] = None    # 開封からの経過日数
    remaining: Optional[int] = None  # 開封中の推定残日数(来院日時点)
    normal: Optional[int] = None     # 通常期間(1本の推定日数を丸めたもの)
    opened_left: Optional[int] = None  # 開封分残日数(来院日時点。開封中なしは0)
    stock_days: Optional[int] = None   # 在庫残日数(来院日時点)
    short_days: Optional[int] = None   # 足りない日数(span - 在庫残日数)
    need: Optional[int] = None       # 必要本数(処方をお願いする本数。予備を含む)
    max_days: Optional[int] = None   # 廃棄期限日数
    as_needed: bool = False          # 随時使用
    warnings: list[str] = field(default_factory=list)  # 警告
    info: list[str] = field(default_factory=list)      # 情報


def requirement(stock: int, est: Estimate, opened, today, span: int,
                max_days: Optional[int] = None,
                margin_days: int = 0,
                as_needed: bool = False,
                spare: int = SPARE_BOTTLES) -> Requirement:
    """calculate required bottles until next visit

    JP:
    次回来院日(来院日 today + span 日)までに必要な本数を計算する。
    opened は開封中のライフタイムの開封日(無ければ None)。
    margin_days は受診が遅れた時などのための余裕日数。
    as_needed(随時使用)なら必要本数は None のまま。
    """
    today = to_date(today)
    req = Requirement(stock=stock, estimate=est, opened=to_date(opened),
                      max_days=max_days, as_needed=as_needed)
    if stock < 0:
        req.warnings.append('stock negative')
    if est.days is not None:
        # 四捨五入(round() は .5 を偶数に丸めるので使わない)
        req.normal = max(1, math.floor(est.days + 0.5))
    if req.opened is not None:
        req.elapsed = (today - req.opened).days
        if max_days and req.elapsed > max_days:
            req.info.append('over max_days')
        if req.normal is not None:
            req.remaining = max(0, req.normal - req.elapsed)
            if req.elapsed > req.normal:
                req.info.append('over estimate')
    if req.normal is None or as_needed:
        return req
    req.opened_left = req.remaining or 0
    req.stock_days = req.opened_left + max(stock, 0) * req.normal
    req.short_days = span + margin_days - req.stock_days
    req.need = max(0, math.ceil(req.short_days / req.normal) + spare)
    return req
