# -*- coding: utf-8 -*-
"""eyedrop mobile (Android) app

JP:
目薬管理 スマホ版(Flet)
========================

データは端末内で完結(スタンドアロン)。コア(在庫・推定・サマリー)は
drugdb パッケージを PC 版と共通で使います。

画面は下部のタブで切り替えます。

- サマリー: 来院時必要本数・目薬在庫の表。共有メニューで Markdown を送る
- 目薬: 開封・入庫・棚卸し。薬ごとの履歴と設定
- データ: バックアップ・復元・年次更新・文字サイズ・表示テーマ

目が悪くても見やすいよう、既定は黒地に白の高コントラストで文字は大きめ。
"""
import os
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

import flet as ft

from drugdb.backup import backup_bytes, backup_file_name, restore_bytes
from drugdb.backup import check_backup
from drugdb.drugdb import DrugDb, DrugDbError
from drugdb.report import (SPAN_PATTERNS, make_report, notices, opened_text,
                           pattern_cell, remaining_text, to_markdown)
from drugdb.rollover import rollover

APP_TITLE = '目薬管理'
DB_NAME = 'eyedrop.db'

# 来院時必要本数の表の列名(スマホの幅に収まるよう短く)
SHORT_SPAN_LABELS = {14: '2週間', 28: '4週間', 60: '2ヶ月'}

# 文字サイズの倍率(画面上部の A－ / A＋ で切り替え)
# 既定(DEFAULT_SCALE)より小さくもできる。倍率表示をタップすると既定に戻る
FONT_STEPS = (0.75, 0.9, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5)
DEFAULT_SCALE = 1.0
# 以前の設定値(ラジオボタン時代)からの読み替え
OLD_FONT_SCALES = {'標準': 1.0, '大': 1.25, '特大': 1.5}
BASE_SIZE = 18
# 上部バーの文字は倍率に関係なく固定(大きくしてもボタンがはみ出さない)
TOPBAR_SIZE = 22

# スクロールバー: 太く、常に表示、つまんで動かせる
SCROLLBAR_THICKNESS = 16

# 高コントラスト(黒地に白)
DARK_SCHEME = ft.ColorScheme(
    primary=ft.Colors.YELLOW_ACCENT, on_primary=ft.Colors.BLACK,
    secondary=ft.Colors.CYAN_ACCENT, on_secondary=ft.Colors.BLACK,
    surface=ft.Colors.BLACK, on_surface=ft.Colors.WHITE,
    error=ft.Colors.RED_ACCENT, on_error=ft.Colors.BLACK)
LIGHT_SCHEME = ft.ColorScheme(
    primary=ft.Colors.BLUE_900, on_primary=ft.Colors.WHITE,
    secondary=ft.Colors.TEAL_900, on_secondary=ft.Colors.WHITE,
    surface=ft.Colors.WHITE, on_surface=ft.Colors.BLACK,
    error=ft.Colors.RED_900, on_error=ft.Colors.WHITE)


def scrollbar_theme(scheme: ft.ColorScheme) -> ft.ScrollbarTheme:
    """large, always visible scrollbar

    JP:
    見やすく大きめのスクロールバー。常に表示し、つまんで動かせる。
    """
    return ft.ScrollbarTheme(
        thickness=SCROLLBAR_THICKNESS, radius=SCROLLBAR_THICKNESS / 2,
        thumb_visibility=True, track_visibility=True, interactive=True,
        thumb_color=scheme.primary, track_color=ft.Colors.GREY_800
        if scheme is DARK_SCHEME else ft.Colors.GREY_300,
        min_thumb_length=48)


def database_path() -> Path:
    """database file path

    JP:
    DB ファイルの場所。環境変数 EYEDROP_DB があればそれ。
    無ければ Flet のアプリ用データフォルダ(FLET_APP_STORAGE_DATA。
    アプリを更新しても消えない)。どちらも無ければカレントディレクトリ。
    """
    if os.environ.get('EYEDROP_DB'):
        return Path(os.environ['EYEDROP_DB'])
    data_dir = os.environ.get('FLET_APP_STORAGE_DATA')
    return Path(data_dir or '.') / DB_NAME


