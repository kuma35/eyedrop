# -*- coding: utf-8 -*-
"""yearly rollover (backup, export, carry forward)

JP:
年次更新
========

cutoff_year を指定すると、その年の1月1日より前の記録を過去年分として
退避します。

1. データベース全体をバックアップ(sqlite の .db ファイル)
2. 退避する在庫記録・ライフタイムを CSV にエクスポート
3. 在庫管理: 前年12月31日時点の残高を棚卸し記録として繰り越し、
   それより前の在庫記録を削除
4. ライフタイム管理: 前年までに終了したライフタイムのうち、
   イレギュラーでない妥当な値を年ごとの過去年値(lifetime_summary)に
   要約して残し、記録は削除

ただしライフタイムは、薬ごとにイレギュラーでない使い切りの実績を直近
KEEP_RECENT(3)回分は必ず残す(その一番古い開封以降の記録を残す)。
年明けすぐに実行しても直近3本の平均などが取れるようにするため。
区切りより前の記録が残ることがあるが、それらは過去年値に入れず、
次の年次更新で退避するときに入れる(二重に数えない)。
実績が2回・1回しか無ければその分だけ残る。0回なら過去年値で推定する。

cutoff_year に今年を指定すれば「年次更新時点で棚卸し」、
昨年を指定すれば「昨年までは持っていて一昨年以前を対象とする」運用になります。
既定は昨年(一昨年以前を退避)です。
"""
import csv
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import sql_edit as E
from .drugdb import DrugDb
from .estimate import DEFAULT_WINDOW, regular_rows, summarize

CARRY_NOTE = '年次更新繰越'
# 推定に使う直近の実績の数(estimate の window と同じ)は必ず残す
KEEP_RECENT = DEFAULT_WINDOW


def keep_from(lifetimes) -> str:
    """start date from which lifetimes must be kept

    JP:
    イレギュラーでない使い切りの実績のうち直近 KEEP_RECENT 回の、
    一番古い開封日。これ以降のライフタイムは退避しない。
    実績が無ければ '' (区切りどおりに退避してよい)。
    """
    recent = regular_rows(lifetimes)[-KEEP_RECENT:]
    return min(row['use_start'] for row, _ in recent) if recent else ''


@dataclass
class RolloverResult:
    """rollover result

    JP:
    年次更新の結果。
    """
    backup: Path
    export_dir: Path
    stock_archived: int = 0
    lifetime_archived: int = 0
    carried: dict = field(default_factory=dict)  # 薬名 -> 繰越在庫数


def _export_csv(path: Path, rows: list[sqlite3.Row], columns: list[str]):
    with path.open('w', newline='', encoding='utf-8') as out:
        writer = csv.writer(out)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row[c] for c in columns])


def backup_database(db: DrugDb, path: Path) -> Path:
    """backup whole database to path

    JP:
    データベース全体を path にバックアップする。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    dest = sqlite3.connect(path)
    try:
        db.conn.backup(dest)
    finally:
        dest.close()
    return path


def rollover(db: DrugDb, cutoff_year: int, out_dir,
             today=None) -> RolloverResult:
    """archive records before cutoff_year-01-01

    JP:
    cutoff_year 年1月1日より前の記録を退避する。
    """
    today = today or date.today()
    out_dir = Path(out_dir)
    cutoff = date(cutoff_year, 1, 1)
    carry_date = (cutoff - timedelta(days=1)).isoformat()
    cutoff_iso = cutoff.isoformat()

    # 終了日なしで残った古い開封を直してから(退避の対象になるように)
    db.close_stale_lifetimes()
    stamp = today.strftime('%Y%m%d')
    backup = backup_database(
        db, out_dir / f'eyedrop-{stamp}-before-rollover-{cutoff_year}.db')
    export_dir = out_dir / f'archive-before-{cutoff_year}'
    export_dir.mkdir(parents=True, exist_ok=True)
    result = RolloverResult(backup=backup, export_dir=export_dir)

    conn = db.conn
    stock_rows = conn.execute(
        'SELECT drug.name, stock.* FROM stock JOIN drug USING (drug_id)'
        ' WHERE stock_date <= ? ORDER BY drug_id, stock_date, stock_id',
        (carry_date,)).fetchall()
    _export_csv(export_dir / 'stock.csv', stock_rows,
                ['stock_id', 'drug_id', 'name', 'stock_date', 'kind', 'qty',
                 'note'])
    # 区切りより前に終わったライフタイムのうち、直近の実績(KEEP_RECENT 回)
    # より前のものだけを退避する
    life_rows = []
    for drug in db.list_drugs():
        rows = conn.execute(
            'SELECT drug.name, lifetime.* FROM lifetime JOIN drug'
            ' USING (drug_id) WHERE drug_id = ?'
            ' ORDER BY use_start, lifetime_id', (drug['drug_id'],)).fetchall()
        keep = keep_from(rows)
        life_rows += [r for r in rows
                      if r['use_end'] is not None and r['use_end'] < cutoff_iso
                      and not (keep and r['use_start'] >= keep)]
    _export_csv(export_dir / 'lifetime.csv', life_rows,
                ['lifetime_id', 'drug_id', 'name', 'use_start', 'use_end',
                 'irregular', 'note'])

    # 過去年値: 年(開封年)ごとに妥当な値を要約
    by_drug = defaultdict(list)
    for row in life_rows:
        by_drug[row['drug_id']].append(row)
    summaries = []
    for drug_id, rows in by_drug.items():
        by_year = defaultdict(list)
        for row, days in regular_rows(rows):
            by_year[int(row['use_start'][:4])].append(days)
        for year, year_days in by_year.items():
            summaries.append(dict(summarize(year_days), drug_id=drug_id,
                                  year=year))

    with conn:
        for drug in db.list_drugs():
            has_old = conn.execute(
                'SELECT count(*) FROM stock WHERE drug_id = ?'
                ' AND stock_date <= ?',
                (drug['drug_id'], carry_date)).fetchone()[0]
            if not has_old:
                continue
            balance = db.balance(drug['drug_id'], as_of=carry_date)
            conn.execute('DELETE FROM stock WHERE drug_id = ?'
                         ' AND stock_date <= ?',
                         (drug['drug_id'], carry_date))
            conn.execute(
                'INSERT INTO stock (drug_id, stock_date, kind, qty, note)'
                " VALUES (?, ?, 'inventory', ?, ?)",
                (drug['drug_id'], carry_date, max(balance, 0), CARRY_NOTE))
            result.carried[drug['name']] = balance
            result.stock_archived += has_old
        for summary in summaries:
            conn.execute(E.MERGE_SUMMARY, summary)
        conn.executemany('DELETE FROM lifetime WHERE lifetime_id = ?',
                         [(r['lifetime_id'],) for r in life_rows])
        result.lifetime_archived = len(life_rows)
    db.set_meta('last_rollover', f'{cutoff_year}:{today.isoformat()}')
    conn.execute('VACUUM')
    return result
