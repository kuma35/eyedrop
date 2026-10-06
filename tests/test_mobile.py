# -*- coding: utf-8 -*-
"""tests for mobile app (build screens without device)

JP:
スマホ版のテスト。端末無しで画面部品の組み立てまでを確認する。
flet が入っていなければスキップ。
"""
import os
from datetime import date, timedelta
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
            for name in ('content', 'title', 'subtitle', 'label',
                         'trailing'):
                child = getattr(obj, name, None)
                if isinstance(child, ft.Control):
                    walk(child)
            for name in ('controls', 'rows', 'cells', 'columns'):
                for child in getattr(obj, name, None) or []:
                    walk(child)
        for control in controls:
            walk(control)
        return '\n'.join(out)

    def test_open_note(self):
        open_note = self.main.open_note
        self.assertIn('みてた(空になった)', open_note(True, True))
        self.assertNotIn('みてた', open_note(False, True))
        self.assertIn('在庫が0本', open_note(True, False))

    def test_undo_open(self):
        drug_id = self.app.db.find_drug('A')['drug_id']
        self.assertIn('開封の取り消し',
                      self.texts(self.app.build_detail(drug_id)))
        self.app.run(lambda: self.app.db.undo_open(drug_id))
        self.assertEqual(self.app.db.opened('A')['use_start'], '2026-01-31')

    def test_picked_date(self):
        from datetime import date, datetime, timedelta, timezone
        picked_date = self.main.picked_date
        jst = timezone(timedelta(hours=9))
        # 日本時間 6/30 0時が UTC(6/29 15時)で返っても 6/30
        self.assertEqual(picked_date(datetime(2025, 6, 29, 15, 0,
                                              tzinfo=timezone.utc)),
                         date(2025, 6, 30))
        self.assertEqual(picked_date(datetime(2025, 6, 29, 15, 0)),
                         date(2025, 6, 30))
        self.assertEqual(picked_date(datetime(2025, 6, 30, tzinfo=jst)),
                         date(2025, 6, 30))
        self.assertEqual(picked_date(datetime(2025, 6, 30)),
                         date(2025, 6, 30))
        # 西側の時間帯(UTC-5 の 6/30 0時 = UTC 6/30 5時)
        self.assertEqual(picked_date(datetime(2025, 6, 30, 5, 0,
                                              tzinfo=timezone.utc)),
                         date(2025, 6, 30))
        self.assertEqual(picked_date(date(2025, 6, 30)), date(2025, 6, 30))
        self.assertIsNone(picked_date(None))

    def test_fix_stale_on_start(self):
        path = Path(self.tmp.name) / 'stale.db'
        with DrugDb(str(path)) as db:
            db.add_drug('S')
            db.add_lifetime('S', '2022-11-20')
            db.add_lifetime('S', '2026-08-20')
        app = self.main.EyedropApp(None, path)
        try:
            self.assertEqual(len(app.fixed_stale), 1)
            self.assertEqual(app.db.lifetimes('S')[0]['use_end'],
                             '2026-08-20')
        finally:
            app.db.close()

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
        self.assertIn('次回来院までに必要な本数', text)
        self.assertIn('目薬在庫', text)
        self.assertIn('随時', text)
        # コピーはハンバーガーメニューへ移したので画面には無い
        self.assertNotIn('をコピー', text)
        menu = self.texts(self.app.build_topbar().leading.items)
        self.assertIn('サマリーを\nMarkdown でコピー', menu)
        self.assertIn('サマリーを\nテキストでコピー', menu)
        self.assertIn('サマリーを\nチャットAI用にコピー', menu)
        # 目薬在庫: 経過なし、残日数・通常日数。値の短い列は見出し2段
        tables = [c.controls[0].content for c in controls
                  if isinstance(c, ft.Row) and c.controls
                  and isinstance(getattr(c.controls[0], 'content', None),
                                 ft.DataTable)]
        heads = [[col.label.value for col in t.columns] for t in tables]
        self.assertEqual(heads[0][1:], ['必要\n本数', '足りない\n日数',
                                        '在庫\n残日数',
                                        '未\n開封', '通常\n期間',
                                        '開封分\n残日数'])
        self.assertEqual(heads[1][1:], ['未\n開封', '開封日', '残\n日数',
                                        '通常\n日数'])
        self.assertGreater(tables[1].heading_row_height, self.app.size(2.4))

    def test_drugs(self):
        text = self.texts(self.app.build_drugs())
        # 既定は代表目薬名
        self.assertIn('A\n', text)
        self.assertNotIn('A-generic', text)
        self.assertIn('未開封 0本', text)
        self.assertIn('随時使用', text)
        self.assertIn('開封(出庫)', text)
        # 代表目薬名ごとの利用終了は目薬タブのカードにある
        self.assertIn('利用終了', text)

    def test_bulk_inventory(self):
        app = self.app
        db = app.db
        a_id = db.find_drug('A')['drug_id']
        c_id = db.find_drug('C')['drug_id']
        menu = app.build_topbar().leading
        self.assertIn('一括棚卸し', self.texts(menu.items))
        app.tab = 1
        app.show_bulk_inventory()
        text = self.texts(app.build_bulk_inventory())
        self.assertIn('一括棚卸し', text)
        self.assertIn('記録上 0本(同じ)', text)
        self.assertIn('記録上 2本(同じ)', text)
        self.assertIn('記録(2件)', text)
        self.assertIn('一括棚卸しコメント', text)
        self.assertEqual(app.bulk['counts'], {a_id: 0, c_id: 2})
        # 「＋」「－」は行だけ更新し、0本より減らさない
        card = app.bulk_row(c_id, 2)
        plus = card.content.content.controls[2].controls[2]
        minus = card.content.content.controls[2].controls[0]
        plus.on_click(None)
        self.assertEqual(app.bulk['counts'][c_id], 3)
        self.assertIn('記録上 2本 → 3本に修正', self.texts([card]))
        for _ in range(5):
            minus.on_click(None)
        self.assertEqual(app.bulk['counts'][c_id], 0)
        self.assertTrue(minus.disabled)
        app.bulk['counts'][c_id] = 1
        # 作り直しても入力中の本数は残る
        controls = app.build_bulk_inventory()
        self.assertIn('記録上 2本 → 1本に修正', self.texts(controls))
        record = controls[-1].controls[0]
        record.on_click(None)
        # 記録するとサマリーへ
        self.assertIsNone(app.bulk)
        self.assertEqual(app.tab, 0)
        self.assertEqual(db.balance('C'), 1)
        self.assertEqual(db.stock_history('A')[-1]['kind'], 'inventory')
        # 日付を変えると本数はその日の記録上の本数に戻る
        app.show_bulk_inventory(date(2025, 12, 31))
        app.bulk['counts'][c_id] = 5
        app.set_bulk_date(date(2026, 1, 1))
        self.assertEqual(app.bulk['counts'][c_id], 2)
        # 文字を大きくしても「－」「＋」と本数は BULK_MAX_SCALE で頭打ち
        app.db.set_meta('font_scale', '2.5')
        row = app.bulk_row(c_id, 2).content.content.controls[2]
        app.db.set_meta('font_scale', '1.5')
        same = app.bulk_row(c_id, 2).content.content.controls[2]
        self.assertEqual(row.controls[0].content.size,
                         same.controls[0].content.size)
        self.assertEqual(row.controls[1].width, same.controls[1].width)
        app.db.set_meta('font_scale', '1.0')
        small = app.bulk_row(c_id, 2).content.content.controls[2]
        self.assertLess(small.controls[0].content.size,
                        same.controls[0].content.size)
        # やめると何も記録せず元の画面へ
        app.build_bulk_inventory()[0].controls[0].on_click(None)
        self.assertIsNone(app.bulk)
        self.assertEqual(db.balance('C'), 1)

    def test_name_mode(self):
        drug_id = self.app.db.find_drug('A')['drug_id']
        self.assertEqual(self.app.name_mode, 'representative')
        self.assertEqual(self.app.drug_label(drug_id), 'A')
        summary = self.texts(self.app.build_summary())
        self.assertIn('代表目薬名', summary)
        self.assertNotIn('A-generic', summary)
        # 画面内一斉切替: 実際に支給される名前
        self.app.set_name_mode('actual')
        self.assertEqual(self.app.drug_label(drug_id), 'A-generic')
        summary = self.texts(self.app.build_summary())
        self.assertIn('目薬名', summary)
        self.assertIn('A-generic', summary)
        self.assertIn('A-generic', self.texts(self.app.build_drugs()))
        # 共有する Markdown も切り替わる
        from drugdb.report import to_markdown
        self.assertIn('| A-generic |', to_markdown(self.app.report()))
        # 詳細では両方を表示
        detail = self.texts(self.app.build_detail(drug_id))
        self.assertIn('代表目薬名: A', detail)
        self.assertIn('目薬名:\nA-generic\n2026-02-01〜利用中', detail)
        menu = self.app.build_topbar().leading
        self.assertEqual([i.checked for i in menu.items[:2]], [False, True])

    def test_alias_end_and_ended_drugs(self):
        db = self.app.db
        drug_id = db.find_drug('C')['drug_id']
        db.add_alias('C', 'C-actual', '2022-10-20')
        db.end_alias('C', 'C-actual', '2025-06-30')
        # 目薬名がすべて利用終了 → サマリー・目薬タブに出ない
        self.assertNotIn('C\n', self.texts(self.app.build_drugs()))
        detail = self.texts(self.app.build_detail(drug_id))
        self.assertIn('利用終了 2025-06-30(目薬名がすべて利用終了)',
                      detail)
        self.assertIn('2022-10-20〜2025-06-30', detail)
        self.assertIn('利用中に戻す', detail)
        # 利用終了した目薬も表示
        self.app.set_show_ended(True)
        controls = self.app.build_drugs()
        switch = [c for c in controls if isinstance(c, ft.Switch)][0]
        self.assertEqual((switch.label, switch.value),
                         ('利用終了した目薬も表示', True))
        drugs = self.texts(controls)
        self.assertIn('利用終了 2025-06-30', drugs)
        # 利用終了した目薬のカードに「利用中に戻す」(取り消し)
        self.assertIn('利用中に戻す', drugs)
        # 詳細画面には代表目薬名ごとの利用終了ボタンは無い
        detail_a = self.texts(self.app.build_detail(
            db.find_drug('A')['drug_id']))
        self.assertIn('廃棄期限設定', detail_a)
        # 「目薬を追加」は目薬名リストの末尾(A-generic の直下)
        self.assertIn('A-generic\n2026-02-01〜利用中\n利用終了する\n目薬を追加',
                      detail_a)
        # 長いラベルは折り返せるよう Text として並べる
        self.assertIn('随時(必要時・頓用;頓服風に使用)', detail_a)
        self.assertEqual(detail_a.count('利用終了'), 1)   # 目薬名の右だけ
        self.assertNotIn('推奨期限', detail_a)

    def test_memo_value(self):
        field = self.app.memo_field()
        self.assertIsNone(self.main.memo_value(field))
        field.value = '  '
        self.assertIsNone(self.main.memo_value(field))
        field.value = ' 消費期限2027.6 '
        self.assertEqual(self.main.memo_value(field), '消費期限2027.6')
        # コメントは在庫の履歴に出る
        db = self.app.db
        db.receive('A', 2, '2026-09-24', self.main.memo_value(field))
        detail = self.texts(self.app.build_detail(
            db.find_drug('A')['drug_id']))
        self.assertIn('消費期限2027.6', detail)

    def test_remaining_label(self):
        db = self.app.db
        db.add_drug('R')
        db.add_lifetime('R', '2026-01-01', '2026-01-31')   # 30日/本
        db.add_lifetime('R', date.today().isoformat())      # 今日開封
        text = self.texts(self.app.build_drugs())
        self.assertIn('推定残り約30日', text)
        drug_id = db.find_drug('R')['drug_id']
        detail = self.texts(self.app.build_detail(drug_id))
        self.assertIn('推定残り約30日', detail)

    def test_todo_labels_and_spans(self):
        from drugdb.report import get_default_span
        # 目薬タブの先頭に「目薬追加」(フロートボタンは無い)
        controls = self.app.build_drugs()
        first = controls[0]
        self.assertIsInstance(first, (ft.FilledButton, ft.OutlinedButton))
        self.assertEqual(first.content.value, '目薬追加')
        # サマリーの説明文
        text = self.texts(self.app.build_summary())
        self.assertIn('足りない日数：次回来院日までの日数−在庫残日数', text)
        self.assertIn('開封日：現在使っている目薬を開封した日。', text)
        self.assertIn('通常日数：この目薬は通常何日で使い切っているか', text)
        # 設定タブで次回来院日の既定の期間を設定
        data = self.app.build_data()
        rows = [top.controls for top in data if isinstance(top, ft.Row)
                and top.controls and isinstance(top.controls[0], ft.TextField)]
        self.assertEqual([(r[0].value, r[1].value) for r in rows],
                         [('2', 'ヶ月')])
        self.app.db.set_meta('spans', '90')
        self.assertEqual(get_default_span(self.app.db), 90)
        today = date.today()
        self.assertIn(f'次回来院日 {today + timedelta(days=90)}(90日後)',
                      self.texts(self.app.build_summary()))

    def test_summary_dates(self):
        today = date.today()
        text = self.texts(self.app.build_summary())
        self.assertIn(f'来院日 {today}', text)
        self.assertIn(f'次回来院日 {today + timedelta(days=60)}(60日後)', text)
        self.assertNotIn('今日に戻す', text)
        # 来院日を変えると次回来院日(既定)も動く
        self.app.set_visit_date(date(2024, 6, 11))
        text = self.texts(self.app.build_summary())
        self.assertIn('来院日 2024-06-11', text)
        self.assertIn('次回来院日 2024-08-10(60日後)', text)
        self.assertIn('今日に戻す', text)
        self.app.set_next_date(date(2024, 7, 9))
        text = self.texts(self.app.build_summary())
        self.assertIn('次回来院日 2024-07-09(28日後)', text)
        self.assertIn('既定(2ヶ月後)に戻す', text)
        self.assertIn('来院日 2024-06-11', self.app.report(summary=True)
                      .visit_text)
        # 目薬タブは今日時点のまま
        self.assertEqual(self.app.report().today, today)
        # 来院日以前の次回来院日は受け付けない
        self.app.set_next_date(date(2024, 6, 11))
        self.assertEqual(self.app.next_date, date(2024, 7, 9))
        # 来院日が次回来院日以降になったら次回来院日は既定に戻る
        self.app.set_visit_date(date(2024, 7, 9))
        self.assertIsNone(self.app.next_date)
        self.app.set_visit_date(None)
        self.assertEqual(self.app.summary_dates()[0], today)

    def test_detail(self):
        drug_id = self.app.db.find_drug('A')['drug_id']
        text = self.texts(self.app.build_detail(drug_id))
        self.assertIn('開封の履歴', text)
        self.assertIn('(イレギュラー)', text)
        self.assertIn('使用中', text)
        self.assertIn('在庫の履歴', text)
        # 開封の履歴は年付き(在庫の履歴と同じ形式)
        self.assertIn('2026-01-31 〜 2026-03-01  29日', text)
        # 履歴は閲覧のみ(削除の操作なし)。行は余白の少ない行(ListTile 不使用)
        self.assertNotIn('削除', text)

        def walk(obj):
            yield obj
            child = getattr(obj, 'content', None)
            if isinstance(child, ft.Control):
                yield from walk(child)
            for child in getattr(obj, 'controls', None) or []:
                yield from walk(child)
        found = [c for top in self.app.build_detail(drug_id)
                 for c in walk(top)]
        self.assertFalse(any(isinstance(c, (ft.ListTile, ft.IconButton))
                             and getattr(c, 'icon', None) == ft.Icons.DELETE
                             for c in found))

    def test_change_pattern(self):
        db = self.app.db
        drug_id = db.find_drug('A')['drug_id']
        self.assertIn('点眼パターン変更', self.texts(
            self.app.build_detail(drug_id)))
        # ダイアログの OK を押したことにする(page が無いので ask を差し替え)
        asked = {}
        self.app.ask = lambda title, controls, label, on_ok: asked.update(
            title=title, on_ok=on_ok)
        self.app.on_change_pattern(drug_id)
        self.assertEqual(asked['title'], 'A の点眼パターン変更')
        self.assertIn('直近の開封をイレギュラーにしました', asked['on_ok']())
        lives = db.lifetimes('A')
        self.assertEqual([r['irregular'] for r in lives], [1, 0, 1])
        self.assertTrue(lives[-1]['note'].startswith('点眼パターン変更('))
        detail = self.texts(self.app.build_detail(drug_id))
        self.assertIn(f'点眼パターン変更 {date.today()}', detail)
        self.assertIn('通常期間(1本あたり推定): 実績なし', detail)

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

    def test_tablet_default_scale(self):
        f = self.main.device_default_scale
        self.assertEqual(f(412, 915), 1.0)        # スマホ
        self.assertEqual(f(800, 1280), 1.5)       # タブレット(M40)
        self.assertEqual(f(1280, 800), 1.5)       # 横向き
        self.assertEqual(f(None, None), 1.0)
        # タブレットでは設定が無ければ 150% で始まる
        self.app.default_scale = 1.5
        self.assertEqual(self.app.scale, 1.5)
        # 変えたら覚える
        self.app.change_font(1)
        self.assertEqual(self.app.scale, 1.75)
        self.assertEqual(self.app.db.get_meta('font_scale'), '1.75')
        # 倍率タップで端末の既定(150%)に戻る
        self.app.reset_font()
        self.assertEqual(self.app.scale, 1.5)

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
            self.assertIn('「目薬追加」で目薬を登録',
                          self.texts(empty.build_drugs()))
        finally:
            empty.db.close()


if __name__ == '__main__':
    unittest.main()
