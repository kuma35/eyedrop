# -*- coding: utf-8 -*-
"""tests for drugdb

JP:
drugdb のテスト。プロジェクト直下で

.. code-block:: shell

   python3 -m unittest discover -s tests
"""
import csv
import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from drugdb import cli
from drugdb.cli import DrugDbShell, main
from drugdb.drugdb import DrugDb, DrugDbError
from drugdb.estimate import (estimate_days, last_days, regular_days,
                             requirement)
from drugdb.import_ods import Cell, import_ods, import_sheet
from drugdb.report import (make_report, need_cell, to_markdown,
                           to_plain_text)
from drugdb.rollover import rollover

# 開発用データ(本番のコピー)。非公開なので git 管理外。無ければスキップ
ODS = Path(__file__).resolve().parent.parent / 'eyedrop-stock.ods'


def life(start, end, irregular=0):
    """lifetime row for estimate functions"""
    return {'use_start': start, 'use_end': end, 'irregular': irregular}


class TestEstimate(unittest.TestCase):
    """estimate.py"""

    def test_regular_days_excludes_irregular_open_and_short(self):
        rows = [life('2024-01-01', '2024-01-31'),       # 30
                life('2024-01-31', '2024-02-05'),       # 5 極端に短い
                life('2024-02-05', '2024-03-06', 1),    # イレギュラー
                life('2024-03-06', '2024-04-03'),       # 28
                life('2024-04-03', None)]               # 開封中
        self.assertEqual(regular_days(rows), [30, 28])

    def test_estimate_recent_window(self):
        rows = [life('2024-01-01', '2024-02-10'),       # 40
                life('2024-02-10', '2024-03-11'),       # 30
                life('2024-03-11', '2024-04-10'),       # 30
                life('2024-04-10', '2024-05-10')]       # 30
        est = estimate_days(rows, window=3)
        self.assertEqual(est.days, 30)
        self.assertEqual(est.samples, [30, 30, 30])

    def test_estimate_fallbacks(self):
        summaries = [{'avg_days': 30.0, 'count': 2},
                     {'avg_days': 36.0, 'count': 1}]
        self.assertEqual(estimate_days([], summaries).days, 32)
        self.assertEqual(estimate_days([], default_days=20).days, 20)
        self.assertIsNone(estimate_days([]).days)

    def test_last_days(self):
        rows = [life('2024-01-01', '2024-01-31'),
                life('2024-01-31', '2024-03-01'),
                life('2024-03-01', None)]
        self.assertEqual(last_days(rows), 30)
        # 直近がイレギュラーなら空欄(None)。遡らない
        rows[1]['irregular'] = 1
        self.assertIsNone(last_days(rows))
        self.assertIsNone(last_days([life('2024-03-01', None)]))

    def test_requirement(self):
        est = estimate_days([life('2024-01-01', '2024-01-31')])  # 30日
        # 開封10日目: 残20日、在庫1 -> 在庫残日数50。60 - 50 = 10日 -> 1本
        req = requirement(1, est, '2024-06-01', '2024-06-11', 60, spare=0)
        self.assertEqual((req.remaining, req.short_days, req.need),
                         (20, 10, 1))
        # 在庫が十分(足りない日数 -50 -> 0本)
        req = requirement(3, est, '2024-06-01', '2024-06-11', 60, spare=0)
        self.assertEqual((req.short_days, req.need), (-50, 0))
        # 開封中なし
        req = requirement(0, est, None, '2024-06-11', 60, spare=0)
        self.assertEqual((req.short_days, req.need), (60, 2))
        # 残りだけで足りる
        req = requirement(0, est, '2024-06-10', '2024-06-11', 20, spare=0)
        self.assertEqual((req.short_days, req.need), (-9, 0))

    def test_normal_days_rounding(self):
        from drugdb.estimate import Estimate
        # 通常期間は四捨五入(.5 は常に切り上げ)
        for avg, normal in ((30.5, 31), (31.5, 32), (30 + 1 / 3, 30),
                            (30 + 2 / 3, 31), (30.49, 30), (0.4, 1)):
            with self.subTest(avg=avg):
                req = requirement(0, Estimate(avg, 'recent 2'), None,
                                  '2024-06-11', 60)
                self.assertEqual(req.normal, normal)

    def test_requirement_no_prescription_limit(self):
        est = estimate_days([life('2024-01-01', '2024-01-11')])  # 10日
        # 1回の処方の上限は設けない(条件が不明なため)
        # 開封中なし、在庫1 -> 在庫残日数10、足りない日数50 -> 5本 + 予備1
        req = requirement(1, est, None, '2024-06-11', 60)
        self.assertEqual((req.short_days, req.need), (50, 6))
        self.assertEqual(req.warnings, [])
        # 在庫が多くても構わない(足りない日数 -10 -> -1 + 予備1 = 0本)
        req = requirement(7, est, None, '2024-06-11', 60)
        self.assertEqual((req.short_days, req.need), (-10, 0))

    def test_requirement_spare(self):
        est = estimate_days([life('2024-01-01', '2024-01-31')])  # 30日
        # 残20日、在庫1 -> 足りない日数10 -> 1本 + 予備1 = 2本
        req = requirement(1, est, '2024-06-01', '2024-06-11', 60)
        self.assertEqual(req.need, 2)
        # 開封中なし、在庫0、90日 -> 3本 + 予備1 = 4本
        req = requirement(0, est, None, '2024-06-11', 90)
        self.assertEqual(req.need, 4)
        self.assertEqual(req.warnings, [])

    def test_requirement_warnings(self):
        est = estimate_days([life('2024-01-01', '2024-01-31')])
        req = requirement(-1, est, '2024-06-01', '2024-07-20', 60,
                          max_days=28, spare=0)
        self.assertEqual(req.warnings, ['stock negative'])
        # 廃棄期限・推定超過は info のみ
        self.assertEqual(set(req.info), {'over max_days', 'over estimate'})
        self.assertEqual(req.remaining, 0)
        self.assertEqual(req.need, 2)

    def test_max_days_does_not_cap_estimate(self):
        # キサラタン: 廃棄期限28日でも実績32日ならそのまま32日で推定
        est = estimate_days([life('2024-01-01', '2024-02-02')])
        self.assertEqual(est.days, 32)
        req = requirement(0, est, '2024-06-01', '2024-06-30', 60,
                          max_days=28, spare=0)
        self.assertEqual(req.info, ['over max_days'])
        self.assertEqual((req.remaining, req.need), (3, 2))

    def test_requirement_as_needed(self):
        est = estimate_days([life('2024-01-01', '2024-03-01')])
        req = requirement(2, est, None, '2024-06-11', 60, as_needed=True)
        self.assertIsNone(req.need)
        self.assertEqual(req.estimate.days, 60)


