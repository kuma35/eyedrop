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

次回受診までの日数 span のうち、開封中の分の推定残日数で賄えない日数を
推定使用日数で割って切り上げたものが必要本数。
必要本数から未開封在庫数を引いたものが依頼数。
必要本数には予備 SPARE_BOTTLES(1本程度の余裕)を含める。
依頼数は1回の処方の上限 MAX_PRESCRIPTION(3本)を超えない。
予備を除いた使用分だけで上限を超える分を不足数(shortage)とし、警告を出す
(予備が上限で削られるだけなら警告しない)。在庫が3本を超えるのは構わない。

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
# 1回の処方で出してもらえる最大本数(健康保険による制限。絶対)
MAX_PRESCRIPTION = 3
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
    remaining: Optional[float] = None  # 開封中の推定残日数
    need: Optional[int] = None       # 必要本数(予備を含む)
    use: Optional[int] = None        # 期間中に使う本数(予備を含まない)
    spare: int = 0                   # 予備の本数
    request: Optional[int] = None    # 依頼数(処方上限まで)
    shortage: int = 0                # 処方上限を超えて足りない本数
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
    次回受診(today + span 日)までに必要な本数と依頼数を計算する。
    opened は開封中のライフタイムの開封日(無ければ None)。
    margin_days は受診が遅れた時などのための余裕日数。
    as_needed(随時使用)なら必要本数・依頼数は None のまま。
    """
    today = to_date(today)
    req = Requirement(stock=stock, estimate=est, opened=to_date(opened),
                      max_days=max_days, as_needed=as_needed)
    if stock < 0:
        req.warnings.append('stock negative')
    if req.opened is not None:
        req.elapsed = (today - req.opened).days
        if max_days and req.elapsed > max_days:
            req.info.append('over max_days')
        if est.days is not None:
            req.remaining = max(0.0, est.days - req.elapsed)
            if req.elapsed > est.days:
                req.info.append('over estimate')
    if est.days is None or as_needed:
        return req
    cover = span + margin_days - (req.remaining or 0.0)
    req.use = max(0, math.ceil(cover / est.days)) if cover > 0 else 0
    req.spare = spare
    req.need = req.use + spare
    stock = max(stock, 0)
    req.request = min(max(0, req.need - stock), MAX_PRESCRIPTION)
    req.shortage = max(0, req.use - stock - MAX_PRESCRIPTION)
    if req.shortage:
        req.warnings.append('over prescription limit')
    return req
