# -*- coding: utf-8 -*-
"""tests for mobile app (build screens without device)

JP:
スマホ版のテスト。端末無しで画面部品の組み立てまでを確認する。
flet が入っていなければスキップ。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import flet as ft
except ImportError:  # pragma: no cover
    ft = None

from drugdb.backup import (backup_bytes, backup_file_name, check_backup,
                           restore_bytes)
from drugdb.drugdb import DrugDb, DrugDbError

MOBILE_SRC = Path(__file__).resolve().parent.parent / 'mobile' / 'src'


class TestBackup(unittest.TestCase):
    """drugdb/backup.py"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_backup_and_restore(self):
        with DrugDb(str(self.path / 'a.db')) as db:
            db.add_drug('A')
            db.receive('A', 3, '2026-01-01')
            data = backup_bytes(db)
        self.assertEqual(check_backup(data), 1)
        target = self.path / 'b.db'
        with DrugDb(str(target)) as db:
            db.add_drug('X')
            db.add_drug('Y')
        self.assertEqual(restore_bytes(data, target), 1)
        self.assertTrue((self.path / 'b.db.before-restore').exists())
        with DrugDb(str(target)) as db:
            self.assertEqual([r['name'] for r in db.list_drugs()], ['A'])
            self.assertEqual(db.balance('A'), 3)

    def test_reject_invalid(self):
        with self.assertRaises(DrugDbError):
            check_backup(b'not a database')
        other = self.path / 'other.db'
        import sqlite3
        conn = sqlite3.connect(other)
        conn.execute('CREATE TABLE t (x)')
        conn.commit()
        conn.close()
        with self.assertRaises(DrugDbError):
            check_backup(other.read_bytes())
        # 検査に落ちたら置き換えない
        target = self.path / 'keep.db'
        target.write_bytes(b'keep')
        with self.assertRaises(DrugDbError):
            restore_bytes(b'bad', target)
        self.assertEqual(target.read_bytes(), b'keep')

    def test_file_name(self):
        from datetime import date
        self.assertEqual(backup_file_name(date(2026, 9, 25)),
                         'eyedrop-backup-20260925.db')


