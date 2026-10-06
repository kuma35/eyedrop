# -*- coding: utf-8 -*-
"""eyedrop mobile (Android) app

JP:
目薬管理 スマホ版(Flet)
========================

データは端末内で完結(スタンドアロン)。コア(在庫・推定・サマリー)は
drugdb パッケージを PC 版と共通で使います。

画面は下部のタブで切り替えます。

- サマリー: 来院日・次回来院日と、次回来院までに必要な本数(と根拠)・目薬在庫の表。
  メニューから Markdown 等でコピー
- 目薬: 開封・入庫・棚卸し。薬ごとの履歴と設定
- 一括棚卸し: 来院前に使用中の目薬をまとめて数え直す。棚卸し実行でサマリーへ
- 設定: バックアップ・復元・年次更新・次回来院日の既定の期間・表示テーマ

左上のメニュー(ハンバーガーメニュー)から、名前の表示の切り替え、
一括棚卸し(タブへのショートカット)、サマリーのコピー。

目が悪くても見やすいよう、既定は黒地に白の高コントラストで文字は大きめ。
"""
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import flet as ft

from drugdb.ai_export import to_ai_prompt
from drugdb.backup import backup_bytes, backup_file_name, restore_bytes
from drugdb.backup import check_backup
from drugdb.drugdb import DrugDb, DrugDbError
from drugdb.report import (DEFAULT_SPAN, NAME_HEAD, SPAN_UNITS, basis_cells,
                           get_default_span, inventory_result_text,
                           line_name, make_report, need_cell, notices,
                           opened_text, remaining_text,
                           set_default_span, span_label, span_to_unit,
                           to_markdown, to_plain_text, unit_to_span)
from drugdb.rollover import rollover

APP_TITLE = '目薬管理'
DB_NAME = 'eyedrop.db'

# 値の桁数が少ない列は見出しを2段にして幅を詰める(Markdown の書き出しは1行のまま)
UNOPENED_HEAD = '未\n開封'
# 次回来院までに必要な本数の表の列(名前の後)。必要本数に続いて根拠
# (report.BASIS_HEADS と同じ順: 足りない日数・在庫残日数・未開封・通常期間・
# 開封分残日数)
NEED_HEADS = ['必要\n本数', '足りない\n日数', '在庫\n残日数', UNOPENED_HEAD,
              '通常\n期間', '開封分\n残日数']

# コメント欄の最大文字数(一言メモ程度)
MEMO_MAX = 100

# 随時使用の表示(毎日ではなく必要なときに使う目薬)
AS_NEEDED_LABEL = '随時(必要時・頓用;頓服風に使用)'

# 開封中の1本の残り日数の文言(推定値であることを明示)
REMAINING_LABEL = '推定残り'

# 文字サイズの倍率(画面上部の A－ / A＋ で切り替え)
# 既定(DEFAULT_SCALE)より小さくもできる。倍率表示をタップすると既定に戻る
FONT_STEPS = (0.75, 0.9, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5)
DEFAULT_SCALE = 1.0
# タブレット(画面の短い辺が TABLET_MIN_DP 以上)の既定の倍率。
# 白内障などで画面の大きいタブレットを持ち歩く人を想定して最初から大きめ
TABLET_SCALE = 1.5
TABLET_MIN_DP = 600
# 以前の設定値(ラジオボタン時代)からの読み替え
OLD_FONT_SCALES = {'標準': 1.0, '大': 1.25, '特大': 1.5}
BASE_SIZE = 18
# 上部バーの文字は倍率に関係なく固定(大きくしてもボタンがはみ出さない)
TOPBAR_SIZE = 22

# 一括棚卸しの「－」「＋」と本数の文字の倍率の上限。これより大きくすると
# スマホの幅に1行で収まらず「＋」がはみ出す(SH-54D で 250% のとき)
BULK_MAX_SCALE = 1.5

# 下のタブの並び(設定は右端)
TAB_SUMMARY, TAB_DRUGS, TAB_BULK, TAB_DATA = range(4)
NAV_TABS = (('サマリー', ft.Icons.SUMMARIZE), ('目薬', ft.Icons.WATER_DROP),
            ('一括棚卸し', ft.Icons.FACT_CHECK), ('設定', ft.Icons.SETTINGS))
# 下のタブのラベルとアイコンの大きさ(倍率 100% のとき。Material 3 の既定)
NAV_LABEL_SIZE = 12
NAV_ICON_SIZE = 24
# 下のタブ1つの幅のうち文字に使えない分(左右の余白)
NAV_TAB_PADDING = 12
# 画面の幅が分からないとき(テスト)の幅(dp)
NAV_DEFAULT_WIDTH = 400

# 表の罫線の太さ
TABLE_LINE_WIDTH = 1

# スクロールバー: 太く、常に表示、つまんで動かせる
SCROLLBAR_THICKNESS = 16

# 高コントラスト(黒地に白)
DARK_SCHEME = ft.ColorScheme(
    primary=ft.Colors.YELLOW_ACCENT, on_primary=ft.Colors.BLACK,
    secondary=ft.Colors.CYAN_ACCENT, on_secondary=ft.Colors.BLACK,
    surface=ft.Colors.BLACK, on_surface=ft.Colors.WHITE,
    outline=ft.Colors.GREY_500,
    error=ft.Colors.RED_ACCENT, on_error=ft.Colors.BLACK)