class DbTestCase(unittest.TestCase):
    """test case with temporary database"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.db = DrugDb(str(self.path / 'test.db'))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()


class TestDrugDb(DbTestCase):
    """drugdb.py"""

    def test_find_drug_by_id_name_alias(self):
        drug_id = self.db.add_drug('コソプト', '2022-01-01')
        self.db.add_alias('コソプト', 'ドルモロール', '2022-01-01')
        for key in (drug_id, str(drug_id), 'コソプト', 'ドルモロール'):
            self.assertEqual(self.db.find_drug(key)['drug_id'], drug_id)
        self.assertEqual(self.db.current_name(drug_id), 'ドルモロール')
        with self.assertRaises(DrugDbError):
            self.db.find_drug('無い薬')

    def test_balance_with_inventory_and_same_day(self):
        self.db.add_drug('A')
        self.db.inventory('A', 1, '2023-02-09')
        self.db.receive('A', 2, '2023-02-09')
        self.db.add_stock('A', 'out', 1, '2023-02-12')
        self.db.inventory('A', 5, '2023-03-01')
        self.db.add_stock('A', 'out', 1, '2023-03-01')
        self.assertEqual(
            [r['balance'] for r in self.db.stock_history('A')],
            [1, 3, 2, 5, 4])
        self.assertEqual(self.db.balance('A', as_of='2023-02-28'), 2)
        self.assertEqual(self.db.balance('A'), 4)

    def test_alias_end_date(self):
        self.db.add_drug('コソプト')
        self.db.add_alias('コソプト', 'ドルモロール', '2022-01-01')
        self.assertEqual(self.db.current_name('コソプト'), 'ドルモロール')
        # 切替時期は利用中の目薬名が2つ
        self.db.add_alias('コソプト', 'ジェネリックB', '2026-10-01')
        self.assertEqual(self.db.current_name('コソプト'),
                         'ドルモロール・ジェネリックB')
        self.db.end_alias('コソプト', 'ドルモロール', '2026-10-20')
        self.assertEqual(
            [r['alias_name'] for r in
             self.db.active_aliases('コソプト', as_of='2026-10-21')],
            ['ジェネリックB'])
        # 利用終了日の当日までは利用中
        self.assertEqual(
            len(self.db.active_aliases('コソプト', as_of='2026-10-20')), 2)
        # 利用中に戻す
        self.db.end_alias('コソプト', 'ドルモロール', '')
        self.assertIsNone(self.db.aliases('コソプト')[0]['end_date'])
        with self.assertRaises(DrugDbError):
            self.db.end_alias('コソプト', '無い名前', '2026-01-01')

    def test_all_aliases_ended_means_drug_ended(self):
        self.db.add_drug('ヒアレイン')
        self.db.add_alias('ヒアレイン', 'ヒアルロン酸', '2022-10-20')
        self.db.add_drug('B')             # 目薬名が無い薬は利用中
        self.assertEqual([r['name'] for r in
                          self.db.list_drugs(active_only=True)],
                         ['ヒアレイン', 'B'])
        self.db.end_alias('ヒアレイン', 'ヒアルロン酸', '2025-06-30')
        self.assertFalse(self.db.is_active('ヒアレイン'))
        self.assertEqual([r['name'] for r in
                          self.db.list_drugs(active_only=True)], ['B'])
        # 全部利用終了なら最後の名前
        self.assertEqual(self.db.current_name('ヒアレイン'), 'ヒアルロン酸')

    def test_migrate_alias_end_date(self):
        path = str(self.path / 'v3.db')
        conn = sqlite3.connect(path)
        conn.execute('CREATE TABLE drug_alias (alias_id INTEGER PRIMARY KEY,'
                     ' drug_id INTEGER NOT NULL, alias_name TEXT NOT NULL,'
                     ' start_date TEXT, note TEXT)')
        conn.commit()
        conn.close()
        with DrugDb(path) as old:
            columns = [r['name'] for r in
                       old.conn.execute('PRAGMA table_info(drug_alias)')]
            self.assertIn('end_date', columns)

    def test_duplicate_drug_name(self):
        self.db.add_drug('コソプト')
        with self.assertRaises(DrugDbError):
            self.db.add_drug('コソプト')
        self.db.add_drug('キサラタン')
        with self.assertRaises(DrugDbError):
            self.db.update_drug('キサラタン', name='コソプト')

    def test_invalid_stock(self):
        self.db.add_drug('A')
        with self.assertRaises(DrugDbError):
            self.db.add_stock('A', 'bad', 1)
        with self.assertRaises(DrugDbError):
            self.db.receive('A', -1)

    def test_open_bottle_closes_previous(self):
        self.db.add_drug('A')
        self.db.receive('A', 3, '2024-01-01')
        self.db.open_bottle('A', '2024-01-01')
        self.db.open_bottle('A', '2024-01-31')
        rows = self.db.lifetimes('A')
        self.assertEqual(rows[0]['use_end'], '2024-01-31')
        self.assertIsNone(rows[1]['use_end'])
        self.assertEqual(self.db.opened('A')['use_start'], '2024-01-31')
        self.assertEqual(self.db.balance('A'), 1)
        with self.assertRaises(DrugDbError):
            self.db.open_bottle('A', '2024-01-15')

    def test_as_of_past_date(self):
        self.db.add_drug('A')
        self.db.receive('A', 3, '2024-01-01')
        for day in ('2024-01-01', '2024-01-31', '2024-03-01'):
            self.db.open_bottle('A', day)
        # 2/10 時点: 1/31 開封分が使用中、実績は 1/1〜1/31 の30日だけ
        self.assertEqual(self.db.opened('A', as_of='2024-02-10')['use_start'],
                         '2024-01-31')
        self.assertEqual(self.db.estimate('A', as_of='2024-02-10').samples,
                         [30])
        req = self.db.requirement('A', span=60, today='2024-02-10')
        self.assertEqual((req.stock, req.elapsed, req.remaining),
                         (1, 10, 20))
        self.assertIsNone(self.db.opened('A', as_of='2023-12-31'))

    def test_close_stale_lifetimes(self):
        self.db.add_drug('A')
        # ods 取込で終了日の欄が空だった古い開封
        self.db.add_lifetime('A', '2022-11-20')
        self.db.add_lifetime('A', '2022-12-25')
        self.db.add_lifetime('A', '2023-01-22', '2023-02-17')
        self.db.add_lifetime('A', '2026-08-20')          # 本当の開封中
        fixed = self.db.close_stale_lifetimes()
        self.assertEqual([(r['use_start'], r['use_end']) for r in fixed],
                         [('2022-11-20', '2022-12-25'),
                          ('2022-12-25', '2023-01-22')])
        rows = self.db.lifetimes('A')
        self.assertEqual([r['irregular'] for r in rows], [1, 1, 0, 0])
        self.assertIn('終了日なし', rows[0]['note'])
        self.assertEqual(self.db.opened('A')['use_start'], '2026-08-20')
        self.assertEqual(self.db.close_stale_lifetimes(), [])  # 2回目は何もしない

    def test_open_closes_only_latest(self):
        self.db.add_drug('A')
        self.db.add_lifetime('A', '2022-12-05')          # 古い開封中
        self.db.add_lifetime('A', '2026-09-25')
        self.db.open_bottle('A', '2026-10-20', from_stock=False)
        rows = self.db.lifetimes('A')
        self.assertIsNone(rows[0]['use_end'])            # 巻き込まない
        self.assertEqual(rows[1]['use_end'], '2026-10-20')

    def test_undo_open(self):
        self.db.add_drug('A')
        self.db.receive('A', 3, '2024-01-01')
        self.db.open_bottle('A', '2024-01-01')
        self.db.open_bottle('A', '2024-01-31')
        done = self.db.undo_open('A')
        self.assertEqual(done['lifetime']['use_start'], '2024-01-31')
        rows = self.db.lifetimes('A')
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['use_end'])            # 使用中に戻る
        self.assertEqual(self.db.balance('A'), 2)        # 在庫が戻る
        self.db.undo_open('A')                           # 最初の開封も取消
        self.assertEqual((self.db.lifetimes('A'), self.db.balance('A')),
                         ([], 3))
        with self.assertRaises(DrugDbError):
            self.db.undo_open('A')

    def test_undo_open_without_stock(self):
        self.db.add_drug('A')
        self.db.receive('A', 1, '2024-01-01')
        self.db.inventory('A', 0, '2024-01-05')
        self.db.open_bottle('A', '2024-01-10', from_stock=False)
        self.db.undo_open('A')
        self.assertEqual(len(self.db.stock_history('A')), 2)  # 在庫は動かない

    def test_undo_open_after_finish(self):
        self.db.add_drug('A')
        self.db.open_bottle('A', '2024-01-01', from_stock=False)
        self.db.finish_bottle('A', '2024-01-05')
        self.assertIsNone(self.db.last_open('A'))
        with self.assertRaises(DrugDbError):
            self.db.undo_open('A')

    def test_undo_open_legacy(self):
        # 旧バージョンの開封(出庫・前の1本との対応が記録されていない)
        self.db.add_drug('A')
        self.db.receive('A', 3, '2024-01-01')
        self.db.open_bottle('A', '2024-01-01')
        self.db.open_bottle('A', '2024-01-31')
        self.db.conn.execute('UPDATE lifetime SET out_stock_id = NULL,'
                             ' prev_lifetime_id = NULL')
        self.db.undo_open('A')
        self.assertEqual(self.db.balance('A'), 2)
        self.assertIsNone(self.db.lifetimes('A')[0]['use_end'])

    def test_undo_open_stock_rolled_over(self):
        self.db.add_drug('A')
        self.db.receive('A', 3, '2024-01-01')
        self.db.open_bottle('A', '2024-01-01')
        lifetime = self.db.lifetimes('A')[0]
        self.db.delete_stock(lifetime['out_stock_id'])   # 年次更新で退避
        with self.assertRaises(DrugDbError):
            self.db.undo_open('A')

    def test_finish_bottle(self):
        self.db.add_drug('A')
        self.db.open_bottle('A', '2024-01-01', from_stock=False)
        self.db.finish_bottle('A', '2024-01-05', irregular=True,
                              note='紛失')
        row = self.db.lifetimes('A')[0]
        self.assertEqual((row['use_end'], row['irregular'], row['note']),
                         ('2024-01-05', 1, '紛失'))
        self.assertIsNone(self.db.opened('A'))
        self.assertEqual(self.db.balance('A'), 0)
        with self.assertRaises(DrugDbError):
            self.db.finish_bottle('A')

    def test_update_drug(self):
        self.db.add_drug('キサラタン')
        self.db.update_drug('キサラタン', max_days=28, end_date='2024-05-01')
        drug = self.db.find_drug('キサラタン')
        self.assertEqual((drug['max_days'], drug['end_date']),
                         (28, '2024-05-01'))
        self.assertEqual(self.db.list_drugs(active_only=True), [])
        with self.assertRaises(DrugDbError):
            self.db.update_drug('キサラタン', drug_id=9)

    def test_reopen_existing_file(self):
        self.db.add_drug('A')
        self.db.close()
        self.db = DrugDb(str(self.path / 'test.db'))
        self.assertEqual(len(self.db.list_drugs()), 1)
        self.assertEqual(self.db.get_meta('schema_version'), '6')

    def test_migrate_add_as_needed(self):
        path = str(self.path / 'old.db')
        conn = sqlite3.connect(path)
        conn.execute('CREATE TABLE drug (drug_id INTEGER PRIMARY KEY,'
                     ' name TEXT NOT NULL UNIQUE, start_date TEXT,'
                     ' end_date TEXT, max_days INTEGER,'
                     ' default_days INTEGER, note TEXT)')
        conn.execute("INSERT INTO drug (name) VALUES ('ヒアレイン')")
        conn.commit()
        conn.close()
        with DrugDb(path) as old:
            self.assertEqual(old.find_drug('ヒアレイン')['as_needed'], 0)
            old.update_drug('ヒアレイン', as_needed=1)
            self.assertEqual(old.find_drug('ヒアレイン')['as_needed'], 1)


def make_sample(db):
    """sample: A 30日/本, 在庫1, 2024-06-01開封"""
    db.add_drug('A', '2024-01-01')
    db.add_alias('A', 'A-generic', '2024-03-01')
    db.receive('A', 7, '2024-01-01')
    for day in ('2024-01-02', '2024-02-01', '2024-03-02', '2024-04-01',
                '2024-05-01', '2024-06-01'):
        db.open_bottle('A', day)
    db.add_drug('B', '2024-01-01')      # 実績なし
    db.receive('B', 2, '2024-01-01')
    db.add_drug('C', '2023-01-01')      # 使用終了
    db.update_drug('C', end_date='2023-12-31')


class TestReport(DbTestCase):
    """report.py"""

    def test_report(self):
        make_sample(self.db)
        report = make_report(self.db, today='2024-06-11', span=60)
        self.assertEqual(report.next_visit, date(2024, 8, 10))
        self.assertEqual([line.name for line in report.lines], ['A', 'B'])
        req = report.lines[0].req
        self.assertEqual((req.stock, req.need), (1, 2))
        # 根拠: 通常期間30日、6/1開封・来院日で10日経過、次回来院日まで60日
        # 開封分残日数 = 30 - (6/11 - 6/1 = 10) = 20
        # 在庫残日数 = 20 + 1 * 30 = 50
        # 足りない日数 = 60 - 50 = 10
        # 必要本数 = ceil(10 / 30) + 予備1 = 2
        self.assertEqual((req.normal, req.opened_left, req.stock_days,
                          req.short_days), (30, 20, 50, 10))
        text = to_markdown(report)
        self.assertTrue(text.startswith(
            '# 目薬 受診前サマリー\n\n- 来院日 2024-06-11\n'
            '- 次回来院日 2024-08-10(60日後)\n'))
        # 期間パターンの表示は無し
        self.assertNotIn('2ヶ月', text)
        self.assertIn('| A | 1 | 6/1 | 10 | 20 | 31 |', text)
        self.assertIn('| 代表目薬名(目薬名) | 必要本数 | 足りない日数'
                      ' | 在庫残日数 | 未開封 | 通常期間 | 開封分残日数 |', text)
        self.assertIn('| A(A-generic) | 2 | 10 | 50 | 1 | 30 | 20 |', text)
        self.assertIn('| 代表目薬名 | 未開封個数 |', text)
        self.assertIn('| B | 相談 |  |  | 2 |  |  |', text)
        self.assertIn('- A(A-generic): 通常期間 30日 (直近3本の平均', text)
        self.assertLess(text.index('## 次回来院までに必要な本数'),
                        text.index('## 目薬在庫'))

    def test_required_count_basis(self):
        from drugdb.estimate import Estimate, requirement
        est = Estimate(30.4, 'recent 3', [30, 30, 31])
        # 6/1開封・6/11来院 -> 開封分残日数20、在庫1本で在庫残日数50
        req = requirement(1, est, '2024-06-01', '2024-06-11', span=10)
        self.assertEqual((req.opened_left, req.stock_days, req.short_days,
                          req.need), (20, 50, -40, 0))
        # 足りない日数が -29〜0 なら予備の1本
        req = requirement(1, est, '2024-06-01', '2024-06-11', span=20)
        self.assertEqual((req.short_days, req.need), (-30, 0))
        req = requirement(1, est, '2024-06-01', '2024-06-11', span=21)
        self.assertEqual((req.short_days, req.need), (-29, 1))
        req = requirement(1, est, '2024-06-01', '2024-06-11', span=50)
        self.assertEqual((req.short_days, req.need), (0, 1))
        # 足りない日数 1〜30 なら 1 + 予備1
        req = requirement(1, est, '2024-06-01', '2024-06-11', span=51)
        self.assertEqual((req.short_days, req.need), (1, 2))
        # 来院日で通常期間を超えて使っている1本は残り0日
        req = requirement(0, est, '2024-05-01', '2024-06-11', span=30)
        self.assertEqual((req.remaining, req.opened_left, req.stock_days,
                          req.short_days, req.need), (0, 0, 0, 30, 2))
        # 開封中が無ければ開封分残日数0
        req = requirement(0, est, None, '2024-06-11', span=60)
        self.assertEqual((req.opened_left, req.short_days, req.need),
                         (0, 60, 3))
        # 随時使用は根拠を出さない
        req = requirement(1, est, None, '2024-06-11', span=60,
                          as_needed=True)
        self.assertIsNone(req.stock_days)

    def test_required_count_by_history(self):
        """required count by number of finished bottles (0 to 3, and 4)

        JP:
        使い切った実績の件数ごとの必要本数。未開封0本、来院日は最後の開封の
        10日後、次回来院日は60日後。
        """
        cases = [
            # (使い切り日数, 通常期間, 開封分残日数, 足りない日数, 必要本数)
            ([], None, None, None, '相談'),                # 実績なし
            ([30], 30, 20, 40, '3'),                       # 1本: 30
            ([30, 28], 29, 19, 41, '3'),                   # 2本: (30+28)/2
            ([30, 28, 32], 30, 20, 40, '3'),               # 3本: (30+28+32)/3
            ([30, 28, 32, 36], 32, 22, 38, '3'),           # 直近3本: 28,32,36
            ([60, 60, 60], 60, 50, 10, '2'),               # 1本分 + 予備1
            ([90, 90, 90], 90, 80, -20, '1'),              # 足りるので予備1だけ
            ([150, 150, 150], 150, 140, -80, '1'),         # 同上(-80/150→0)
        ]
        for days, normal, opened_left, short, need in cases:
            with self.subTest(days=days):
                db = DrugDb(':memory:')
                db.add_drug('X', '2024-01-01')
                db.receive('X', len(days) + 1, '2024-01-01')
                opened = date(2024, 1, 1)
                db.open_bottle('X', opened)
                for length in days:
                    opened += timedelta(days=length)
                    db.open_bottle('X', opened)
                visit = opened + timedelta(days=10)
                report = make_report(db, today=visit, span=60)
                req = report.lines[0].req
                self.assertEqual(req.estimate.samples, days[-3:])
                self.assertEqual((req.normal, req.opened_left, req.short_days),
                                 (normal, opened_left, short))
                self.assertEqual(need_cell(req), need)
                if normal is not None:
                    # 在庫残日数 = 開封分残日数(未開封0本)
                    self.assertEqual(req.stock_days, opened_left)
                    self.assertIn(f'通常期間 {normal}日 (直近'
                                  f'{len(days[-3:])}本の平均', to_markdown(report))
                db.close()

    def test_change_pattern(self):
        """eye drop pattern change marks only the latest lifetime

        JP:
        点眼パターン変更: 変更日より前に開封した直近の1件(開封中)だけを
        イレギュラーにし、メモに「点眼パターン変更」を追記。推定はそれより前を
        辿らないので、以後は変更後の実績だけで推定する。
        """
        self.db.add_drug('X', '2024-01-01')
        self.db.receive('X', 6, '2024-01-01')
        for day in ('2024-01-01', '2024-01-31', '2024-03-01', '2024-03-31'):
            self.db.open_bottle('X', day)
        lives = self.db.lifetimes('X')
        self.db.set_irregular(lives[3]['lifetime_id'], False,
                              note='予備を先に開封')
        # 4/10 に1日2回→1回に変更(開封中の 3/31 の1本が対象)
        marked = self.db.change_pattern('X', '2024-04-10', '1日2回→1回')
        self.assertEqual(marked, lives[3]['lifetime_id'])
        lives = self.db.lifetimes('X')
        self.assertEqual([r['irregular'] for r in lives], [0, 0, 0, 1])
        self.assertEqual(lives[3]['note'], '予備を先に開封 / '
                         '点眼パターン変更(2024-04-10) 1日2回→1回')
        self.assertEqual(self.db.find_drug('X')['pattern_date'], '2024-04-10')
        # イレギュラーより前は辿らないので推定できず「相談」
        report = make_report(self.db, today='2024-04-11', span=60)
        self.assertEqual(need_cell(report.lines[0].req), '相談')
        # 変更後の1本を使い切ると、その1本だけで推定する
        self.db.open_bottle('X', '2024-04-10')
        self.db.open_bottle('X', '2024-06-09')
        est = self.db.estimate('X')
        self.assertEqual((est.days, est.samples), (60, [60]))
        # 変更日より前の開封が無ければ何もしない(変更日だけ記録)
        self.db.add_drug('Y')
        self.assertIsNone(self.db.change_pattern('Y', '2024-04-10'))

    def test_estimate_stops_at_irregular(self):
        """estimate uses only lifetimes after the last irregular

        JP:
        イレギュラーが1つあれば、そこより前には辿らない(紛失などでも同じ)。
        """
        rows = [life('2024-01-01', '2024-01-31'),
                life('2024-01-31', '2024-03-01'),
                life('2024-03-01', '2024-03-20'),
                life('2024-03-20', '2024-04-17'),
                life('2024-04-17', '2024-05-17')]
        # 19日は極端に短いので自動で除外(中央値29 * 0.7 未満)
        self.assertEqual(estimate_days(rows).samples, [30, 28, 30])
        rows[2]['irregular'] = 1               # 3/1〜3/20 が紛失など
        est = estimate_days(rows)
        self.assertEqual(est.samples, [28, 30])  # 前の30, 29 は使わない
        # 最後がイレギュラー(開封中を含む)なら実績なし。過去年値も辿らない
        rows.append(life('2024-05-17', None))
        rows[-1]['irregular'] = 1
        summary = [{'avg_days': 30, 'count': 3}]
        self.assertEqual(estimate_days(rows, summary, default_days=25).basis,
                         'default')
        self.assertEqual(estimate_days(rows, summary).basis, 'no data')

    def test_change_pattern_ignores_older_summaries(self):
        self.db.add_drug('X', '2020-01-01')
        self.db.conn.execute(
            "INSERT INTO lifetime_summary VALUES (1, 2023, 10, 30, 28, 32)")
        self.db.conn.execute(
            "INSERT INTO lifetime_summary VALUES (1, 2024, 3, 60, 58, 62)")
        self.assertEqual(self.db.estimate('X').days, (300 + 180) / 13)
        self.db.change_pattern('X', '2024-01-20')
        est = self.db.estimate('X')
        self.assertEqual((est.days, est.basis), (60, 'past years'))
        self.db.change_pattern('X', '2025-01-20')
        self.assertEqual(self.db.estimate('X').basis, 'no data')

    def test_cli_pattern(self):
        out = io.StringIO()
        shell = DrugDbShell(self.db, stdout=out)
        for line in ('add X', 'in X 2 -d 2024-01-01',
                     'open X -d 2024-01-01', 'open X -d 2024-01-31',
                     'pattern X -d 2024-02-10 -m 両眼に変更', 'show X',
                     'life X'):
            shell.onecmd(line)
        text = out.getvalue()
        self.assertIn('点眼パターン変更: ライフタイム 2 をイレギュラーにしました',
                      text)
        self.assertIn('点眼パターン変更 2024-02-10', text)
        self.assertIn('*2024-01-31', text)
        self.assertIn('点眼パターン変更(2024-02-10) 両眼に変更', text)

    def test_required_count_new_drug(self):
        """new drug without any stock or lifetime records

        JP:
        目薬を追加しただけ(入庫・開封の記録が全く無い)なら推定できず「相談」。
        """
        self.db.add_drug('X', '2024-01-01')
        report = make_report(self.db, today='2024-06-11', span=60)
        req = report.lines[0].req
        self.assertEqual((req.stock, req.opened, req.normal, req.need),
                         (0, None, None, None))
        self.assertEqual(need_cell(req), '相談')
        text = to_markdown(report)
        self.assertIn('| X | 相談 |  |  | 0 |  |  |', text)
        self.assertIn('- X: 通常期間 - (実績なし)', text)

    def test_report_next_visit_error(self):
        make_sample(self.db)
        for bad in ('2024-06-11', '2024-06-01'):
            with self.assertRaises(ValueError):
                make_report(self.db, today='2024-06-11', next_visit=bad)

    def test_plain_text(self):
        make_sample(self.db)
        self.db.add_drug('D', as_needed=True)
        self.db.receive('D', 2, '2024-01-01')
        text = to_plain_text(make_report(self.db, today='2024-06-11',
                                         name_mode='representative'))
        self.assertTrue(text.startswith(
            '目薬 受診前サマリー\n来院日 2024-06-11\n'
            '次回来院日 2024-08-10(60日後)\n'))
        self.assertIn('A  必要本数2  足りない日数10  在庫残日数50  未開封1'
                      '  通常期間30  開封分残日数20', text)
        self.assertIn('B  必要本数相談  未開封2', text)
        self.assertIn('D  必要本数随時  未開封2', text)
        self.assertIn('A  未開封1  開封日6/1  残日数20  通常日数31', text)
        self.assertNotIn('|', text)
        self.assertNotIn('#', text)

    def test_ai_export(self):
        import json
        from drugdb.ai_export import to_ai_data, to_ai_prompt
        make_sample(self.db)
        self.db.add_drug('D', as_needed=True)
        report = make_report(self.db, today='2024-06-11')
        data = to_ai_data(report)
        self.assertEqual((data['来院日'], data['次回来院日']),
                         ('2024-06-11', '2024-08-10'))
        a, b, d = data['目薬']
        self.assertEqual((a['代表目薬名'], a['目薬名'], a['未開封']),
                         ('A', 'A-generic', 1))
        self.assertEqual(a['推定残日数'], 20)
        self.assertEqual((a['必要本数'], a['足りない日数'], a['在庫残日数'],
                          a['通常期間'], a['開封分残日数']), (2, 10, 50, 30, 20))
        self.assertEqual(b['必要本数'], '相談')
        self.assertEqual(d['必要本数'], '随時')
        text = to_ai_prompt(report)
        self.assertIn('(2024-06-11 / 2024-08-10)', text)
        body = text.split('```json')[1].split('```')[0]
        self.assertEqual(json.loads(body), data)
        # 注意は日本語の文(内部コードを出さない)
        self.db.update_drug('A', max_days=5)
        notes = to_ai_data(make_report(self.db, today='2024-06-11'))['注意']
        self.assertTrue(any('廃棄期限' in n for n in notes))

    def test_spans(self):
        from drugdb.report import (DEFAULT_SPAN, get_default_span, parse_span,
                                   set_default_span, span_label, span_to_unit,
                                   unit_to_span)
        self.assertEqual(get_default_span(self.db), DEFAULT_SPAN)
        self.assertEqual([span_label(d) for d in (60, 28, 14, 30, 15, 56)],
                         ['2ヶ月', '4週間', '2週間', '1ヶ月', '15日', '8週間'])
        self.assertEqual([span_to_unit(d) for d in (60, 28, 14, 30, 10)],
                         [(2, 'ヶ月'), (4, '週間'), (2, '週間'), (1, 'ヶ月'),
                          (10, '日')])
        self.assertEqual(unit_to_span(2, 'ヶ月'), 60)
        self.assertEqual(unit_to_span('3', '週間'), 21)
        self.assertEqual(unit_to_span(10, '日'), 10)
        for bad in ((0, '週間'), ('x', '週間'), (1, '年'), (13, 'ヶ月')):
            with self.assertRaises(ValueError):
                unit_to_span(*bad)
        self.assertEqual([parse_span(t) for t in
                          ('2ヶ月', '2か月', '8週間', '8週', '60日', '60',
                           ' 3 ヶ月 ')], [60, 60, 56, 56, 60, 60, 90])
        for bad in ('', 'a', '0', '400', '2年', '1.5ヶ月'):
            with self.assertRaises(ValueError):
                parse_span(bad)
        # 以前の3つの期間の保存形式(先頭が通常)も読める
        self.db.set_meta('spans', '90,45,22')
        self.assertEqual(get_default_span(self.db), 90)
        self.db.set_meta('spans', 'x')
        self.assertEqual(get_default_span(self.db), DEFAULT_SPAN)
        with self.assertRaises(ValueError):
            set_default_span(self.db, 0)
        # 設定した期間で次回来院日を決める
        make_sample(self.db)
        set_default_span(self.db, 90)
        report = make_report(self.db, today='2024-06-11')
        self.assertEqual((report.span, report.next_visit),
                         (90, date(2024, 9, 9)))
        self.assertIn('- 次回来院日 2024-09-09(90日後)', to_markdown(report))

    def test_report_name_mode(self):
        make_sample(self.db)
        both = to_markdown(make_report(self.db, today='2024-06-11'))
        self.assertIn('| A(A-generic) | 2 |', both)
        rep = to_markdown(make_report(self.db, today='2024-06-11',
                                      name_mode='representative'))
        self.assertIn('| 代表目薬名 | 必要本数 |', rep)
        self.assertNotIn('A-generic', rep)
        act = to_markdown(make_report(self.db, today='2024-06-11',
                                      name_mode='actual'))
        self.assertIn('| 目薬名 | 必要本数 |', act)
        self.assertIn('- A-generic: 通常期間', act)
        with self.assertRaises(ValueError):
            make_report(self.db, name_mode='bad')

    def test_report_as_needed_and_info(self):
        make_sample(self.db)
        self.db.add_drug('ヒアレイン', as_needed=True)
        self.db.receive('ヒアレイン', 2, '2024-01-01')
        self.db.update_drug('A', max_days=28)
        report = make_report(self.db, today='2024-07-05', span=60)
        text = to_markdown(report)
        # 目薬在庫の表: 随時使用は含めない
        table = text.split('## 目薬在庫')[1].split('## 推定の根拠')[0]
        # 7/5 時点 34日経過、推定30日 -> 超過4日
        self.assertIn('| A | 1 | 6/1 | 34 | 超過4日 | 31 |', table)
        self.assertIn('| B | 2 |  |  |  |  |', table)
        self.assertNotIn('ヒアレイン', table)
        self.assertIn('| ヒアレイン | 随時 |  |  | 2 |  |  |', text)
        self.assertIn('- [info] A(A-generic): 開封から34日経過。'
                      '廃棄期限(4週間)を過ぎています', text)
        self.assertNotIn('[警告]', text)

    def test_opened_text_label(self):
        from drugdb.report import opened_text
        make_sample(self.db)
        req = self.db.requirement('A', span=60, today='2024-06-11')
        self.assertIn(' 推定残り約20日', opened_text(req))
        self.assertIn(' 残り約20日', opened_text(req, '残り'))

    def test_report_no_prescription_limit(self):
        self.db.add_drug('A')
        self.db.add_lifetime('A', '2024-01-01', '2024-01-11')  # 10日/本
        report = make_report(self.db, today='2024-06-11', span=60)
        text = to_markdown(report)
        # 上限なし: 60 / 10 = 6本 + 予備1
        self.assertIn('| A | 7 | 60 | 0 | 0 | 10 | 0 |', text)
        self.assertNotIn('[警告]', text)
        self.assertNotIn('不足', text)

    def test_report_until(self):
        make_sample(self.db)
        report = make_report(self.db, today='2024-06-11',
                             next_visit='2024-07-11')
        self.assertEqual(report.span, 30)

    def test_markdown_table_escape(self):
        self.db.add_drug('A|B')
        text = to_markdown(make_report(self.db, today='2024-06-11'))
        self.assertIn('| A\\|B | 相談 |  |  | 0 |', text)


class TestRollover(DbTestCase):
    """rollover.py"""

    def test_rollover(self):
        self.db.add_drug('A')
        self.db.inventory('A', 2, '2023-02-01')
        self.db.receive('A', 6, '2023-06-01')
        days = ['2023-02-01', '2023-03-03', '2023-04-02', '2023-05-02',
                '2023-05-05', '2023-06-04', '2023-07-04', '2024-01-19']
        for day in days:
            self.db.open_bottle('A', day)
        self.db.receive('A', 2, '2024-01-10')
        before = self.db.balance('A')
        result = rollover(self.db, 2024, self.path / 'archive',
                          today=date(2024, 7, 1))
        self.assertTrue(result.backup.exists())
        with (result.export_dir / 'stock.csv').open(encoding='utf-8') as f:
            self.assertEqual(len(list(csv.reader(f))) - 1,
                             result.stock_archived)
        self.assertEqual(self.db.balance('A'), before)
        history = self.db.stock_history('A')
        self.assertEqual(history[0]['stock_date'], '2023-12-31')
        self.assertEqual(history[0]['kind'], 'inventory')
        self.assertEqual(result.carried, {'A': 2 + 6 - 7})
        # 2023年に終了したもののうち、直近3回の実績(05-05, 06-04, 07-04 開封)
        # より前の4本だけ退避
        self.assertEqual(result.lifetime_archived, 4)
        self.assertEqual([r['use_start'] for r in self.db.lifetimes('A')],
                         ['2023-05-05', '2023-06-04', '2023-07-04',
                          '2024-01-19'])
        # 3日の極端に短いものは過去年値に含めない
        summary = self.db.summaries('A')[0]
        self.assertEqual((summary['year'], summary['count']), (2023, 3))
        self.assertEqual(summary['min_days'], 30)

    def test_rollover_keeps_recent(self):
        # 年明けすぐに実行しても直近3回分の実績は残る
        self.db.add_drug('A')
        self.db.receive('A', 20, '2025-01-01')
        days = [f'2025-{m:02d}-01' for m in range(1, 13)] + ['2025-12-31']
        for day in days:
            self.db.open_bottle('A', day)
        est = self.db.estimate('A')
        result = rollover(self.db, 2026, self.path / 'k',
                          today=date(2026, 1, 3))
        rows = self.db.lifetimes('A')
        # 直近3回の実績(10/01, 11/01, 12/01 開封)以降は区切り前でも残る
        self.assertEqual([r['use_start'] for r in rows],
                         ['2025-10-01', '2025-11-01', '2025-12-01',
                          '2025-12-31'])
        self.assertEqual(result.lifetime_archived, 9)
        self.assertEqual(self.db.estimate('A').days, est.days)
        self.assertEqual(self.db.estimate('A').samples, est.samples)
        # 過去年値には退避した分だけ(残した分は二重に数えない)
        self.assertEqual(self.db.summaries('A')[0]['count'], 9)
        self.assertEqual(self.db.balance('A'), 20 - 13)

    def test_rollover_keeps_fewer_when_few(self):
        self.db.add_drug('A')
        self.db.add_lifetime('A', '2025-01-01', '2025-02-01')   # 1回だけ
        rollover(self.db, 2026, self.path / 'f', today=date(2026, 1, 3))
        self.assertEqual(len(self.db.lifetimes('A')), 1)
        self.assertEqual(self.db.estimate('A').days, 31)
        self.db.add_drug('B')
        self.db.add_lifetime('B', '2025-01-01', '2025-01-10', irregular=True)
        rollover(self.db, 2026, self.path / 'g', today=date(2026, 1, 3))
        # 実績0(イレギュラーのみ)なら区切りどおり退避、推定は実績なし
        self.assertEqual(self.db.lifetimes('B'), [])
        self.assertIsNone(self.db.estimate('B').days)

    def test_rollover_merges_summary(self):
        self.db.add_drug('A')
        for start, end in (('2023-01-01', '2023-01-31'),
                           ('2023-01-31', '2023-03-12'),
                           ('2023-03-12', '2023-04-11'),
                           ('2023-04-11', '2023-05-11')):
            self.db.add_lifetime('A', start, end)
        # 1回目: 直近3回を残して 01-01 開封(30日)だけ退避
        rollover(self.db, 2024, self.path / 'a1', today=date(2024, 1, 5))
        self.assertEqual(self.db.summaries('A')[0]['count'], 1)
        self.db.add_lifetime('A', '2023-05-11', '2023-06-10')
        self.db.add_lifetime('A', '2023-06-10', '2023-07-10')
        # 2回目: 01-31 開封(40日)と 03-12 開封(30日)を退避して 2023年に合算
        rollover(self.db, 2025, self.path / 'a2', today=date(2025, 1, 5))
        summary = self.db.summaries('A')[0]
        self.assertEqual((summary['year'], summary['count'],
                          round(summary['avg_days'], 2),
                          summary['max_days']), (2023, 3, 33.33, 40))
        self.assertEqual(len(self.db.lifetimes('A')), 3)


class TestCli(DbTestCase):
    """cli.py"""

    def run_cmd(self, line):
        out = io.StringIO()
        shell = DrugDbShell(self.db, stdout=out)
        with redirect_stderr(io.StringIO()) as err:
            shell.onecmd(line)
        return out.getvalue(), err.getvalue(), shell.failed

    def test_help_lists_flags(self):
        out = self.run_cmd('help')[0]
        self.assertIn('各サブコマンドの詳しいヘルプは -h', out)
        self.assertIn('drugs      薬の一覧  [-a]', out)
        detail = self.run_cmd('help drugs')[0]
        self.assertIn('-a, --all', detail)

    def test_parse_error_shows_subcommand_help(self):
        out, err, failed = self.run_cmd('drugs help')
        self.assertTrue(failed)
        self.assertIn('unrecognized arguments', err)
        self.assertIn('usage: drugs', out)
        self.assertIn('-a, --all', out)
        # 実行時のエラー(構文は正しい)ではヘルプを付けない
        out, err, failed = self.run_cmd('in 無い薬 1')
        self.assertTrue(failed)
        self.assertIn('薬が見つかりません', err)
        self.assertNotIn('usage:', out)

    def test_commands(self):
        self.assertFalse(self.run_cmd('add A -d 2024-01-01')[2])
        self.run_cmd('in A 3 -d 2024-01-01')
        self.run_cmd('open A -d 2024-01-01')
        out, _, failed = self.run_cmd('open A -d 2024-01-31 -m "2本目"')
        self.assertFalse(failed)
        self.assertIn('在庫: 1', out)
        out = self.run_cmd('life A')[0]
        self.assertIn('2024-01-01 〜 2024-01-31  30日', out)
        out = self.run_cmd('report -v 2024-02-10 -n 60')[0]
        self.assertIn('## 次回来院までに必要な本数', out)
        self.assertIn('- 来院日 2024-02-10', out)
        self.assertIn('- 次回来院日 2024-04-10(60日後)', out)
        out = self.run_cmd('report --visit 2024-02-10 --next 2024-03-09'
                           ' --plain')[0]
        self.assertIn('次回来院日 2024-03-09(28日後)', out)
        self.assertIn('■ 次回来院までに必要な本数', out)
        self.assertNotIn('| ', out)
        out, err, failed = self.run_cmd('report -v 2024-02-10 -n 2024-02-01')
        self.assertTrue(failed)
        self.assertIn('来院日 2024-02-10 より後の日付', err)
        self.assertTrue(self.run_cmd('report -n 2年')[2])

    def test_visit_next_interval(self):
        out = io.StringIO()
        shell = DrugDbShell(self.db, stdout=out)

        def run(line):
            out.seek(0)
            out.truncate()
            with redirect_stderr(io.StringIO()) as err:
                shell.onecmd(line)
            return out.getvalue() + err.getvalue()

        today = date.today()
        self.assertIn(f'来院日 {today}(今日)', run('visit'))
        self.assertIn('(既定: 2ヶ月後)', run('next'))
        text = run('visit 2024-02-10')
        self.assertIn('来院日 2024-02-10\n', text)
        self.assertIn('次回来院日 2024-04-10(60日後)(既定: 2ヶ月後)', text)
        self.assertIn('次回来院日 2024-03-09(28日後)\n', run('next 4週間'))
        self.assertIn('次回来院日 2024-03-01(20日後)', run('next 2024-03-01'))
        self.assertIn('より後の日付', run('next 2024-02-01'))
        self.assertIn('2024-03-01', run('next'))        # 変わらない
        # report は visit・next の設定を使う(引数があればそちら)
        self.assertIn('- 次回来院日 2024-03-01(20日後)', run('report'))
        self.assertIn('- 来院日 2024-02-20', run('report -v 2024-02-20'))
        self.assertIn('次回来院日の既定: 来院日の8週間後(56日後)',
                      run('interval 8週間'))
        self.assertIn('次回来院日 2024-04-06(56日後)(既定: 8週間後)',
                      run('next -r'))
        self.assertIn(f'来院日 {today}(今日)', run('visit -r'))

    def test_endname(self):
        self.run_cmd('add ヒアレイン')
        self.run_cmd('alias ヒアレイン ヒアルロン酸 -d 2022-10-20')
        self.assertFalse(self.run_cmd('endname ヒアレイン ヒアルロン酸'
                                      ' -d 2025-06-30')[2])
        out = self.run_cmd('show ヒアレイン')[0]
        self.assertIn('目薬名: 2022-10-20〜2025-06-30 ヒアルロン酸', out)
        self.assertEqual(self.run_cmd('drugs')[0], '')
        self.assertIn('目薬名がすべて利用終了', self.run_cmd('drugs -a')[0])
        self.run_cmd('endname ヒアレイン ヒアルロン酸 --clear')
        self.assertIn('ヒアレイン', self.run_cmd('drugs')[0])

    def test_errors(self):
        _, err, failed = self.run_cmd('in 無い薬 1')
        self.assertTrue(failed)
        self.assertIn('薬が見つかりません', err)
        _, err, failed = self.run_cmd('in')
        self.assertTrue(failed)
        _, err, failed = self.run_cmd('in A 1 -d 2024-13-01')
        self.assertTrue(failed)
        _, err, failed = self.run_cmd('bogus')
        self.assertTrue(failed)

    def test_main_one_shot(self):
        db_file = str(self.path / 'main.db')
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['-f', db_file, '--create', 'add', 'X']), 0)
            self.assertEqual(main(['-f', db_file, 'in', 'Y', '1']), 1)

    def test_main_missing_file_errors(self):
        db_file = str(self.path / 'missing.db')
        with redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit):
                main(['-f', db_file, 'drugs'])
        self.assertIn('見つかりません', err.getvalue())
        self.assertFalse(Path(db_file).exists())

    def test_main_default_file_auto_creates(self):
        db_file = str(self.path / 'auto.db')
        with mock.patch.object(cli, 'DEFAULT_DB', Path(db_file)), \
                redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['add', 'X']), 0)
        self.assertTrue(Path(db_file).exists())


class TestImportSheet(DbTestCase):
    """import_ods.py with synthetic sheet"""

    def test_date_warnings(self):
        def row(*values):
            return [Cell('' if v is None else str(v), v) for v in values]
        header = row('登録名(ID)', '現在の薬の名前', '現在の名前利用開始日',
                     None, '開封日', '(終了日)', None, None, '日付', '入庫数',
                     '出庫数', '棚卸?', '残高')
        pad = (None,) * 8
        rows = [row('名称'), header,
                row('X', 'X', date(2024, 1, 1)) + row(None) * 5
                + row(date(2024, 1, 1), None, None, 'Yes', 1.0),
                row(*pad, date(2099, 1, 1), None, 1.0, None, 0.0),
                row(*pad, date(2024, 2, 1), 2.0, None, None, 2.0)]
        result = import_sheet(self.db, 'X', rows)
        self.assertEqual(result.stocks, 3)
        self.assertEqual(result.warnings,
                         ['在庫の日付が未来: 2099-01-01',
                          '在庫の日付順が逆: 2099-01-01 の次に 2024-02-01'])
        self.assertEqual(len(result.mismatches), 1)


@unittest.skipUnless(ODS.exists(), 'ods not found')
class TestImportOds(DbTestCase):
    """import_ods.py with real spreadsheet"""

    def test_import(self):
        results = {r.name: r for r in import_ods(self.db, ODS)}
        self.assertIn('コソプト', results)
        # 残高不一致は日付異常(要確認)があるシートでだけ起きる
        for result in results.values():
            if result.mismatches:
                self.assertNotEqual(result.warnings, [], result.name)
        self.assertEqual(self.db.current_name('キサラタン'), 'ラタノプロスト')
        self.assertEqual(self.db.find_drug('ドルモロール')['name'], 'コソプト')
        self.assertIsNotNone(results['リンデロン'].ended)
        irregular = [r for r in self.db.lifetimes('グラナテック')
                     if r['irregular']]
        self.assertEqual([r['note'] for r in irregular], ['中断→', '再開→'])
        # 2回目は取り込み済としてスキップ
        self.assertEqual(import_ods(self.db, ODS), [])


if __name__ == '__main__':
    unittest.main()