@unittest.skipIf(ft is None, 'flet not installed')
class TestMobileScreens(unittest.TestCase):
    """mobile/src/main.py screens"""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(MOBILE_SRC))
        import main  # pylint: disable=import-outside-toplevel
        cls.main = main

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / 'eyedrop.db'
        self.app = self.main.EyedropApp(None, self.db_path)
        db = self.app.db
        db.add_drug('A', '2026-01-01', max_days=28)
        db.add_alias('A', 'A-generic', '2026-02-01')
        db.receive('A', 3, '2026-01-01')
        for day in ('2026-01-01', '2026-01-31', '2026-03-01'):
            db.open_bottle('A', day)
        db.set_irregular(db.lifetimes('A')[0]['lifetime_id'])
        db.add_drug('C', as_needed=True)
        db.receive('C', 2, '2026-01-01')

    def tearDown(self):
        self.app.db.close()
        self.tmp.cleanup()

    def texts(self, controls) -> str:
        """collect Text values recursively"""
        out = []

        def walk(obj):
            if isinstance(obj, ft.Text):
                out.append(str(obj.value))
            for name in ('content', 'title', 'subtitle', 'label'):
                child = getattr(obj, name, None)
                if isinstance(child, ft.Control):
                    walk(child)
            for name in ('controls', 'rows', 'cells', 'columns'):
                for child in getattr(obj, name, None) or []:
                    walk(child)
        for control in controls:
            walk(control)
        return '\n'.join(out)

    def test_database_path(self):
        env = {'EYEDROP_DB': '', 'FLET_APP_STORAGE_DATA': '/data/app'}
        old = {k: os.environ.get(k) for k in env}
        try:
            os.environ.update(env)
            self.assertEqual(self.main.database_path(),
                             Path('/data/app/eyedrop.db'))
            os.environ['EYEDROP_DB'] = '/tmp/x.db'
            self.assertEqual(self.main.database_path(), Path('/tmp/x.db'))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_summary(self):
        controls = self.app.build_summary()
        text = self.texts(controls)
        self.assertIn('来院時必要本数', text)
        self.assertIn('目薬在庫', text)
        self.assertIn('随時', text)
        # コピーはハンバーガーメニューへ移したので画面には無い
        self.assertNotIn('をコピー', text)
        menu = self.texts(self.app.build_topbar().leading.items)
        self.assertIn('Markdown をコピー\n(Web用)', menu)
        self.assertIn('テキストをコピー\n(アプリ用)', menu)
        # 目薬在庫: 経過なし、残日数・通常日数。値の短い列は見出し2段
        tables = [c.controls[0].content for c in controls
                  if isinstance(c, ft.Row) and c.controls
                  and isinstance(getattr(c.controls[0], 'content', None),
                                 ft.DataTable)]
        heads = [[col.label.value for col in t.columns] for t in tables]
        self.assertEqual(heads[0][1:], ['未\n開封', '2ヶ月', '1ヶ月\n(4週間)',
                                        '2週間'])
        self.assertEqual(heads[1][1:], ['未\n開封', '開封日', '残\n日数',
                                        '通常\n日数'])
        self.assertGreater(tables[1].heading_row_height, self.app.size(2.4))

    def test_drugs(self):
        text = self.texts(self.app.build_drugs())
        # 既定は代表名
        self.assertIn('A\n', text)
        self.assertNotIn('A-generic', text)
        self.assertIn('未開封 0本', text)
        self.assertIn('随時使用', text)
        self.assertIn('開封', text)

    def test_name_mode(self):
        drug_id = self.app.db.find_drug('A')['drug_id']
        self.assertEqual(self.app.name_mode, 'representative')
        self.assertEqual(self.app.drug_label(drug_id), 'A')
        summary = self.texts(self.app.build_summary())
        self.assertIn('代表名', summary)
        self.assertNotIn('A-generic', summary)
        # 画面内一斉切替: 実際に支給される名前
        self.app.set_name_mode('actual')
        self.assertEqual(self.app.drug_label(drug_id), 'A-generic')
        summary = self.texts(self.app.build_summary())
        self.assertIn('実際の名前', summary)
        self.assertIn('A-generic', summary)
        self.assertIn('A-generic', self.texts(self.app.build_drugs()))
        # 共有する Markdown も切り替わる
        from drugdb.report import to_markdown
        self.assertIn('| A-generic |', to_markdown(self.app.report()))
        # 詳細では両方を表示
        detail = self.texts(self.app.build_detail(drug_id))
        self.assertIn('代表名: A', detail)
        self.assertIn('実際の名前: A-generic (2026-02-01〜)', detail)
        menu = self.app.build_topbar().leading
        self.assertEqual([i.checked for i in menu.items[:2]], [False, True])

    def test_detail(self):
        drug_id = self.app.db.find_drug('A')['drug_id']
        text = self.texts(self.app.build_detail(drug_id))
        self.assertIn('開封の履歴', text)
        self.assertIn('(イレギュラー)', text)
        self.assertIn('使用中', text)
        self.assertIn('在庫の履歴', text)

    def test_data_and_font_scale(self):
        text = self.texts(self.app.build_data())
        self.assertIn('バックアップ', text)
        self.assertIn('年次更新', text)
        self.assertEqual(self.app.size(), 18)
        self.app.db.set_meta('font_scale', '1.5')
        self.assertEqual(self.app.size(), 27)
        # 以前の設定値(特大)も読める
        self.app.db.set_meta('font_scale', '特大')
        self.assertEqual(self.app.size(), 27)

    def test_change_font(self):
        self.assertEqual(self.app.scale, 1.0)
        # 既定より小さくできる(最小 75%)
        self.app.change_font(-1)
        self.assertEqual(self.app.scale, 0.9)
        for _ in range(5):
            self.app.change_font(-1)
        self.assertEqual(self.app.scale, 0.75)
        self.assertEqual(self.texts(self.app.build_topbar().actions)
                         .count('75%'), 1)
        # 倍率表示のタップで既定に戻る
        self.app.reset_font()
        self.assertEqual(self.app.scale, 1.0)
        for _ in range(10):
            self.app.change_font(1)
        self.assertEqual(self.app.scale, 2.5)  # 最大
        self.app.change_font(-1)
        self.assertEqual(self.app.scale, 2.0)
        bar = self.app.build_topbar()
        labels = self.texts(bar.actions)
        self.assertIn('A－', labels)
        self.assertIn('200%', labels)
        self.assertIn('A＋', labels)

    def test_empty_database(self):
        empty = self.main.EyedropApp(None, Path(self.tmp.name) / 'e.db')
        try:
            controls = empty.build_summary()
            self.assertIn('目薬が登録されていません', self.texts(controls))
            # データが無くても表(枠線付き)に空の行が1行ある
            tables = [c.controls[0].content for c in controls
                      if isinstance(c, ft.Row) and c.controls
                      and isinstance(getattr(c.controls[0], 'content', None),
                                     ft.DataTable)]
            self.assertEqual(len(tables), 2)
            for table in tables:
                self.assertEqual(len(table.rows), 1)
                self.assertIsNotNone(table.border)
                self.assertIsNotNone(table.vertical_lines)
            self.assertIn('+ で目薬を追加',
                          self.texts(empty.build_drugs()))
        finally:
            empty.db.close()


if __name__ == '__main__':
    unittest.main()