LIGHT_SCHEME = ft.ColorScheme(
    primary=ft.Colors.BLUE_900, on_primary=ft.Colors.WHITE,
    secondary=ft.Colors.TEAL_900, on_secondary=ft.Colors.WHITE,
    surface=ft.Colors.WHITE, on_surface=ft.Colors.BLACK,
    outline=ft.Colors.GREY_700,
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


def picked_date(value) -> Optional[date]:
    """date chosen in DatePicker

    JP:
    DatePicker で選んだ日付。 Flutter から UTC の日時で返ることがあり
    (日本時間 6/30 0時 → UTC 6/29 15時)、そのまま日付にすると1日ずれる。
    12時間足してから日付にすれば、UTC で返っても現地時刻で返っても
    選んだ日になる(UTC-12〜+12 の範囲)。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return (value + timedelta(hours=12)).date()
    return value


def device_default_scale(width, height) -> float:
    """default font scale by screen size

    JP:
    画面の大きさ(論理ピクセル=dp)から文字の大きさの既定を決める。
    短い辺が TABLET_MIN_DP 以上ならタブレットとして TABLET_SCALE。
    """
    if width and height and min(width, height) >= TABLET_MIN_DP:
        return TABLET_SCALE
    return DEFAULT_SCALE


def nav_layout(width, scale: float) -> tuple[str, list[str], float]:
    """layout of bottom tabs by screen width and font scale

    JP:
    下のタブの表示を決める。戻り値は (形, ラベル, 文字の大きさ)。
    全部のラベルが1つのタブの幅に入る間は 'icon'(アイコン + ラベル。
    倍率に合わせて大きくする)。入らなくなったら 'text'(アイコンをやめて
    文字だけ。アプリの文字と同じ大きさで、入る文字数で先頭から切る。
    例: 「サマ」「目薬」「一括」「設定」→「サ」「目」「一」「設」)。
    日本語は1文字の幅がほぼ文字の大きさと同じとして数える。
    """
    labels = [label for label, _icon in NAV_TABS]
    tab = (width or NAV_DEFAULT_WIDTH) / len(NAV_TABS) - NAV_TAB_PADDING
    label_size = NAV_LABEL_SIZE * scale
    if max(len(label) for label in labels) * label_size <= tab:
        return 'icon', labels, label_size
    # 1文字も入らないほど大きいときはタブの幅に合わせて小さくする
    size = min(BASE_SIZE * scale, tab)
    count = max(1, int(tab // size))
    return 'text', [label[:count] for label in labels], size


def memo_value(field: ft.TextField) -> Optional[str]:
    """comment text or None if blank"""
    return (field.value or '').strip() or None


def md(value: date) -> str:
    """date as M/D"""
    return f'{value.month}/{value.day}'


def open_note(has_opened: bool, from_stock: bool) -> str:
    """explanation text of open dialog

    JP:
    開封ダイアログの説明文。 has_opened は開封中の目薬があるか、
    from_stock は在庫から出庫するか(在庫0本なら出庫しない)。
    """
    if has_opened:
        text = ('既に開封済みの目薬がみてた(空になった)ので、'
                '新しい目薬を在庫から1本出して使い始めます'
                '(みてた(空になった)目薬については開封日(通常は本日)を'
                '利用終了日として記録し、開封の履歴に追記します)。')
    else:
        text = '新しい目薬を在庫から1本出して使い始めます(開封の履歴に追記します)。'
    if not from_stock:
        text += ('\nただし未開封の在庫が0本なので、在庫は減らさずに開封します。'
                 '入庫の記録漏れがないか確認し、必要なら棚卸ししてください。')
    return text


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
        # 文字の大きさの既定(端末で決まる。 start でタブレットなら大きくする)。
        # ユーザーが A－/A＋ で変えたら meta に覚え、以後はそれを使う
        self.default_scale = DEFAULT_SCALE
        # 終了日なしで残った古い開封(ods 取込由来)を直す。何度実行しても同じ
        self.fixed_stale = self.db.close_stale_lifetimes()
        self.tab = 0
        self.detail_drug: Optional[int] = None  # 目薬タブで詳細表示中の薬
        self.show_ended = False  # 目薬タブで利用終了した目薬も表示
        # 一括棚卸しのタブを表示中なら {'date': 日付, 'counts': {drug_id: 本数},
        # 'memo': コメント}。文字の大きさを変えて作り直しても入力中の本数が
        # 消えないようここに持つ。ほかのタブに移ると捨てる
        self.bulk: Optional[dict] = None
        # サマリーの来院日・次回来院日(None なら今日・来院日 + 既定の期間)。
        # アプリを閉じると既定に戻る
        self.visit_date: Optional[date] = None
        self.next_date: Optional[date] = None
        self.share: Optional[ft.Share] = None
        self.picker: Optional[ft.FilePicker] = None
        # 縦スクロール(常にスクロールバーを表示)
        self.body = ft.Column(expand=True, scroll=ft.ScrollMode.ALWAYS,
                              spacing=12)

    # ------------------------------------------------------------ 設定
    @property
    def scale(self) -> float:
        """font scale"""
        value = self.db.get_meta('font_scale')
        if value is None:
            return self.default_scale
        if value in OLD_FONT_SCALES:
            return OLD_FONT_SCALES[value]
        try:
            return float(value)
        except ValueError:
            return 1.0

    @property
    def name_mode(self) -> str:
        """drug name display mode ('representative' or 'actual')

        JP:
        名前の表示。 'representative' は代表目薬名(例: コソプト。固定)、
        'actual' は実際に支給される名前(例: ドルモロール)。既定は代表目薬名。
        """
        mode = self.db.get_meta('name_mode')
        return mode if mode in ('representative', 'actual') \
            else 'representative'

    def set_name_mode(self, mode: str):
        """switch drug name display on all screens"""
        self.db.set_meta('name_mode', mode)
        self.refresh()

    def drug_label(self, drug_id: int) -> str:
        """drug name by current display mode"""
        if self.name_mode == 'actual':
            return self.db.current_name(drug_id)
        return self.db.find_drug(drug_id)['name']

    def summary_dates(self) -> tuple[date, date]:
        """(visit date, next visit date) of summary

        JP:
        サマリーの来院日と次回来院日。未指定なら今日と来院日 + 既定の期間。
        """
        visit = self.visit_date or date.today()
        return visit, self.next_date or visit + timedelta(
            days=get_default_span(self.db))

    def report(self, summary: bool = False):
        """report with current name mode

        JP:
        レポート。 summary ならサマリーの来院日・次回来院日で、
        そうでなければ今日時点(目薬タブの開封中の状態など)。
        """
        if not summary:
            return make_report(self.db, name_mode=self.name_mode)
        visit, next_visit = self.summary_dates()
        return make_report(self.db, today=visit, next_visit=next_visit,
                           name_mode=self.name_mode)

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
        文字の大きさをこの端末の既定(スマホは100%、タブレットは150%)に戻す。
        """
        self.db.set_meta('font_scale', str(self.default_scale))
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

        mode = self.name_mode

        def menu_item(label: str, value: str) -> ft.PopupMenuItem:
            return ft.PopupMenuItem(
                content=ft.Text(label, size=TOPBAR_SIZE - 2),
                checked=mode == value, height=56,
                on_click=lambda e: self.set_name_mode(value))

        def action_item(label: str, icon, handler) -> ft.PopupMenuItem:
            return ft.PopupMenuItem(
                content=ft.Text(label, size=TOPBAR_SIZE - 2), icon=icon,
                height=72, on_click=handler)

        # ハンバーガーメニュー: 名前の表示を画面内一斉に切り替える。
        # 一括棚卸し(タブへのショートカット)。
        # サマリーのコピー(受診時はアプリを見せればよいのでボタンは画面に出さない。
        # Evernote Web は Markdown を認識、 Android アプリはテキストのまま)
        menu = ft.PopupMenuButton(
            icon=ft.Icons.MENU, icon_size=32, tooltip='メニュー',
            items=[menu_item('代表目薬名で表示(例: コソプト)', 'representative'),
                   menu_item('目薬名で表示(例: ドルモロール)', 'actual'),
                   ft.PopupMenuItem(),  # 区切り線
                   action_item('一括棚卸し', ft.Icons.FACT_CHECK,
                               lambda e: self.show_bulk_inventory()),
                   ft.PopupMenuItem(),  # 区切り線
                   # アイコン付きの項目は折り返されないので2行に分ける
                   action_item('サマリーを\nMarkdown でコピー',
                               ft.Icons.CONTENT_COPY, self.on_copy_summary),
                   action_item('サマリーを\nテキストでコピー', ft.Icons.NOTES,
                               self.on_copy_text),
                   action_item('サマリーを\nチャットAI用にコピー',
                               ft.Icons.AUTO_AWESOME,
                               self.on_copy_ai)])
        return ft.AppBar(
            toolbar_height=64, leading=menu, leading_width=56,
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
        self.default_scale = device_default_scale(page.width, page.height)
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
        self.clipboard = ft.Clipboard()
        self.picker = ft.FilePicker()
        # 下のタブは refresh で作る(文字の大きさと画面の幅で変わる)
        page.on_resize = self.on_resize
        page.add(ft.SafeArea(content=self.body, expand=True))
        self.refresh()
        if self.fixed_stale:
            self.notify(f'終了日のない古い開封記録 {len(self.fixed_stale)}件を、'
                        '次の開封日で終了(イレギュラー)にしました')

    def apply_theme(self):
        """theme mode from settings (default dark)"""
        mode = self.db.get_meta('theme_mode') or 'dark'
        self.page.theme_mode = (ft.ThemeMode.LIGHT if mode == 'light'
                                else ft.ThemeMode.DARK)

    def on_resize(self, _e):
        """screen size changed (rotation etc.)

        JP:
        画面の幅が変わったら(回転など)下のタブだけ作り直す。
        高さだけの変化(キーボードの表示など)では何もしない
        (画面全体を作り直すと入力中の欄からフォーカスが外れるため)。
        """
        if self.page.width != getattr(self, '_nav_width', None):
            self.page.navigation_bar = self.build_navigation_bar()
            self.page.update()

    def build_navigation_bar(self) -> ft.NavigationBar:
        """bottom tabs sized by font scale

        JP:
        下のタブ。文字の大きさ(A－/A＋)に合わせて大きくする(nav_layout 参照)。
        文字だけの形では、選ばれたタブを色・太字・背景の枠で示す(選択の丸い印は
        大きさが固定で文字からはみ出すので消す)。タブを長押しすると
        省略しない名前が出る。
        """
        width = self.page.width if self.page is not None else None
        self._nav_width = width
        scale = self.scale
        mode, labels, size = nav_layout(width, scale)
        if mode == 'icon':
            # 既定(100%)で 80
            height = round(44 + (NAV_ICON_SIZE + NAV_LABEL_SIZE) * scale)
        else:
            height = max(80, round(size * 1.4 + 32))
        self._nav_height = height
        if self.page is not None:
            # ラベルの文字の大きさはテーマでしか変えられない。
            # 高さもテーマで指定する(コントロールの height は画面下の
            # システムのボタンの分まで含むので、タブが下に隠れて切れる)
            # 選ばれたタブのラベルは太字で明るく(Material 3 の既定と同じ見た目)
            style = ft.NavigationBarTheme(
                height=height,
                label_text_style={
                    ft.ControlState.SELECTED: ft.TextStyle(
                        size=round(size), color=ft.Colors.ON_SURFACE,
                        weight=ft.FontWeight.W_600),
                    ft.ControlState.DEFAULT: ft.TextStyle(
                        size=round(size),
                        color=ft.Colors.ON_SURFACE_VARIANT)})
            self.page.theme.navigation_bar_theme = style
            self.page.dark_theme.navigation_bar_theme = style
        destinations = []
        for (name, icon), label in zip(NAV_TABS, labels):
            if mode == 'icon':
                destinations.append(ft.NavigationBarDestination(
                    icon=ft.Icon(icon, size=round(NAV_ICON_SIZE * scale)),
                    label=name, tooltip=name))
                continue
            destinations.append(ft.NavigationBarDestination(
                icon=ft.Text(label, size=round(size), no_wrap=True,
                             color=ft.Colors.ON_SURFACE),
                # 選ばれたタブは色付きの背景の枠で示す(下線だと「一」が
                # 「二」に見えるため)
                selected_icon=ft.Container(
                    content=ft.Text(label, size=round(size), no_wrap=True,
                                    color=ft.Colors.PRIMARY,
                                    weight=ft.FontWeight.BOLD),
                    bgcolor=ft.Colors.with_opacity(0.25, ft.Colors.PRIMARY),
                    border_radius=8,
                    padding=ft.Padding.symmetric(horizontal=4)),
                label=name, tooltip=name))
        if mode == 'icon':
            return ft.NavigationBar(
                selected_index=self.tab, on_change=self.on_tab,
                destinations=destinations)
        return ft.NavigationBar(
            selected_index=self.tab, on_change=self.on_tab,
            label_behavior=ft.NavigationBarLabelBehavior.ALWAYS_HIDE,
            indicator_color=ft.Colors.TRANSPARENT,
            destinations=destinations)

    def on_tab(self, e):
        """navigation bar changed

        JP:
        下のタブが押された。一括棚卸しの入力を実行せずに離れようとしたときは
        警告して一括棚卸しのタブに留まる(confirm_leave_bulk)。
        """
        index = e.control.selected_index

        def go():
            self.set_tab(index)
            self.refresh()

        if index == self.tab or self.confirm_leave_bulk(go):
            go()

    def set_tab(self, index: int):
        """switch tab

        JP:
        タブを切り替える。一括棚卸しのタブに入るときは、本数を記録上の
        本数(今日の時点)から始める。
        """
        self.tab = index
        self.detail_drug = None
        self.bulk = None
        if index == TAB_BULK:
            self.reset_bulk()

    def refresh(self):
        """rebuild current tab

        JP:
        現在のタブを作り直して表示する。
        """
        builders = {TAB_SUMMARY: self.build_summary,
                    TAB_DRUGS: self.build_drugs,
                    TAB_BULK: self.build_bulk_inventory,
                    TAB_DATA: self.build_data}
        if self.tab == TAB_DRUGS and self.detail_drug is not None:
            controls = self.build_detail(self.detail_drug)
        else:
            controls = builders[self.tab]()
        # 縦スクロールバーが内容に重ならないよう右に余白
        # 画面(タブ・詳細)が変わったら先頭から表示する
        view = (self.tab, self.detail_drug)
        scroll_top = view != getattr(self, '_view', view)
        self._view = view
        self.body.controls = [ft.Container(
            padding=ft.Padding.only(right=SCROLLBAR_THICKNESS + 6),
            content=ft.Column(controls=controls, spacing=12))]
        if self.page is not None:
            self.page.appbar = self.build_topbar()
            self.page.navigation_bar = self.build_navigation_bar()
            if scroll_top:
                self.page.run_task(self.body.scroll_to, offset=0)
            self.apply_theme()
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
        外枠と縦横の罫線を付け、見出し行に色を付けて表だと分かるようにする。
        データが無いときも空の行を1行出す。
        """
        if not rows:
            rows = [[''] * len(heads)]
        # 見出しが2段(\n を含む)なら見出し行を高くする
        head_lines = max(h.count('\n') + 1 for h in heads)
        line = ft.BorderSide(width=TABLE_LINE_WIDTH, color=ft.Colors.OUTLINE)
        data_table = ft.DataTable(
            column_spacing=12, horizontal_margin=8,
            border=ft.Border.all(width=TABLE_LINE_WIDTH + 1,
                                 color=ft.Colors.OUTLINE),
            horizontal_lines=line, vertical_lines=line,
            heading_row_color=ft.Colors.with_opacity(0.2,
                                                     ft.Colors.PRIMARY),
            heading_row_height=self.size(max(2.4, 1.2 * head_lines + 1.0)),
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

    def summary_date_button(self, label: str, value: date,
                            on_pick: Callable[[date], None]) -> ft.Control:
        """button showing summary date, opens date picker

        JP:
        サマリーの日付ボタン。押すとカレンダーで日付を選び、 on_pick を呼ぶ。
        """
        def picked(e):
            chosen = picked_date(e.control.value)
            if chosen is not None:
                on_pick(chosen)

        def open_picker(_e):
            self.page.show_dialog(ft.DatePicker(
                value=datetime.combine(value, datetime.min.time()),
                first_date=datetime(2020, 1, 1),
                last_date=datetime(2100, 12, 31), on_change=picked))

        return ft.OutlinedButton(content=self.text(label),
                                 icon=ft.Icons.CALENDAR_MONTH,
                                 on_click=open_picker)

    def set_visit_date(self, value: Optional[date]):
        """change visit date of summary (None: today)

        JP:
        サマリーの来院日を変える(None で今日)。次回来院日を指定済みで、
        それが来院日以前になるなら次回来院日を既定に戻す。
        """
        self.visit_date = value
        if self.next_date and self.next_date <= self.summary_dates()[0]:
            self.next_date = None
            self.notify('次回来院日を既定に戻しました')
        self.refresh()

    def set_next_date(self, value: Optional[date]):
        """change next visit date of summary (None: default)"""
        if value is not None and value <= self.summary_dates()[0]:
            self.notify('次回来院日は来院日より後の日付にしてください',
                        error=True)
            return
        self.next_date = value
        self.refresh()

    def summary_date_controls(self, visit: date,
                              next_visit: date) -> list[ft.Control]:
        """visit / next visit date buttons of summary

        JP:
        サマリー先頭の来院日・次回来院日の欄。押すとカレンダーで変えられる。
        変えたときは「今日に戻す」「既定に戻す」を出す。
        """
        default = span_label(get_default_span(self.db))
        visit_row = [self.summary_date_button(
            f'来院日 {visit.isoformat()}', visit, self.set_visit_date)]
        if self.visit_date:
            visit_row.append(ft.TextButton(
                content=self.text('来院日を今日に戻す', 0.9),
                on_click=lambda e: self.set_visit_date(None)))
        next_row = [self.summary_date_button(
            f'次回来院日 {next_visit.isoformat()}'
            f'({(next_visit - visit).days}日後)', next_visit,
            self.set_next_date)]
        if self.next_date:
            next_row.append(ft.TextButton(
                content=self.text(f'次回来院日を既定({default}後)に戻す', 0.9),
                on_click=lambda e: self.set_next_date(None)))
        return [ft.Row(wrap=True, spacing=8, run_spacing=8, controls=row)
                for row in (visit_row, next_row)]

    def build_summary(self) -> list[ft.Control]:
        """summary tab

        JP:
        サマリー: 来院日・次回来院日、次回来院までに必要な本数(と根拠)と
        目薬在庫の表、注意。
        """
        report = self.report(summary=True)
        mode = report.name_mode
        need_rows = [[line_name(line, mode), need_cell(line.req)]
                     + basis_cells(line.req) for line in report.lines]
        stock_rows = []
        for line in report.lines:
            req = line.req
            if req.as_needed:
                continue
            stock_rows.append([
                line_name(line, mode), req.stock,
                md(req.opened) if req.opened else '',
                remaining_text(req),
                '' if line.last_days is None else line.last_days])
        notes = [self.text(f'{line_name(line, mode)}: {text}', 0.9,
                           color=ft.Colors.ERROR if level == 'warning'
                           else None)
                 for line in report.lines for level, text in notices(line)]
        controls = [
            *self.summary_date_controls(report.today, report.next_visit),
            self.heading('次回来院までに必要な本数'),
            self.table([NAME_HEAD[mode]] + NEED_HEADS, need_rows,
                       numeric=(1, 2, 3, 4, 5, 6)),
            self.text('必要本数：処方をお願いする本数(足りない日数÷通常期間を'
                      '切り上げて予備1本を足す)。0は処方不要。'
                      '足りない日数：次回来院日までの日数−在庫残日数'
                      '(マイナスは余る日数)。'
                      '在庫残日数：来院日の時点で残っている目薬の日数'
                      '(開封分残日数＋未開封×通常期間)。'
                      '通常期間：1本を何日で使い切るか。'
                      '開封分残日数：来院日の時点での、いま使っている1本の'
                      '残り日数(通常期間−(来院日−開封日))', 0.8),
            self.heading('目薬在庫'),
            self.table([NAME_HEAD[mode], UNOPENED_HEAD, '開封日', '残\n日数',
                        '通常\n日数'],
                       stock_rows, numeric=(1, 3, 4)),
            self.text('開封日：現在使っている目薬を開封した日。'
                      '残日数：来院日の時点で現在使っている目薬の推定残量(日数)、'
                      '通常日数：この目薬は通常何日で使い切っているか', 0.8),
        ]
        if notes:
            controls += [self.heading('注意')] + notes
        if not report.lines:
            controls.append(self.text('目薬が登録されていません。'
                                      '「目薬」タブで追加するか、'
                                      '「設定」タブで復元してください。'))
        return controls

    async def on_copy_summary(self, _e):
        """copy summary markdown to clipboard

        JP:
        サマリーを Markdown でクリップボードにコピーする。
        Evernote へは手動で貼り付ける(共有メニューではうまくいかなかったため)。
        """
        await self.clipboard.set(to_markdown(self.report(summary=True)))
        self.notify('Markdown をコピーしました。Evernote Web に'
                    '貼り付けてください')

    async def on_copy_text(self, _e):
        """copy summary plain text to clipboard

        JP:
        サマリーをテキスト版でクリップボードにコピーする。 Evernote の
        Android アプリは貼り付けるとテキストのままになるので、記号の少ない
        読みやすい形にしたもの。
        """
        await self.clipboard.set(to_plain_text(self.report(summary=True)))
        self.notify('テキストをコピーしました。Evernote アプリに'
                    '貼り付けてください')

    async def on_copy_ai(self, _e):
        """copy prompt + JSON for chat AI

        JP:
        チャットAI(Evernote AI など)用に、指示(プロンプト)と次回来院までに必要な本数・目薬在庫の
        データ(JSON)をクリップボードにコピーする。
        """
        await self.clipboard.set(to_ai_prompt(self.report(summary=True)))
        self.notify('チャットAI用にコピーしました。チャットAI'
                    '(Evernote AI など)に貼り付けてください')

    # ------------------------------------------------------------ 目薬
    def build_drugs(self) -> list[ft.Control]:
        """drugs tab

        JP:
        目薬: 使用中の薬ごとにカード。開封・入庫・棚卸し・詳細。
        """
        report = self.report()
        # 代表目薬名の追加(スクロール部分の先頭)
        controls = [self.button('目薬追加', self.on_add_drug,
                                icon=ft.Icons.ADD)]
        for line in report.lines:
            req = line.req
            name = line_name(line, report.name_mode)
            status = f'未開封 {req.stock}本'
            if req.as_needed:
                status += ' / 随時使用'
            else:
                status += f' / {opened_text(req, REMAINING_LABEL)}'
            drug_id = line.drug_id
            controls.append(ft.Card(content=ft.Container(
                padding=ft.Padding.all(12),
                content=ft.Column(spacing=8, controls=[
                    self.text(name, 1.2, bold=True),
                    self.text(status, 0.95),
                    ft.Row(wrap=True, spacing=8, run_spacing=8, controls=[
                        self.button('開封(出庫)',
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
                        self.button('利用終了',
                                    lambda e, d=drug_id: self.on_end(d),
                                    icon=ft.Icons.STOP_CIRCLE, filled=False),
                    ])]))))
        if not report.lines:
            controls.append(self.text('上の「目薬追加」で目薬を登録します。'))
        controls.append(ft.Switch(
            label='利用終了した目薬も表示', value=self.show_ended,
            label_text_style=ft.TextStyle(size=self.size()),
            on_change=lambda e: self.set_show_ended(e.control.value)))
        if self.show_ended:
            for drug in self.db.list_drugs():
                if self.db.is_active(drug['drug_id']):
                    continue
                drug_id = drug['drug_id']
                controls.append(ft.Card(content=ft.Container(
                    padding=ft.Padding.all(12),
                    content=ft.Column(spacing=8, controls=[
                        self.text(self.drug_label(drug_id), 1.1, bold=True,
                                  color=ft.Colors.OUTLINE),
                        self.text(self.end_text(drug_id), 0.9),
                        ft.Row(wrap=True, spacing=8, run_spacing=8, controls=[
                            self.button(
                                '詳細', lambda e, d=drug_id: self.show_detail(d),
                                icon=ft.Icons.HISTORY, filled=False),
                            self.button(
                                '利用中に戻す',
                                lambda e, d=drug_id: self.on_restore_use(d),
                                icon=ft.Icons.PLAY_CIRCLE, filled=False)])]))))
        return controls

    def set_show_ended(self, value: bool):
        """show ended drugs in drugs tab"""
        self.show_ended = bool(value)
        self.refresh()

    def end_text(self, drug_id: int) -> str:
        """why the drug is ended

        JP:
        利用終了の表示。代表目薬名の利用終了日、または目薬名がすべて
        利用終了していること。
        """
        drug = self.db.find_drug(drug_id)
        if drug['end_date']:
            return f"利用終了 {drug['end_date']}"
        ends = [r['end_date'] for r in self.db.aliases(drug_id)
                if r['end_date']]
        return f'利用終了 {max(ends)}(目薬名がすべて利用終了)' \
            if ends else '利用終了'

    def show_detail(self, drug_id: int):
        """show drug detail"""
        self.detail_drug = drug_id
        self.refresh()

    def date_button(self, initial: date, on_pick: Callable[[date], None],
                    prefix: str = '日付') -> ft.Control:
        """button showing date, opens date picker

        JP:
        日付を表示するボタン。押すとカレンダーで日付を選べる。
        """
        label = self.text(f'{prefix}: {initial.isoformat()}')

        def picked(e):
            value = picked_date(e.control.value)
            if value is None:
                return
            label.value = f'{prefix}: {value.isoformat()}'
            on_pick(value)
            label.update()

        def open_picker(_e):
            self.page.show_dialog(ft.DatePicker(
                value=datetime.combine(initial, datetime.min.time()),
                first_date=datetime(2020, 1, 1),
                last_date=datetime(2100, 12, 31), on_change=picked))

        return ft.OutlinedButton(content=label, icon=ft.Icons.CALENDAR_MONTH,
                                 on_click=open_picker)

    def memo_field(self) -> ft.TextField:
        """optional comment field

        JP:
        コメント欄(任意)。在庫記録の note 列に入る。空欄なら NULL で、
        SQLite では容量をほとんど使わない。
        """
        return ft.TextField(label='コメント(任意)', text_size=self.size(),
                            max_length=MEMO_MAX)

    def labeled_switch(self, label: str, value: bool, on_change=None):
        """switch with wrapping label, returns (row, switch)

        JP:
        長いラベルでもはみ出さず折り返すスイッチ。 Switch の label は
        折り返さないので、ラベルを別の Text にして横に並べる。
        """
        switch = ft.Switch(value=value, on_change=on_change)
        row = ft.Row(vertical_alignment=ft.CrossAxisAlignment.CENTER,
                     controls=[switch, ft.Container(
                         content=self.text(label), expand=True)])
        return row, switch

    def qty_field(self, initial: int) -> ft.TextField:
        """number field"""
        return ft.TextField(value=str(initial), label='本数', width=120,
                            text_size=self.size(1.2),
                            keyboard_type=ft.KeyboardType.NUMBER,
                            input_filter=ft.NumbersOnlyInputFilter())

    def ask(self, title: str, controls: list[ft.Control], ok_label: str,
            on_ok: Callable[[], Optional[str]],
            cancel_label: str = 'キャンセル', safe_cancel: bool = False):
        """dialog with OK / cancel

        JP:
        OK・キャンセルのダイアログ。 OK で on_ok を実行する。
        safe_cancel なら、OK が入力を消すなど取り返しのつかない操作なので、
        キャンセルの方を強調して右に置く(うっかり OK を押さないように)。
        """
        def ok(_e):
            self.page.pop_dialog()
            self.run(on_ok)

        def cancel(_e):
            self.page.pop_dialog()

        if safe_cancel:
            actions = [ft.TextButton(content=self.text(ok_label), on_click=ok),
                       ft.FilledButton(content=self.text(cancel_label),
                                       on_click=cancel)]
        else:
            actions = [ft.TextButton(content=self.text(cancel_label),
                                     on_click=cancel),
                       ft.FilledButton(content=self.text(ok_label),
                                       on_click=ok)]
        # 中身が長いとき・キーボードが出たときはダイアログの中をスクロール
        self.page.show_dialog(ft.AlertDialog(
            modal=True, scrollable=True,
            title=self.text(title, 1.2, bold=True),
            content=ft.Column(tight=True, spacing=12, controls=controls),
            actions=actions))

    def on_open(self, drug_id: int):
        """open new bottle dialog"""
        chosen = {'date': date.today()}
        name = self.drug_label(drug_id)

        # 在庫0本での開封は入庫の記録漏れのことが多いので、在庫は減らさない
        from_stock = self.db.balance(drug_id) > 0

        memo = self.memo_field()

        def ok():
            self.db.open_bottle(drug_id, chosen['date'], memo_value(memo),
                                from_stock=from_stock)
            return f"{name}: {md(chosen['date'])} 開封。" \
                   f'未開封 {self.db.balance(drug_id)}本'

        when = self.date_button(chosen['date'],
                                lambda d: chosen.update(date=d))
        self.ask(f'{name} を開封(出庫)',
                 [self.text(open_note(self.db.opened(drug_id) is not None,
                                      from_stock), 0.9,
                            color=None if from_stock else ft.Colors.ERROR),
                  when, memo], '開封(出庫)', ok)

    def on_undo_open(self, drug_id: int):
        """undo latest open dialog

        JP:
        一番新しい開封の取り消し確認ダイアログ。
        """
        row = self.db.last_open(drug_id)
        if row is None:
            return
        name = self.drug_label(drug_id)
        start = date.fromisoformat(row['use_start'])

        def ok():
            self.db.undo_open(drug_id)
            return f'{name}: {md(start)} の開封を取り消しました。' \
                   f'未開封 {self.db.balance(drug_id)}本'

        self.ask(f'{name} の開封を取り消し',
                 [self.text(f'{start.isoformat()} の開封を取り消します。'
                            '開封の履歴からこの1本を削除し、在庫に1本戻します。'
                            'この開封で空になった(使用終了にした)1本は'
                            '使用中に戻します。', 0.9)],
                 '取り消し', ok)

    def on_receive(self, drug_id: int):
        """stock in dialog"""
        chosen = {'date': date.today()}
        name = self.drug_label(drug_id)
        qty = self.qty_field(1)
        memo = self.memo_field()

        def ok():
            self.db.receive(drug_id, int(qty.value or 0), chosen['date'],
                            memo_value(memo))
            return f'{name}: 入庫。未開封 {self.db.balance(drug_id)}本'

        when = self.date_button(chosen['date'],
                                lambda d: chosen.update(date=d))
        self.ask(f'{name} を入庫(処方)', [qty, when, memo], '入庫', ok)

    def on_inventory(self, drug_id: int):
        """stocktaking dialog"""
        chosen = {'date': date.today()}
        name = self.drug_label(drug_id)
        qty = self.qty_field(self.db.balance(drug_id))
        memo = self.memo_field()

        def ok():
            self.db.inventory(drug_id, int(qty.value or 0), chosen['date'],
                              memo_value(memo))
            return f'{name}: 棚卸し。未開封 {self.db.balance(drug_id)}本'

        when = self.date_button(chosen['date'],
                                lambda d: chosen.update(date=d))
        self.ask(f'{name} を棚卸し', [
            self.text('未開封の本数を入力します。', 0.9), qty, when, memo],
            '棚卸し', ok)

    def on_add_drug(self, _e):
        """add drug dialog"""
        name = ft.TextField(label='代表目薬名(例: コソプト)',
                            text_size=self.size(1.1), autofocus=True)
        actual = ft.TextField(label='目薬名(任意。例: ドルモロール)',
                              text_size=self.size())
        max_days = ft.TextField(label='開封後の廃棄期限(日・任意)',
                                text_size=self.size(),
                                keyboard_type=ft.KeyboardType.NUMBER,
                                input_filter=ft.NumbersOnlyInputFilter())
        as_needed_row, as_needed = self.labeled_switch(AS_NEEDED_LABEL, False)

        def ok():
            if not (name.value or '').strip():
                raise ValueError('代表目薬名を入力してください')
            drug_id = self.db.add_drug(name.value.strip(),
                                       max_days=int(max_days.value)
                                       if max_days.value else None,
                                       as_needed=bool(as_needed.value))
            if (actual.value or '').strip():
                self.db.add_alias(drug_id, actual.value.strip())
            return f'{name.value.strip()} を追加しました'

        note = self.text(
            '代表目薬名(例: コソプト)を登録します。同じ効き目の薬をまとめる名前で、'
            'あとから変わりません。実際に支給される目薬(ジェネリックなど。例: '
            'ドルモロール)がこの後に変わったときは、ここではなく、各目薬の'
            '「詳細」の「目薬を追加」で追加します。', 0.9)
        self.ask('目薬追加(代表目薬名の追加)',
                 [note, name, actual, max_days, as_needed_row], '追加', ok)

    # ------------------------------------------------------------ 一括棚卸し
    def reset_bulk(self, day: Optional[date] = None):
        """reset bulk stocktaking input

        JP:
        一括棚卸しの入力を初めに戻す。本数は記録上の未開封の本数
        (day の時点。省略時今日)から始め、コメントは空にする。
        """
        self.bulk = {'date': day or date.today(), 'counts': {}, 'memo': None}

    def show_bulk_inventory(self, day: Optional[date] = None):
        """show bulk stocktaking tab (shortcut from menu)

        JP:
        一括棚卸しのタブを出す(ハンバーガーメニューのショートカット)。
        既に一括棚卸しのタブなら何もしない(入力中の本数を消さない)。
        """
        if self.tab == TAB_BULK and self.bulk is not None and day is None:
            return
        self.set_tab(TAB_BULK)
        self.reset_bulk(day)
        self.refresh()

    def bulk_dirty(self) -> bool:
        """bulk stocktaking has input not yet recorded

        JP:
        一括棚卸しに、まだ実行していない入力があるか。本数を記録上の本数から
        変えたか、一括棚卸しコメントを書いたとき。
        """
        bulk = self.bulk
        if bulk is None:
            return False
        before = bulk.get('before', {})
        return bool((bulk['memo'] or '').strip()) or any(
            qty != before.get(drug_id, qty)
            for drug_id, qty in bulk['counts'].items())

    def confirm_leave_bulk(self, go: Callable[[], None]) -> bool:
        """warn before leaving bulk stocktaking with unrecorded input

        JP:
        一括棚卸しのタブを離れてよいか。入力が実行されていなければ(bulk_dirty)
        警告ダイアログを出して False(留まる)を返す。ダイアログで
        「構わず移動」を選んだら go を呼ぶ。
        """
        if self.tab != TAB_BULK or not self.bulk_dirty():
            return True
        # 下のタブの選択を一括棚卸しに戻す
        self.refresh()
        if self.page is None:
            return False

        def discard():
            go()

        self.ask('一括棚卸しを実行していません', [self.text(
            '数え直した本数(またはコメント)は、「棚卸し実行」を押すまで'
            '記録されません。このまま移ると入力は消えます。'
            '一括棚卸しに留まるときは「留まる」を押します。', 0.9)],
            '構わず移動', discard, cancel_label='留まる',
            safe_cancel=True)
        return False

    def set_bulk_date(self, day: date):
        """change date of bulk stocktaking

        JP:
        一括棚卸しの日付を変える。本数はその日時点の記録上の本数に戻す。
        """
        self.bulk.update(date=day, counts={})
        self.refresh()

    def bulk_row(self, drug_id: int, before: int) -> ft.Control:
        """one drug of bulk stocktaking with large -/+ buttons

        JP:
        一括棚卸しの1行(目薬1つ)。大きな「－」「＋」で実際の本数に合わせる。
        押すたびに画面全体は作り直さず、この行だけ更新する(スクロール位置を保つ)。
        記録上の本数と違うときはそれが分かるように色と文言を変える。
        """
        counts = self.bulk['counts']
        # 「－」「＋」と本数は倍率に上限を付ける(BULK_MAX_SCALE)
        limit = min(1.0, BULK_MAX_SCALE / self.scale)
        count = self.text(counts[drug_id], 2.0 * limit, bold=True)
        note = self.text('', 0.85)

        def step_button(label: str, delta: int) -> ft.Control:
            return ft.FilledButton(
                content=self.text(label, 1.8 * limit, bold=True),
                tooltip='1本減らす' if delta < 0 else '1本増やす',
                style=ft.ButtonStyle(padding=ft.Padding.symmetric(
                    horizontal=24, vertical=8)),
                on_click=lambda e: step(delta))

        minus = step_button('－', -1)
        plus = step_button('＋', 1)
        row = ft.Row(spacing=16,
                     vertical_alignment=ft.CrossAxisAlignment.CENTER,
                     controls=[minus, ft.Container(
                         content=count, width=self.size(3.0 * limit),
                         alignment=ft.Alignment.CENTER), plus])

        def show():
            value = counts[drug_id]
            count.value = str(value)
            changed = value != before
            count.color = ft.Colors.SECONDARY if changed else None
            note.value = (f'記録上 {before}本 → {value}本に修正' if changed
                          else f'記録上 {before}本(同じ)')
            note.color = ft.Colors.SECONDARY if changed else None
            minus.disabled = value <= 0

        def step(delta: int):
            counts[drug_id] = max(0, counts[drug_id] + delta)
            show()
            if self.page is not None:
                card.update()

        show()
        card = ft.Card(content=ft.Container(
            padding=ft.Padding.all(12),
            content=ft.Column(spacing=8, controls=[
                self.text(self.drug_label(drug_id), 1.2, bold=True),
                note, row])))
        return card

    def build_bulk_inventory(self) -> list[ft.Control]:
        """bulk stocktaking screen

        JP:
        一括棚卸し: 使用中の目薬を1画面に並べ、未開封の本数を数え直す。
        日付は1つ(既定は今日)。「棚卸し実行」で、本数が同じ目薬も含めてすべてを
        棚卸しとして記録し(最後に数えて確かめた日が履歴に残る)、サマリーへ。
        """
        if self.bulk is None:
            self.reset_bulk()
        bulk = self.bulk
        day = bulk['date']
        counts = bulk['counts']
        drugs = self.db.list_drugs(active_only=True)
        rows = []
        # 記録上の本数(入力が変わったかを bulk_dirty で見る)
        bulk['before'] = {}
        for drug in drugs:
            drug_id = drug['drug_id']
            before = self.db.balance(drug_id, as_of=day)
            bulk['before'][drug_id] = before
            counts.setdefault(drug_id, before)
            rows.append(self.bulk_row(drug_id, before))
        # 最後の目薬のカードのすぐ下にあるので、その目薬へのコメントと
        # 紛れないよう一括棚卸し全体のコメントだと分かる名前と説明にする
        memo = self.memo_field()
        memo.label = '一括棚卸しコメント(任意)'
        memo.value = bulk['memo']

        def on_memo(e):
            bulk['memo'] = e.control.value

        memo.on_change = on_memo

        def record(_e):
            def ok():
                items = self.db.inventory_all(
                    {d['drug_id']: counts[d['drug_id']] for d in drugs},
                    day, memo_value(memo))
                self.set_tab(TAB_SUMMARY)
                return f'一括棚卸し: {inventory_result_text(items)}'
            self.run(ok)

        def reset(_e):
            self.reset_bulk(day)
            self.refresh()

        controls = [
            self.heading('一括棚卸し'),
            self.text('使用中の目薬の未開封の本数を数えて、「－」「＋」で'
                      '実際の本数に合わせます。最初は記録上の本数です。'
                      '「棚卸し実行」で、本数が同じ目薬も含めてすべてを'
                      '棚卸しとして記録し、サマリーを表示します。'
                      '日付を変えると本数はその日の記録上の本数に戻ります。'
                      '実行せずにほかのタブに移ろうとすると確認します'
                      '(移ると入力は消えます)。',
                      0.9),
            self.summary_date_button(f'日付 {day.isoformat()}', day,
                                     self.set_bulk_date),
            *rows]
        if not drugs:
            controls.append(self.text('使用中の目薬がありません。'))
        controls += [
            self.text('一括棚卸しコメント: 上のすべての目薬の棚卸しの記録に'
                      '同じコメントが入ります', 0.85),
            memo,
            ft.Row(wrap=True, spacing=8, run_spacing=8, controls=[
                ft.FilledButton(
                    content=self.text(f'棚卸し実行({len(drugs)}件)'),
                    icon=ft.Icons.CHECK, on_click=record, disabled=not drugs,
                    style=ft.ButtonStyle(padding=ft.Padding.all(14))),
                self.button('記録上の本数に戻す', reset, icon=ft.Icons.UNDO,
                            filled=False)])]
        return controls

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
                self.text(self.drug_label(drug_id), 1.3, bold=True)]),
            self.text(f"代表目薬名: {drug['name']}", 0.9),
        ]
        if not self.db.is_active(drug_id):
            controls.append(self.text(self.end_text(drug_id), 1.0,
                                      bold=True, color=ft.Colors.ERROR))
        controls += self.alias_controls(drug_id)
        controls += [
            self.text(f'未開封 {req.stock}本 / '
                      f'{opened_text(req, REMAINING_LABEL)}', 0.95),
            self.text(f'通常期間(1本あたり推定) {req.normal}日'
                      if req.normal else '通常期間(1本あたり推定): 実績なし',
                      0.9),
            self.labeled_switch(
                AS_NEEDED_LABEL, bool(drug['as_needed']),
                lambda e: self.run(lambda: self.db.update_drug(
                    drug_id, as_needed=int(e.control.value))))[0],
            # 代表目薬名ごとの利用終了・取り消しは目薬タブのカードで行う
            self.button('廃棄期限設定', lambda e: self.on_max_days(drug_id),
                        icon=ft.Icons.TIMER, filled=False),
            self.button('点眼パターン変更',
                        lambda e: self.on_change_pattern(drug_id),
                        icon=ft.Icons.EDIT_CALENDAR, filled=False),
        ]
        if drug['pattern_date']:
            controls.append(self.text(
                f"点眼パターン変更 {drug['pattern_date']}", 0.9))
        controls += [
            self.heading('開封の履歴'),
            self.text('タップでイレギュラー(推定に使わない)を切り替え。'
                      'イレギュラーより前の実績も推定に使いません', 0.8),
        ]
        today = date.today()
        rows = []
        for row in self.db.lifetimes(drug_id):  # 古い順(昇順)
            start = date.fromisoformat(row['use_start'])
            end = date.fromisoformat(row['use_end']) if row['use_end'] \
                else None
            days = ((end or today) - start).days
            label = (f"{start.isoformat()} 〜 "
                     f"{end.isoformat() if end else '使用中'}  {days}日")
            if row['irregular']:
                label += '  (イレギュラー)'
            lifetime_id, irregular = row['lifetime_id'], bool(row['irregular'])
            rows.append(self.history_row(
                label, row['note'], ft.Colors.ERROR if irregular else None,
                on_click=lambda e, i=lifetime_id, v=irregular:
                    self.run(lambda: self.db.set_irregular(i, not v))))
        controls.append(ft.Column(
            spacing=0, controls=rows,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH))
        # 開封の履歴は閲覧のみ。間違えた開封は一番新しいものだけ取り消せる
        if self.db.last_open(drug_id) is not None:
            controls.append(self.button(
                '開封の取り消し', lambda e: self.on_undo_open(drug_id),
                icon=ft.Icons.UNDO, filled=False))
        # 在庫の履歴は閲覧のみ(訂正は棚卸しで行う)
        controls.append(self.heading('在庫の履歴'))
        labels = {'in': '入庫', 'out': '出庫', 'inventory': '棚卸'}
        rows = []
        for row in self.db.stock_history(drug_id):  # 古い順(昇順)
            label = (f"{row['stock_date']} {labels[row['kind']]}"
                     f" {row['qty']}  残{row['balance']}")
            rows.append(self.history_row(label, row['note']))
        controls.append(ft.Column(
            spacing=0, controls=rows,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH))
        return controls

    def on_change_pattern(self, drug_id: int):
        """eye drop pattern change dialog

        JP:
        点眼パターン変更のダイアログ。変更日より前に開封した直近の1本
        (通常は使用中の1本)をイレギュラーにし、メモに「点眼パターン変更」と
        コメントを追記する。推定はイレギュラーより前を辿らない。
        """
        chosen = {'date': date.today()}
        name = self.drug_label(drug_id)
        memo = self.memo_field()

        def ok():
            marked = self.db.change_pattern(drug_id, chosen['date'],
                                            memo_value(memo))
            return f'{name}: 点眼パターン変更。' + (
                '直近の開封をイレギュラーにしました' if marked
                else '変更日より前の開封はありません')

        when = self.date_button(chosen['date'],
                                lambda d: chosen.update(date=d),
                                prefix='変更日')
        self.ask(f'{name} の点眼パターン変更', [
            self.text('1日の点眼回数や点眼する眼が変わったときに使います。'
                      '変更日より前に開封した直近の1本(通常は使用中の1本)を'
                      'イレギュラー(推定に使わない)にし、開封の履歴のメモに'
                      '「点眼パターン変更」と記録します。イレギュラーより前の'
                      '実績は推定に使わないので、変更後の目薬を1本使い切るまで、'
                      '必要本数は「相談」になります。', 0.9),
            when, memo], '変更', ok)

    def history_row(self, label: str, note: Optional[str], color=None,
                    on_click=None) -> ft.Control:
        """compact history row with bottom line

        JP:
        履歴の1行。 ListTile は最低の高さと余白が大きく行間が空くので、
        余白の少ない行にして下に細い区切り線を引く。
        """
        texts = [self.text(label, color=color)]
        if note:
            texts.append(self.text(note, 0.8))
        return ft.Container(
            content=ft.Column(spacing=0, controls=texts),
            padding=ft.Padding.symmetric(vertical=6, horizontal=8),
            border=ft.Border(bottom=ft.BorderSide(1, ft.Colors.OUTLINE)),
            ink=on_click is not None, on_click=on_click)

    def on_max_days(self, drug_id: int):
        """set recommended max days"""
        drug = self.db.find_drug(drug_id)
        field = ft.TextField(value=str(drug['max_days'] or ''),
                             label='開封後の廃棄期限(日・空欄で無し)',
                             text_size=self.size(),
                             keyboard_type=ft.KeyboardType.NUMBER,
                             input_filter=ft.NumbersOnlyInputFilter())
        self.ask('廃棄期限設定', [field], '設定', lambda: self.db.update_drug(
            drug_id, max_days=int(field.value) if field.value else None))

    def alias_controls(self, drug_id: int) -> list[ft.Control]:
        """actual names with period and end/restore buttons

        JP:
        目薬名の一覧。利用期間と、利用中なら「利用終了する」、
        利用終了なら「利用中に戻す」ボタン。末尾に「目薬を追加」。
        """
        rows = self.db.aliases(drug_id)
        if not rows:
            return [self.text('目薬名: 代表目薬名と同じ', 0.9),
                    self.button('目薬を追加',
                                lambda e: self.on_alias(drug_id),
                                icon=ft.Icons.LABEL, filled=False)]
        active = {r['alias_id'] for r in self.db.active_aliases(drug_id)}
        controls = [self.text('目薬名:', 0.9)]
        for row in reversed(rows):
            name = row['alias_name']
            in_use = row['alias_id'] in active
            period = f"{row['start_date'] or ''}〜" + (
                '利用中' if in_use and not row['end_date']
                else row['end_date'])
            if in_use:
                action = ft.TextButton(
                    content=self.text('利用終了する', 0.9),
                    on_click=lambda e, n=name: self.on_alias_end(drug_id, n))
            else:
                action = ft.TextButton(
                    content=self.text('利用中に戻す', 0.9),
                    on_click=lambda e, n=name: self.run(
                        lambda: self.db.end_alias(drug_id, n, '')))
            controls.append(ft.ListTile(
                title=self.text(name, 1.0, bold=in_use,
                                color=None if in_use else ft.Colors.OUTLINE),
                subtitle=self.text(period, 0.8), trailing=action))
        # 目薬(実際に支給される目薬名)の追加は目薬名リストの末尾
        controls.append(self.button('目薬を追加',
                                    lambda e: self.on_alias(drug_id),
                                    icon=ft.Icons.LABEL, filled=False))
        return controls

    def on_alias_end(self, drug_id: int, alias_name: str):
        """set end date of actual name

        JP:
        目薬名の利用終了日を設定する。すべての目薬名が利用終了すると
        その代表目薬名は利用終了扱い(サマリーに出ない)。
        """
        chosen = {'date': date.today()}

        def ok():
            self.db.end_alias(drug_id, alias_name, chosen['date'])
            if not self.db.is_active(drug_id):
                return (f'{alias_name} を利用終了にしました。目薬名が'
                        'すべて利用終了したので、この目薬は利用終了です')
            return f'{alias_name} を利用終了にしました'

        when = self.date_button(chosen['date'],
                                lambda d: chosen.update(date=d),
                                prefix='利用終了日')
        self.ask(f'{alias_name} を利用終了', [when], '利用終了', ok)

    def on_alias(self, drug_id: int):
        """change actual (supplied) drug name

        JP:
        実際に支給される名前が変わったとき、開始日とともに記録する。
        代表目薬名は変わらない。
        """
        chosen = {'date': date.today()}
        field = ft.TextField(label='実際に支給される名前(例: ドルモロール)',
                             text_size=self.size())

        def ok():
            if not (field.value or '').strip():
                raise ValueError('名前を入力してください')
            self.db.add_alias(drug_id, field.value.strip(), chosen['date'])

        when = self.date_button(chosen['date'],
                                lambda d: chosen.update(date=d),
                                prefix='開始日')
        note = self.text(f"代表目薬名({self.db.find_drug(drug_id)['name']})は"
                         '変わりません。前の名前は、使い切ったら'
                         '「利用終了」にしてください。', 0.9)
        self.ask('目薬を追加', [note, field, when], '追加', ok)

    def on_end(self, drug_id: int):
        """end using the whole representative drug

        JP:
        代表目薬名ごと(その目薬名すべて)を利用終了にする。
        目薬名1つだけを終わらせるのは詳細画面の目薬名の「利用終了」。
        """
        drug = self.db.find_drug(drug_id)
        names = [r['alias_name'] for r in self.db.active_aliases(drug_id)]
        group = f"代表目薬名 {drug['name']}"
        if names:
            group += f"(目薬名 {'・'.join(names)})"
        chosen = {'date': date.today()}

        def ok():
            self.db.update_drug(drug_id, end_date=chosen['date'])
            return f"{drug['name']} を利用終了にしました"

        when = self.date_button(chosen['date'],
                                lambda d: chosen.update(date=d),
                                prefix='利用終了日')
        note = self.text(
            f'{group}をまるごと利用終了にし、サマリーに出さないようにします。'
            '目薬名1つだけ(ジェネリックの切り替えなど)を終えるときは、'
            '詳細画面で目薬名の右の「利用終了」を使ってください。'
            '取り消すときは「利用終了した目薬も表示」から'
            '「利用中に戻す」を押します。', 0.9)
        self.ask(f"{drug['name']} をまるごと利用終了", [note, when], '利用終了',
                 ok)

    def on_restore_use(self, drug_id: int):
        """undo end of representative drug

        JP:
        利用終了を取り消す。代表目薬名の利用終了日があればそれを消す。
        目薬名がすべて利用終了して終わっている場合は、最後に終わった
        目薬名を利用中に戻す。
        """
        drug = self.db.find_drug(drug_id)
        ended = [r for r in self.db.aliases(drug_id) if r['end_date']]
        if drug['end_date']:
            detail = '利用終了を取り消します。'
        else:
            last = max(ended, key=lambda r: r['end_date'])
            detail = (f"目薬名がすべて利用終了しているので、最後に終わった"
                      f"目薬名 {last['alias_name']} を利用中に戻します。")

        def ok():
            if drug['end_date']:
                self.db.update_drug(drug_id, end_date=None)
            else:
                self.db.end_alias(drug_id, last['alias_name'], '')
            return f"{drug['name']} を利用中に戻しました"

        self.ask(f"{drug['name']} を利用中に戻す", [self.text(detail, 0.9)],
                 '利用中に戻す', ok)

    # ------------------------------------------------------------ 設定
    def build_data(self) -> list[ft.Control]:
        """data tab

        JP:
        設定: バックアップ・復元・年次更新・次回来院日の既定の期間・表示テーマ。
        """
        theme = self.db.get_meta('theme_mode') or 'dark'
        return [
            self.heading('バックアップ'),
            self.text('データはこの端末の中にだけあります。'
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
            self.heading('次回来院日の既定'),
            self.text('サマリーの次回来院日を、来院日から何日後にするかを'
                      '月・週・日で指定します(サマリーでカレンダーから'
                      '変えることもできます)。', 0.9),
            *self.span_controls(),
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

    def span_controls(self) -> list[ft.Control]:
        """default span setting field (number + unit)

        JP:
        次回来院日の既定の期間の設定欄。次回診察日は月単位・週単位で決まるので
        「数 + 単位(ヶ月/週間/日)」で入れる(1ヶ月=30日、1週間=7日で換算)。
        """
        number, unit = span_to_unit(get_default_span(self.db))
        num = ft.TextField(value=str(number), label='来院日から', width=130,
                           text_size=self.size(1.1),
                           keyboard_type=ft.KeyboardType.NUMBER,
                           input_filter=ft.NumbersOnlyInputFilter())
        unit_box = ft.Dropdown(
            value=unit, width=130, text_size=self.size(),
            options=[ft.DropdownOption(key=u, text=u) for u in SPAN_UNITS])

        def save(_e):
            def ok():
                days = set_default_span(
                    self.db, unit_to_span(num.value, unit_box.value))
                return f'次回来院日の既定を{span_label(days)}後にしました'
            self.run(ok)

        def reset(_e):
            self.run(lambda: set_default_span(self.db, DEFAULT_SPAN) and
                     f'次回来院日の既定を元に戻しました'
                     f'({span_label(DEFAULT_SPAN)}後)')

        return [
            ft.Row(spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                   controls=[num, unit_box, self.text('後')]),
            ft.Row(wrap=True, spacing=8, run_spacing=8, controls=[
                self.button('期間を設定', save, icon=ft.Icons.CHECK),
                self.button('元に戻す', reset, icon=ft.Icons.UNDO,
                            filled=False)])]

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
            if not year.value:
                raise ValueError('年を入力してください')
            result = rollover(self.db, int(year.value), out_dir)
            return (f'年次更新しました(在庫記録 {result.stock_archived}件、'
                    f'開封 {result.lifetime_archived}件を退避)。'
                    '設定タブからバックアップを保存してください')

        guard = self.text(
            '年を指定すると、その年の1月1日より前を退避します。'
            '在庫は年末の本数を繰り越します。開封の記録は、推定に使う直近3回分を'
            '必ず残すので、区切りより前の記録が一部残ることがあります。', 0.9)
        note = self.text('退避した記録は端末内の archive フォルダに残ります。'
                         '実行前にバックアップを保存しておくと安心です。', 0.9)
        self.ask('年次更新', [guard, note, year], '実行', ok)


def main(page: ft.Page):
    """flet entry point"""
    EyedropApp(page, database_path()).start()


if __name__ == '__main__':
    ft.run(main)