def md(value: date) -> str:
    """date as M/D"""
    return f'{value.month}/{value.day}'


class EyedropApp:
    """mobile app

    JP:
    スマホ版アプリ本体。 page が None でも画面部品の組み立て
    (build_*)はできる(テスト用)。
    """

    def __init__(self, page: Optional[ft.Page], db_path: Path):
        self.page = page
        self.db_path = db_path
        self.db = DrugDb(str(db_path))
        self.tab = 0
        self.detail_drug: Optional[int] = None  # 目薬タブで詳細表示中の薬
        self.share: Optional[ft.Share] = None
        self.picker: Optional[ft.FilePicker] = None
        # 縦スクロール(常にスクロールバーを表示)
        self.body = ft.Column(expand=True, scroll=ft.ScrollMode.ALWAYS,
                              spacing=12)

    # ------------------------------------------------------------ 設定
    @property
    def scale(self) -> float:
        """font scale"""
        value = self.db.get_meta('font_scale') or str(DEFAULT_SCALE)
        if value in OLD_FONT_SCALES:
            return OLD_FONT_SCALES[value]
        try:
            return float(value)
        except ValueError:
            return 1.0

    def change_font(self, step: int):
        """make font larger (step=1) or smaller (step=-1)

        JP:
        文字を1段階大きく(step=1)・小さく(step=-1)する。
        """
        steps = list(FONT_STEPS)
        current = min(steps, key=lambda v: abs(v - self.scale))
        index = max(0, min(len(steps) - 1, steps.index(current) + step))
        self.db.set_meta('font_scale', str(steps[index]))
        self.refresh()

    def reset_font(self):
        """reset font size to default

        JP:
        文字の大きさを既定(100%)に戻す。
        """
        self.db.set_meta('font_scale', str(DEFAULT_SCALE))
        self.refresh()

    def size(self, ratio: float = 1.0) -> float:
        """font size"""
        return round(BASE_SIZE * ratio * self.scale)

    def text(self, value, ratio: float = 1.0, bold: bool = False,
             color=None) -> ft.Text:
        """text with app font size"""
        return ft.Text(str(value), size=self.size(ratio), color=color,
                       weight=ft.FontWeight.BOLD if bold else None)

    def heading(self, value: str) -> ft.Text:
        """section heading"""
        return self.text(value, 1.3, bold=True, color=ft.Colors.PRIMARY)

    def button(self, label: str, on_click, icon=None,
               filled: bool = True) -> ft.Control:
        """large button"""
        cls = ft.FilledButton if filled else ft.OutlinedButton
        return cls(content=self.text(label), icon=icon, on_click=on_click,
                   style=ft.ButtonStyle(padding=ft.Padding.all(14)))

    def build_topbar(self) -> ft.AppBar:
        """top bar with font size buttons (always shown)

        JP:
        常に画面上部に出すバー。文字を小さく(A－)・大きく(A＋)するボタンと
        今の倍率。倍率をタップすると既定(100%)に戻る。
        バーの文字は倍率に関係なく固定の大きさ。
        """
        scale = self.scale

        def font_button(label: str, step: int, tip: str, enabled: bool):
            return ft.FilledButton(
                content=ft.Text(label, size=TOPBAR_SIZE,
                                weight=ft.FontWeight.BOLD),
                tooltip=tip, disabled=not enabled,
                style=ft.ButtonStyle(padding=ft.Padding.symmetric(
                    horizontal=14, vertical=8)),
                on_click=lambda e: self.change_font(step))

        return ft.AppBar(
            toolbar_height=64,
            title=ft.Text(APP_TITLE, size=TOPBAR_SIZE,
                          weight=ft.FontWeight.BOLD),
            actions=[
                font_button('A－', -1, '文字を小さく',
                            scale > FONT_STEPS[0]),
                ft.TextButton(
                    content=ft.Text(f'{scale * 100:.0f}%',
                                    size=TOPBAR_SIZE - 4),
                    tooltip='標準(100%)に戻す',
                    style=ft.ButtonStyle(padding=ft.Padding.symmetric(
                        horizontal=4)),
                    on_click=lambda e: self.reset_font()),
                font_button('A＋', 1, '文字を大きく',
                            scale < FONT_STEPS[-1]),
            ],
            actions_padding=ft.Padding.only(right=8))

    # ------------------------------------------------------------ 起動
    def start(self):
        """set up page

        JP:
        ページを設定して最初の画面を表示する。
        """
        page = self.page
        page.title = APP_TITLE
        page.theme = ft.Theme(color_scheme=LIGHT_SCHEME,
                              scrollbar_theme=scrollbar_theme(LIGHT_SCHEME))
        page.dark_theme = ft.Theme(color_scheme=DARK_SCHEME,
                                   scaffold_bgcolor=ft.Colors.BLACK,
                                   scrollbar_theme=scrollbar_theme(
                                       DARK_SCHEME))
        page.locale_configuration = ft.LocaleConfiguration(
            supported_locales=[ft.Locale('ja', 'JP')],
            current_locale=ft.Locale('ja', 'JP'))
        self.share = ft.Share()
        self.picker = ft.FilePicker()
        page.navigation_bar = ft.NavigationBar(
            selected_index=0, on_change=self.on_tab,
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.SUMMARIZE,
                                            label='サマリー'),
                ft.NavigationBarDestination(icon=ft.Icons.WATER_DROP,
                                            label='目薬'),
                ft.NavigationBarDestination(icon=ft.Icons.SETTINGS,
                                            label='データ'),
            ])
        page.add(ft.SafeArea(content=self.body, expand=True))
        self.refresh()

    def apply_theme(self):
        """theme mode from settings (default dark)"""
        mode = self.db.get_meta('theme_mode') or 'dark'
        self.page.theme_mode = (ft.ThemeMode.LIGHT if mode == 'light'
                                else ft.ThemeMode.DARK)

    def on_tab(self, e):
        """navigation bar changed"""
        self.tab = e.control.selected_index
        self.detail_drug = None
        self.refresh()

    def refresh(self):
        """rebuild current tab

        JP:
        現在のタブを作り直して表示する。
        """
        builders = [self.build_summary, self.build_drugs, self.build_data]
        if self.tab == 1 and self.detail_drug is not None:
            controls = self.build_detail(self.detail_drug)
        else:
            controls = builders[self.tab]()
        # 縦スクロールバーが内容に重ならないよう右に余白
        self.body.controls = [ft.Container(
            padding=ft.Padding.only(right=SCROLLBAR_THICKNESS + 6),
            content=ft.Column(controls=controls, spacing=12))]
        if self.page is not None:
            self.page.appbar = self.build_topbar()
            self.apply_theme()
            self.page.floating_action_button = (
                ft.FloatingActionButton(icon=ft.Icons.ADD,
                                        bgcolor=ft.Colors.PRIMARY,
                                        foreground_color=ft.Colors.ON_PRIMARY,
                                        on_click=self.on_add_drug)
                if self.tab == 1 and self.detail_drug is None else None)
            self.page.update()

    def notify(self, message: str, error: bool = False):
        """show snack bar"""
        if self.page is None:
            return
        self.page.show_dialog(ft.SnackBar(
            content=self.text(message, color=ft.Colors.ON_ERROR if error
                              else None),
            bgcolor=ft.Colors.ERROR if error else None))

    def run(self, action: Callable[[], Optional[str]]):
        """run db action, show result or error, then refresh

        JP:
        DB 操作を実行し、結果(戻り値の文字列)かエラーを表示して画面を更新する。
        """
        try:
            message = action()
        except (DrugDbError, ValueError) as err:
            self.notify(f'エラー: {err}', error=True)
            return
        self.refresh()
        if message:
            self.notify(message)

    # ------------------------------------------------------------ サマリー
    def table(self, heads: list[str], rows: list[list],
              numeric: tuple[int, ...] = ()) -> ft.Control:
        """horizontally scrollable data table

        JP:
        画面からはみ出す表は横スクロール(常にスクロールバーを表示)。
        横スクロールバーが最終行に重ならないよう下に余白を入れ、
        行の高さは文字の大きさに合わせる。
        """
        data_table = ft.DataTable(
            column_spacing=12, horizontal_margin=4,
            heading_row_height=self.size(2.4),
            data_row_min_height=self.size(2.4),
            data_row_max_height=self.size(2.8),
            heading_text_style=ft.TextStyle(size=self.size(0.9),
                                            weight=ft.FontWeight.BOLD),
            data_text_style=ft.TextStyle(size=self.size()),
            columns=[ft.DataColumn(label=ft.Text(h, no_wrap=True),
                                   numeric=i in numeric)
                     for i, h in enumerate(heads)],
            rows=[ft.DataRow(cells=[ft.DataCell(content=ft.Text(
                str(v), no_wrap=True)) for v in row]) for row in rows])
        return ft.Row(scroll=ft.ScrollMode.ALWAYS, controls=[ft.Container(
            padding=ft.Padding.only(bottom=SCROLLBAR_THICKNESS + 6),
            content=data_table)])

    def build_summary(self) -> list[ft.Control]:
        """summary tab

        JP:
        サマリー: 来院時必要本数と目薬在庫の表、注意、共有ボタン。
        """
        report = make_report(self.db)
        pattern_rows = [[line.name, line.req.stock]
                        + [pattern_cell(r) for r in line.patterns]
                        for line in report.lines]
        stock_rows = []
        for line in report.lines:
            req = line.req
            if req.as_needed:
                continue
            stock_rows.append([
                line.name, req.stock, md(req.opened) if req.opened else '',
                '' if req.elapsed is None else req.elapsed,
                remaining_text(req),
                '' if line.last_days is None else line.last_days])
        notes = [self.text(f'{line.name}: {text}', 0.9,
                           color=ft.Colors.ERROR if level == 'warning'
                           else None)
                 for line in report.lines for level, text in notices(line)]
        controls = [
            self.text(f'{report.today.isoformat()} 時点', 0.9),
            self.button('共有(Markdown)', self.on_share_summary,
                        icon=ft.Icons.SHARE),
            self.heading('来院時必要本数'),
            self.table(['目薬名', '未開封']
                       + [SHORT_SPAN_LABELS.get(days, label)
                          for label, days in SPAN_PATTERNS],
                       pattern_rows, numeric=(1,)),
            self.text('必要N…処方をお願いする本数(予備1本込み・最大3本)。'
                      '空欄は処方不要', 0.8),
            self.heading('目薬在庫'),
            self.table(['目薬名', '未開封', '開封日', '経過', '推定残', '日数'],
                       stock_rows, numeric=(1, 3, 5)),
        ]
        if notes:
            controls += [self.heading('注意')] + notes
        if not report.lines:
            controls.append(self.text('目薬が登録されていません。'
                                      '「目薬」タブで追加するか、'
                                      '「データ」タブで復元してください。'))
        return controls

    async def on_share_summary(self, _e):
        """share summary markdown via share sheet"""
        text = to_markdown(make_report(self.db))
        await self.share.share_text(text, subject='目薬 受診前サマリー')

    # ------------------------------------------------------------ 目薬
    def build_drugs(self) -> list[ft.Control]:
        """drugs tab

        JP:
        目薬: 使用中の薬ごとにカード。開封・入庫・棚卸し・詳細。
        """
        report = make_report(self.db)
        controls = []
        for line in report.lines:
            req = line.req
            name = line.name if line.current_name == line.name \
                else f'{line.name}({line.current_name})'
            status = f'未開封 {req.stock}本'
            if req.as_needed:
                status += ' / 随時使用'
            else:
                status += f' / {opened_text(req)}'
            drug_id = line.drug_id
            controls.append(ft.Card(content=ft.Container(
                padding=ft.Padding.all(12),
                content=ft.Column(spacing=8, controls=[
                    self.text(name, 1.2, bold=True),
                    self.text(status, 0.95),
                    ft.Row(wrap=True, spacing=8, run_spacing=8, controls=[
                        self.button('開封',
                                    lambda e, d=drug_id: self.on_open(d),
                                    icon=ft.Icons.WATER_DROP),
                        self.button('入庫',
                                    lambda e, d=drug_id: self.on_receive(d),
                                    icon=ft.Icons.ADD_BOX, filled=False),
                        self.button('棚卸し',
                                    lambda e, d=drug_id: self.on_inventory(d),
                                    icon=ft.Icons.INVENTORY, filled=False),
                        self.button('詳細',
                                    lambda e, d=drug_id: self.show_detail(d),
                                    icon=ft.Icons.HISTORY, filled=False),
                    ])]))))
        if not controls:
            controls.append(self.text('右下の + で目薬を追加します。'))
        return controls

    def show_detail(self, drug_id: int):
        """show drug detail"""
        self.detail_drug = drug_id
        self.refresh()

    def date_button(self, initial: date,
                    on_pick: Callable[[date], None]) -> ft.Control:
        """button showing date, opens date picker

        JP:
        日付を表示するボタン。押すとカレンダーで日付を選べる。
        """
        label = self.text(f'日付: {initial.isoformat()}')

        def picked(e):
            value = e.control.value
            if value is None:
                return
            value = value.date() if isinstance(value, datetime) else value
            label.value = f'日付: {value.isoformat()}'
            on_pick(value)
            label.update()

        def open_picker(_e):
            self.page.show_dialog(ft.DatePicker(
                value=datetime.combine(initial, datetime.min.time()),
                first_date=datetime(2020, 1, 1),
                last_date=datetime(2100, 12, 31), on_change=picked))

        return ft.OutlinedButton(content=label, icon=ft.Icons.CALENDAR_MONTH,
                                 on_click=open_picker)

    def qty_field(self, initial: int) -> ft.TextField:
        """number field"""
        return ft.TextField(value=str(initial), label='本数', width=120,
                            text_size=self.size(1.2),
                            keyboard_type=ft.KeyboardType.NUMBER,
                            input_filter=ft.NumbersOnlyInputFilter())

    def ask(self, title: str, controls: list[ft.Control], ok_label: str,
            on_ok: Callable[[], Optional[str]]):
        """dialog with OK / cancel

        JP:
        OK・キャンセルのダイアログ。 OK で on_ok を実行する。
        """
        def ok(_e):
            self.page.pop_dialog()
            self.run(on_ok)

        self.page.show_dialog(ft.AlertDialog(
            modal=True, title=self.text(title, 1.2, bold=True),
            content=ft.Column(tight=True, spacing=12, controls=controls),
            actions=[ft.TextButton(content=self.text('キャンセル'),
                                   on_click=lambda e: self.page.pop_dialog()),
                     ft.FilledButton(content=self.text(ok_label),
                                     on_click=ok)]))

    def on_open(self, drug_id: int):
        """open new bottle dialog"""
        chosen = {'date': date.today()}
        name = self.db.find_drug(drug_id)['name']

        # 在庫0本での開封は入庫の記録漏れのことが多いので、在庫は減らさない
        from_stock = self.db.balance(drug_id) > 0

        def ok():
            self.db.open_bottle(drug_id, chosen['date'],
                                from_stock=from_stock)
            return f"{name}: {md(chosen['date'])} 開封。" \
                   f'未開封 {self.db.balance(drug_id)}本'

        when = self.date_button(chosen['date'],
                                lambda d: chosen.update(date=d))
        if from_stock:
            note = self.text('在庫から1本出して使い始めます。'
                             '使っていた1本は使い切りになります。', 0.9)
        else:
            note = self.text('未開封の在庫が0本です。在庫は減らさずに開封します。'
                             '入庫の記録漏れがないか確認し、必要なら棚卸し'
                             'してください。', 0.9, color=ft.Colors.ERROR)
        self.ask(f'{name} を開封', [note, when], '開封', ok)

    def on_receive(self, drug_id: int):
        """stock in dialog"""
        chosen = {'date': date.today()}
        name = self.db.find_drug(drug_id)['name']
        qty = self.qty_field(1)

        def ok():
            self.db.receive(drug_id, int(qty.value or 0), chosen['date'])
            return f'{name}: 入庫。未開封 {self.db.balance(drug_id)}本'

        when = self.date_button(chosen['date'],
                                lambda d: chosen.update(date=d))
        self.ask(f'{name} を入庫(処方)', [qty, when], '入庫', ok)

    def on_inventory(self, drug_id: int):
        """stocktaking dialog"""
        chosen = {'date': date.today()}
        name = self.db.find_drug(drug_id)['name']
        qty = self.qty_field(self.db.balance(drug_id))

        def ok():
            self.db.inventory(drug_id, int(qty.value or 0), chosen['date'])
            return f'{name}: 棚卸し。未開封 {self.db.balance(drug_id)}本'

        when = self.date_button(chosen['date'],
                                lambda d: chosen.update(date=d))
        self.ask(f'{name} を棚卸し', [
            self.text('未開封の本数を入力します。', 0.9), qty, when],
            '棚卸し', ok)

    def on_add_drug(self, _e):
        """add drug dialog"""
        name = ft.TextField(label='目薬名', text_size=self.size(1.1),
                            autofocus=True)
        max_days = ft.TextField(label='開封後の推奨期限(日・任意)',
                                text_size=self.size(),
                                keyboard_type=ft.KeyboardType.NUMBER,
                                input_filter=ft.NumbersOnlyInputFilter())
        as_needed = ft.Switch(label='随時使用', value=False,
                              label_text_style=ft.TextStyle(size=self.size()))

        def ok():
            if not (name.value or '').strip():
                raise ValueError('目薬名を入力してください')
            self.db.add_drug(name.value.strip(),
                             max_days=int(max_days.value)
                             if max_days.value else None,
                             as_needed=bool(as_needed.value))
            return f'{name.value.strip()} を追加しました'

        self.ask('目薬を追加', [name, max_days, as_needed], '追加', ok)

    # ------------------------------------------------------------ 詳細
    def build_detail(self, drug_id: int) -> list[ft.Control]:
        """drug detail: settings, lifetimes, stock history

        JP:
        薬の詳細: 設定、ライフタイム(開封)履歴、在庫履歴。
        """
        drug = self.db.find_drug(drug_id)
        req = self.db.requirement(drug_id, span=0)
        controls = [
            ft.Row(controls=[
                ft.IconButton(icon=ft.Icons.ARROW_BACK, icon_size=32,
                              on_click=lambda e: self.show_detail(None)),
                self.text(drug['name'], 1.3, bold=True)]),
            self.text(f'現在の名前: {self.db.current_name(drug_id)}', 0.9),
            self.text(f'未開封 {req.stock}本 / {opened_text(req)}', 0.95),
            self.text(f'1本あたり推定 {req.estimate.days:.0f}日'
                      if req.estimate.days else '1本あたり推定: 実績なし', 0.9),
            ft.Switch(label='随時使用', value=bool(drug['as_needed']),
                      label_text_style=ft.TextStyle(size=self.size()),
                      on_change=lambda e: self.run(lambda: self.db.update_drug(
                          drug_id, as_needed=int(e.control.value)))),
            ft.Row(wrap=True, spacing=8, controls=[
                self.button('推奨期限', lambda e: self.on_max_days(drug_id),
                            icon=ft.Icons.TIMER, filled=False),
                self.button('名前を追加', lambda e: self.on_alias(drug_id),
                            icon=ft.Icons.LABEL, filled=False),
                self.button('使用終了', lambda e: self.on_end(drug_id),
                            icon=ft.Icons.STOP_CIRCLE, filled=False)]),
            self.heading('開封の履歴'),
            self.text('タップでイレギュラー(推定に使わない)を切り替え', 0.8),
        ]
        today = date.today()
        for row in reversed(self.db.lifetimes(drug_id)):
            start = date.fromisoformat(row['use_start'])
            end = date.fromisoformat(row['use_end']) if row['use_end'] \
                else None
            days = ((end or today) - start).days
            label = f"{md(start)} 〜 {md(end) if end else '使用中'}  {days}日"
            if row['irregular']:
                label += '  (イレギュラー)'
            lifetime_id, irregular = row['lifetime_id'], bool(row['irregular'])
            controls.append(ft.ListTile(
                title=self.text(label, color=ft.Colors.ERROR if irregular
                                else None),
                subtitle=self.text(row['note'], 0.8) if row['note'] else None,
                on_click=lambda e, i=lifetime_id, v=irregular:
                    self.run(lambda: self.db.set_irregular(i, not v))))
        controls.append(self.heading('在庫の履歴'))
        labels = {'in': '入庫', 'out': '出庫', 'inventory': '棚卸'}
        for row in reversed(self.db.stock_history(drug_id)):
            stock_id = row['stock_id']
            controls.append(ft.ListTile(
                title=self.text(f"{row['stock_date']} {labels[row['kind']]}"
                                f" {row['qty']}  残{row['balance']}"),
                subtitle=self.text(row['note'], 0.8) if row['note'] else None,
                trailing=ft.IconButton(
                    icon=ft.Icons.DELETE, tooltip='削除',
                    on_click=lambda e, i=stock_id: self.ask(
                        '在庫記録を削除', [self.text('この記録を削除します。')],
                        '削除', lambda: self.db.delete_stock(i)))))
        return controls

    def on_max_days(self, drug_id: int):
        """set recommended max days"""
        drug = self.db.find_drug(drug_id)
        field = ft.TextField(value=str(drug['max_days'] or ''),
                             label='開封後の推奨期限(日・空欄で無し)',
                             text_size=self.size(),
                             keyboard_type=ft.KeyboardType.NUMBER,
                             input_filter=ft.NumbersOnlyInputFilter())
        self.ask('推奨期限', [field], '設定', lambda: self.db.update_drug(
            drug_id, max_days=int(field.value) if field.value else None))

    def on_alias(self, drug_id: int):
        """add current drug name"""
        chosen = {'date': date.today()}
        field = ft.TextField(label='実際にもらった薬の名前',
                             text_size=self.size())

        def ok():
            if not (field.value or '').strip():
                raise ValueError('名前を入力してください')
            self.db.add_alias(drug_id, field.value.strip(), chosen['date'])

        when = self.date_button(chosen['date'],
                                lambda d: chosen.update(date=d))
        self.ask('名前を追加(ジェネリック等)', [field, when], '追加', ok)

    def on_end(self, drug_id: int):
        """end using drug"""
        name = self.db.find_drug(drug_id)['name']

        def ok():
            self.db.update_drug(drug_id, end_date=date.today())
            self.detail_drug = None
            return f'{name} の使用を終了しました'

        self.ask('使用終了', [self.text(
            f'{name} の使用を終了し、サマリーに出さないようにします。')],
            '終了', ok)

    # ------------------------------------------------------------ データ
    def build_data(self) -> list[ft.Control]:
        """data tab

        JP:
        データ: バックアップ・復元・年次更新・文字サイズ・表示テーマ。
        """
        theme = self.db.get_meta('theme_mode') or 'dark'
        return [
            self.heading('バックアップ'),
            self.text('データはこのスマホの中にだけあります。'
                      '機種変更や故障に備えて、ときどき保存してください。', 0.9),
            self.button('ファイルに保存', self.on_backup_save,
                        icon=ft.Icons.SAVE),
            self.button('共有で送る', self.on_backup_share,
                        icon=ft.Icons.SHARE, filled=False),
            self.heading('復元'),
            self.text('保存したバックアップ(または PC の eyedrop.db)で'
                      '今のデータを置き換えます。', 0.9),
            self.button('ファイルから復元', self.on_restore,
                        icon=ft.Icons.RESTORE, filled=False),
            self.heading('年次更新'),
            self.text('指定した年より前の記録を退避し、在庫を繰り越します。', 0.9),
            self.button('年次更新', lambda e: self.on_rollover(),
                        icon=ft.Icons.EVENT_REPEAT, filled=False),
            self.heading('表示'),
            self.text('文字の大きさは画面上部の「A－」「A＋」で変えられます。',
                      0.9),
            ft.Switch(label='黒地に白(高コントラスト)', value=theme != 'light',
                      label_text_style=ft.TextStyle(size=self.size()),
                      on_change=lambda e: self.run(lambda: self.db.set_meta(
                          'theme_mode',
                          'dark' if e.control.value else 'light'))),
            self.text(f'データの場所: {self.db_path}', 0.7),
        ]

    async def on_backup_save(self, _e):
        """save backup via save dialog"""
        try:
            path = await self.picker.save_file(
                dialog_title='バックアップの保存先',
                file_name=backup_file_name(),
                src_bytes=backup_bytes(self.db))
        except (OSError, ValueError) as err:
            self.notify(f'エラー: {err}', error=True)
            return
        if path:
            self.notify('バックアップを保存しました')

    async def on_backup_share(self, _e):
        """share backup file"""
        await self.share.share_files(
            [ft.ShareFile.from_bytes(backup_bytes(self.db),
                                     name=backup_file_name(),
                                     mime_type='application/x-sqlite3')],
            subject='目薬管理 バックアップ')

    async def on_restore(self, _e):
        """restore from picked file"""
        files = await self.picker.pick_files(
            dialog_title='復元するファイル', with_data=True)
        if not files:
            return
        picked = files[0]
        data = picked.bytes or (Path(picked.path).read_bytes()
                                if picked.path else b'')
        try:
            count = check_backup(data)
        except DrugDbError as err:
            self.notify(f'エラー: {err}', error=True)
            return

        def ok():
            self.db.close()
            try:
                restore_bytes(data, self.db_path)
            finally:
                self.db = DrugDb(str(self.db_path))
            return f'復元しました(目薬 {count}件)'

        self.ask('復元', [self.text(
            f'{picked.name} (目薬 {count}件)で今のデータを置き換えます。'
            '元に戻せません。')], '復元', ok)

    def on_rollover(self):
        """yearly rollover dialog"""
        year = ft.TextField(value=str(date.today().year - 1),
                            label='この年の1月1日より前を退避', width=260,
                            text_size=self.size(1.1),
                            keyboard_type=ft.KeyboardType.NUMBER,
                            input_filter=ft.NumbersOnlyInputFilter())
        out_dir = self.db_path.parent / 'archive'

        def ok():
            result = rollover(self.db, int(year.value), out_dir)
            return (f'年次更新しました(在庫記録 {result.stock_archived}件、'
                    f'開封 {result.lifetime_archived}件を退避)。'
                    'データタブからバックアップを保存してください')

        self.ask('年次更新', [
            self.text('退避した記録は端末内の archive フォルダに残ります。'
                      '実行前にバックアップを保存しておくと安心です。', 0.9),
            year], '実行', ok)


def main(page: ft.Page):
    """flet entry point"""
    EyedropApp(page, database_path()).start()


if __name__ == '__main__':
    ft.run(main)
