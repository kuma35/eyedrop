# -*- coding: utf-8 -*-
"""command line interface

JP:
コマンドライン版
================

.. code-block:: shell

   python3 -m drugdb                 # 対話シェル
   python3 -m drugdb report -n 2ヶ月  # コマンドを1つ実行して終了
   python3 -m drugdb -f other.db drugs
   python3 -m drugdb -f other.db --create add コソプト  # 新規データベースを作る

データベースは -f で指定。省略時は環境変数 EYEDROP_DB、
それも無ければプロジェクト直下の eyedrop.db 。
-f や EYEDROP_DB で指定したファイルが無いとエラーになる(新規作成は --create)。
何も指定しなかったとき(既定のファイル)は無ければ新規作成する。

日付は YYYY-MM-DD 、 YYYY/MM/DD または MM/DD(今年)で指定できます。
省略すると今日です。
期間は「2ヶ月」「8週間」「60日」「60」のように指定できます(1ヶ月=30日)。
"""
import argparse
import os
import shlex
import sys
from cmd import Cmd
from datetime import date, timedelta
from functools import wraps
from pathlib import Path
from typing import Optional

from .drugdb import DRUG_COLUMNS, DrugDb, DrugDbError
from .ai_export import to_ai_prompt
from .import_ods import import_ods
from .report import (estimate_text, get_default_span, make_report,
                     opened_text, parse_span, set_default_span, span_label,
                     to_markdown, to_plain_text)
from .rollover import rollover

DEFAULT_DB = Path(__file__).resolve().parent.parent / 'eyedrop.db'


def parse_date(text: str) -> date:
    """parse date text

    JP:
    YYYY-MM-DD, YYYY/MM/DD, MM/DD(今年) を date にする。
    """
    parts = text.replace('-', '/').split('/')
    try:
        if len(parts) == 2:
            return date(date.today().year, int(parts[0]), int(parts[1]))
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        pass
    raise argparse.ArgumentTypeError(f'日付が不正です: {text}')


def parse_next(text: str) -> tuple[str, object]:
    """parse next visit (date or span)

    JP:
    次回来院日の指定。日付なら ('date', date)、期間なら ('span', 日数)。
    """
    try:
        return 'date', parse_date(text)
    except argparse.ArgumentTypeError:
        pass
    try:
        return 'span', parse_span(text)
    except ValueError as err:
        raise argparse.ArgumentTypeError(
            f'次回来院日は日付か期間(例: 11/28、2ヶ月、8週間、60日)で'
            f'指定してください: {text}') from err


def parse_span_arg(text: str) -> int:
    """argparse type of span"""
    try:
        return parse_span(text)
    except ValueError as err:
        raise argparse.ArgumentTypeError(str(err)) from err


class _Parser(argparse.ArgumentParser):
    """argparse which raises instead of exit"""
    def error(self, message):
        raise DrugDbError(f'{self.prog}: {message}')


def command(*arguments):
    """decorator: define do_xxx with argparse arguments

    JP:
    do_xxx(self, args) を argparse で引数解析するコマンドにする。
    arguments は (位置引数..., {キーワード引数}) のタプルの並び。
    """
    def decorator(func):
        name = func.__name__[3:]
        parser = _Parser(prog=name, description=func.__doc__,
                         add_help=False)
        parser.add_argument('-h', '--help', action='store_true',
                            help='ヘルプ')
        for spec in arguments:
            *flags, options = spec
            parser.add_argument(*flags, **options)

        @wraps(func)
        def wrapper(self, line):
            try:
                args = parser.parse_args(shlex.split(line))
            except DrugDbError as err:
                self.error(err)
                parser.print_help(self.stdout)
                return False
            if args.help:
                parser.print_help(self.stdout)
                return False
            try:
                return func(self, args)
            except (DrugDbError, ValueError) as err:
                self.error(err)
            return False
        wrapper.parser = parser
        return wrapper
    return decorator


def _flags_summary(parser: argparse.ArgumentParser) -> str:
    """short usage of a command's optional flags (excluding -h)

    JP:
    コマンド一覧に添える「[-a]」のようなオプション一覧(-h は除く)。
    """
    parts = []
    for action in parser._actions:  # pylint: disable=protected-access
        if not action.option_strings or action.option_strings[0] in (
                '-h', '--help'):
            continue
        flag = action.option_strings[0]
        if action.nargs == 0:
            parts.append(f'[{flag}]')
        else:
            parts.append(f'[{flag} {action.metavar or action.dest.upper()}]')
    return ' '.join(parts)


DRUG = ('drug', {'help': '薬(ID、代表目薬名または目薬名)'})
QTY = ('qty', {'type': int, 'help': '本数'})
DATE = ('-d', '--date', {'type': parse_date, 'default': None,
                         'help': '日付(省略時今日)'})
MEMO = ('-m', '--memo', {'default': None, 'help': 'メモ'})


class DrugDbShell(Cmd):
    """DrugDb shell commands

    JP:
    目薬管理の対話シェル。
    """
    intro = '目薬管理 (help でコマンド一覧、 q で終了)'
    prompt = 'eyedrop> '

    def __init__(self, db: DrugDb, stdout=None):
        super().__init__(stdout=stdout)
        self.db = db
        self.failed = False
        # 来院日(None なら今日)と次回来院日(None なら来院日 + 既定の期間)。
        # 次回来院日は ('date', 日付) か ('span', 来院日から何日後か)
        self.visit: Optional[date] = None
        self.next_visit: Optional[tuple[str, object]] = None

    def print(self, *values):
        """print to shell stdout"""
        print(*values, file=self.stdout)

    def error(self, err):
        """print error"""
        self.failed = True
        print(f'エラー: {err}', file=sys.stderr)

    def emptyline(self):
        return False

    def default(self, line):
        self.error(f'不明なコマンドです: {line}')

    def do_help(self, arg):
        """help [コマンド]: コマンド一覧またはコマンドのヘルプ"""
        func = getattr(self, f'do_{arg}', None) if arg else None
        if func is not None and hasattr(func, 'parser'):
            func.parser.print_help(self.stdout)
            return
        if arg:
            super().do_help(arg)
            return
        self.print('各サブコマンドの詳しいヘルプは -h(例: drugs -h、または help drugs)')
        for name in sorted(n[3:] for n in self.get_names()
                           if n.startswith('do_')):
            func = getattr(self, f'do_{name}')
            doc = (func.__doc__ or '').strip()
            line = f'  {name:10} {doc.splitlines()[0] if doc else ""}'
            if hasattr(func, 'parser'):
                flags = _flags_summary(func.parser)
                if flags:
                    line += f'  {flags}'
            self.print(line)

    def do_q(self, _arg):
        """終了"""
        return True

    do_quit = do_q
    do_EOF = do_q

    # ------------------------------------------------------------ drug
    @command(('-a', '--all', {'action': 'store_true',
                              'help': '使用終了した薬も表示'}))
    def do_drugs(self, args):
        """薬の一覧"""
        for drug in self.db.list_drugs(active_only=not args.all):
            name = self.db.current_name(drug['drug_id'])
            extra = [] if name == drug['name'] else [f'現在:{name}']
            if drug['as_needed']:
                extra.append('随時使用')
            if drug['max_days']:
                extra.append(f"廃棄期限{drug['max_days']}日")
            if drug['end_date']:
                extra.append(f"{drug['end_date']}終了")
            elif not self.db.is_active(drug['drug_id']):
                extra.append('目薬名がすべて利用終了')
            self.print(f"{drug['drug_id']:3} {drug['name']}"
                       f"  在庫{self.db.balance(drug['drug_id'])}"
                       + (f"  ({', '.join(extra)})" if extra else ''))

    @command(('name', {'help': '代表目薬名'}), DATE,
             ('--max-days', {'type': int,
                             'help': '開封後の廃棄期限日数(超過で info)'}),
             ('--default-days', {'type': int,
                                 'help': '実績が無いときの想定使用日数'}),
             ('--as-needed', {'action': 'store_true',
                              'help': '随時使用(必要本数を計算しない)'}),
             MEMO)
    def do_add(self, args):
        """薬を登録"""
        drug_id = self.db.add_drug(args.name, args.date, args.max_days,
                                   args.default_days, args.memo,
                                   args.as_needed)
        self.print(f'登録しました: {drug_id} {args.name}')

    @command(DRUG, ('field', {'choices': DRUG_COLUMNS, 'help': '項目'}),
             ('value', {'help': '値("-" で空にする)'}))
    def do_set(self, args):
        """薬の項目を変更(例: set キサラタン max_days 28)"""
        value = None if args.value == '-' else args.value
        if args.field == 'as_needed':
            value = int(str(value).lower() in ('1', 'yes', 'true', 'on'))
        elif value is not None and args.field.endswith('_days'):
            value = int(value)
        if value is not None and args.field.endswith('_date'):
            value = parse_date(value)
        self.db.update_drug(args.drug, **{args.field: value})

    @command(DRUG, ('name', {'help': '目薬名'}), DATE, MEMO)
    def do_alias(self, args):
        """目薬名を追加(代表目薬名はそのまま。-d で開始日)"""
        self.db.add_alias(args.drug, args.name, args.date, args.memo)

    @command(DRUG, ('name', {'help': '目薬名'}),
             ('-d', '--date', {'type': parse_date, 'default': None,
                               'help': '利用終了日(省略時今日)'}),
             ('--clear', {'action': 'store_true', 'help': '利用中に戻す'}))
    def do_endname(self, args):
        """目薬名の利用終了日を設定(全部終了した代表目薬名は利用終了扱い)"""
        self.db.end_alias(args.drug, args.name,
                          '' if args.clear else args.date)

    @command(DRUG, ('text', {'help': 'メモ'}), DATE)
    def do_note(self, args):
        """日付付きメモを追加"""
        self.db.add_note(args.drug, args.text, args.date or date.today())

    @command(DRUG, ('-d', '--date', {'type': parse_date, 'default': None,
                                     'help': '使用終了日(省略時今日)'}))
    def do_end(self, args):
        """薬の使用を終了(サマリーに出さない)"""
        self.db.update_drug(args.drug, end_date=args.date or date.today())

    @command(DRUG)
    def do_show(self, args):
        """薬の詳細"""
        drug = self.db.find_drug(args.drug)
        drug_id = drug['drug_id']
        self.print(f"{drug_id}: {drug['name']}  開始 {drug['start_date']}"
                   + (f"  終了 {drug['end_date']}" if drug['end_date']
                      else ''))
        if drug['as_needed']:
            self.print('  随時使用')
        if drug['pattern_date']:
            self.print(f"  点眼パターン変更 {drug['pattern_date']}")
        for key in ('max_days', 'default_days', 'note'):
            if drug[key] is not None:
                self.print(f'  {key}: {drug[key]}')
        for row in self.db.aliases(drug_id):
            self.print(f"  目薬名: {row['start_date']}〜"
                       f"{row['end_date'] or '(利用中)'} {row['alias_name']}")
        for row in self.db.notes(drug_id):
            self.print(f"  メモ: {row['note_date'] or ''} {row['text']}")
        for row in self.db.summaries(drug_id):
            self.print(f"  過去年値 {row['year']}: 平均{row['avg_days']:.1f}"
                       f"日 ({row['count']}本 {row['min_days']}"
                       f"〜{row['max_days']}日)")
        req = self.db.requirement(drug_id, span=0)
        self.print(f'  {estimate_text(req)}')
        self.print(f'  未開封在庫: {req.stock}本 / {opened_text(req)}')

    # ------------------------------------------------------------ stock
    @command(DRUG, QTY, DATE, MEMO)
    def do_in(self, args):
        """入庫(処方された)"""
        self.db.receive(args.drug, args.qty, args.date, args.memo)
        self.print(f'在庫: {self.db.balance(args.drug)}')

    @command(DRUG, QTY, DATE, MEMO)
    def do_out(self, args):
        """出庫(開封以外で在庫が減った。開封は open)"""
        self.db.add_stock(args.drug, 'out', args.qty, args.date, args.memo)
        self.print(f'在庫: {self.db.balance(args.drug)}')

    @command(DRUG, QTY, DATE, MEMO)
    def do_inv(self, args):
        """棚卸し(未開封の在庫数を qty とする)"""
        self.db.inventory(args.drug, args.qty, args.date, args.memo)

    @command(DRUG)
    def do_stock(self, args):
        """在庫の履歴"""
        labels = {'in': '入庫', 'out': '出庫', 'inventory': '棚卸'}
        for row in self.db.stock_history(args.drug):
            self.print(f"{row['stock_id']:5} {row['stock_date']}"
                       f" {labels[row['kind']]} {row['qty']:2}"
                       f"  残{row['balance']:2}  {row['note'] or ''}")

    @command(('stock_id', {'type': int, 'help': '在庫記録ID(stock で表示)'}))
    def do_delstock(self, args):
        """在庫記録を削除(訂正用)"""
        self.db.delete_stock(args.stock_id)

    # ------------------------------------------------------------ lifetime
    @command(DRUG, DATE, MEMO,
             ('--no-stock', {'action': 'store_true',
                             'help': '在庫から出庫しない'}))
    def do_open(self, args):
        """開封(在庫から1本出して使い始める。前の1本は使用終了)"""
        self.db.open_bottle(args.drug, args.date, args.memo,
                            from_stock=not args.no_stock)
        self.print(f'在庫: {self.db.balance(args.drug)}')

    @command(DRUG)
    def do_undoopen(self, args):
        """一番新しい開封を取り消す(在庫を戻し、前の1本を使用中に戻す)"""
        done = self.db.undo_open(args.drug)
        self.print(f"取り消しました: {done['lifetime']['use_start']} の開封"
                   f'  在庫: {self.db.balance(args.drug)}')

    @command(DRUG, DATE, MEMO,
             ('-i', '--irregular', {'action': 'store_true',
                                    'help': 'イレギュラー(中止・紛失等)'}))
    def do_finish(self, args):
        """開封中の1本を使用終了(次を開封しない場合)"""
        self.db.finish_bottle(args.drug, args.date, args.irregular,
                              args.memo)

    @command(DRUG, ('-d', '--date', {'type': parse_date, 'default': None,
                                     'help': '変更日(省略時今日)'}), MEMO)
    def do_pattern(self, args):
        """点眼パターン変更(直近の開封をイレギュラーにし、それより前を推定に使わない)"""
        marked = self.db.change_pattern(args.drug, args.date, args.memo)
        self.print('点眼パターン変更: ' + (
            f'ライフタイム {marked} をイレギュラーにしました' if marked
            else '変更日より前の開封はありません'))

    @command(('lifetime_id', {'type': int,
                              'help': 'ライフタイムID(life で表示)'}),
             ('--clear', {'action': 'store_true', 'help': '解除'}), MEMO)
    def do_irregular(self, args):
        """ライフタイムをイレギュラー(推定に使わない)にする"""
        self.db.set_irregular(args.lifetime_id, not args.clear, args.memo)

    @command(('lifetime_id', {'type': int,
                              'help': 'ライフタイムID(life で表示)'}))
    def do_dellife(self, args):
        """ライフタイムを削除(訂正用)"""
        self.db.delete_lifetime(args.lifetime_id)

    @command(DRUG)
    def do_life(self, args):
        """ライフタイムの履歴"""
        today = date.today()
        for row in self.db.lifetimes(args.drug):
            end = row['use_end'] or '(使用中)'
            last = date.fromisoformat(row['use_end']) if row['use_end'] \
                else today
            days = (last - date.fromisoformat(row['use_start'])).days
            mark = '*' if row['irregular'] else ' '
            self.print(f"{row['lifetime_id']:5}{mark}{row['use_start']}"
                       f" 〜 {end:10} {days:3}日  {row['note'] or ''}")

    # ------------------------------------------------------------ report
    def visit_dates(self, visit=None, next_visit=None) -> tuple[date, date]:
        """(visit date, next visit date) from args or session settings

        JP:
        来院日と次回来院日。引数、無ければ visit・next で設定した値、
        それも無ければ今日と来院日 + 既定の期間。
        """
        visit = visit or self.visit or date.today()
        kind, value = next_visit or self.next_visit or (
            'span', get_default_span(self.db))
        if kind == 'span':
            value = visit + timedelta(days=value)
        if value <= visit:
            raise ValueError(f'次回来院日 {value} は来院日 {visit} より'
                             '後の日付にしてください')
        return visit, value

    def print_visit(self):
        """print visit and next visit dates"""
        visit, next_visit = self.visit_dates()
        self.print(f'来院日 {visit}'
                   + ('' if self.visit else '(今日)'))
        self.print(f'次回来院日 {next_visit}({(next_visit - visit).days}日後)'
                   + ('' if self.next_visit else
                      f'(既定: {span_label(get_default_span(self.db))}後)'))

    @command(('date', {'type': parse_date, 'nargs': '?', 'default': None,
                       'help': '来院日(省略時は表示のみ)'}),
             ('-r', '--reset', {'action': 'store_true',
                                'help': '今日に戻す'}))
    def do_visit(self, args):
        """来院日を設定・表示(report の基準日。既定は今日)"""
        if args.reset:
            self.visit = None
        elif args.date:
            self.visit = args.date
        self.print_visit()

    @command(('when', {'type': parse_next, 'nargs': '?', 'default': None,
                       'metavar': '日付|期間',
                       'help': '次回来院日(例: 11/28)または来院日からの期間'
                               '(例: 2ヶ月、8週間、60日)。省略時は表示のみ'}),
             ('-r', '--reset', {'action': 'store_true',
                                'help': '既定(来院日 + interval の期間)に戻す'}))
    def do_next(self, args):
        """次回来院日を設定・表示(既定は来院日 + interval の期間)"""
        if args.reset:
            self.next_visit = None
        elif args.when:
            self.visit_dates(next_visit=args.when)
            self.next_visit = args.when
        self.print_visit()

    @command(('span', {'type': parse_span_arg, 'nargs': '?', 'default': None,
                       'metavar': '期間',
                       'help': '例: 2ヶ月、8週間、60日。省略時は表示のみ'}))
    def do_interval(self, args):
        """次回来院日の既定(来院日から何日後か)を設定・表示"""
        if args.span:
            set_default_span(self.db, args.span)
        days = get_default_span(self.db)
        self.print(f'次回来院日の既定: 来院日の{span_label(days)}後({days}日後)')

    @command(('-v', '--visit', {'type': parse_date, 'default': None,
                                'metavar': 'DATE',
                                'help': '来院日(省略時は visit の設定、'
                                        '無ければ今日)'}),
             ('-n', '--next', {'type': parse_next, 'default': None,
                               'dest': 'next_visit', 'metavar': '日付|期間',
                               'help': '次回来院日または来院日からの期間'
                                       '(省略時は next の設定、無ければ'
                                       ' interval の期間後)'}),
             ('--margin', {'type': int, 'default': 0,
                           'help': '余裕日数'}),
             ('--plain', {'action': 'store_true',
                          'help': 'Markdown ではなくテキスト版で出力'
                                  '(Evernote アプリなど書式なしで貼る先向け)'}),
             ('--ai', {'action': 'store_true',
                       'help': 'チャットAI用(指示 + JSON)で出力'}),
             ('-o', '--output', {'default': None, 'metavar': 'FILE',
                                 'help': 'ファイルにも出力'}))
    def do_report(self, args):
        """受診前サマリー(来院日から次回来院日までの必要本数)"""
        visit, next_visit = self.visit_dates(args.visit, args.next_visit)
        report = make_report(self.db, today=visit, next_visit=next_visit,
                             margin_days=args.margin)
        if args.ai:
            text = to_ai_prompt(report)
        elif args.plain:
            text = to_plain_text(report)
        else:
            text = to_markdown(report)
        self.stdout.write(text)
        if args.output:
            Path(args.output).write_text(text, encoding='utf-8')
            print(f'出力しました: {args.output}', file=sys.stderr)

    # ------------------------------------------------------------ maintenance
    @command(('year', {'type': int, 'nargs': '?', 'default': None,
                       'help': 'この年の1月1日より前を退避(既定: 昨年)'}),
             ('-o', '--out', {'default': 'archive',
                              'help': '出力ディレクトリ(既定 archive)'}))
    def do_rollover(self, args):
        """年次更新(バックアップ・エクスポート・在庫繰越)"""
        year = args.year or date.today().year - 1
        result = rollover(self.db, year, args.out)
        self.print(f'バックアップ: {result.backup}')
        self.print(f'エクスポート: {result.export_dir}')
        self.print(f'退避: 在庫記録 {result.stock_archived}件、'
                   f'ライフタイム {result.lifetime_archived}件')
        for name, qty in result.carried.items():
            self.print(f'  繰越 {name}: {max(qty, 0)}本'
                       + ('' if qty >= 0 else
                          f' (計算上 {qty}本のため0本で繰越)'))

    @command(('path', {'help': 'ods ファイル'}))
    def do_import(self, args):
        """スプレッドシート(eyedrop-stock.ods)を取り込む"""
        for res in import_ods(self.db, args.path):
            self.print(f'{res.name}: 名前{res.aliases} メモ{res.notes}'
                       f' ライフタイム{res.lifetimes} 在庫記録{res.stocks}'
                       + (f' ({res.ended} 使用終了)' if res.ended else ''))
            for msg in res.mismatches:
                self.print(f'  残高不一致 {msg}')
            for msg in res.warnings:
                self.print(f'  要確認 {msg}')


def main(argv=None) -> int:
    """entry point

    JP:
    エントリポイント。コマンドが無ければ対話シェル。
    -f(または環境変数 EYEDROP_DB)で指定したファイルが無ければエラーにする
    (誤ったパスを指定すると気づかずに空の新規データベースを見てしまうため)。
    新しく作りたいときは --create を付ける。どちらも指定しなければ既定の
    ファイル(プロジェクト直下の eyedrop.db)を使い、無ければ新規作成する。
    """
    parser = argparse.ArgumentParser(
        prog='drugdb', description='目薬の在庫・ライフタイム管理')
    parser.add_argument('-f', '--file', dest='filename', default=None,
                        metavar='FILENAME',
                        help='データベースファイル(省略時は環境変数 EYEDROP_DB'
                             'か既定のファイル)。指定した場合、無ければエラー'
                             '(新規作成は --create)')
    parser.add_argument('--create', action='store_true',
                        help='指定したファイルが無ければ新しく作成する')
    parser.add_argument('command', nargs=argparse.REMAINDER,
                        help='実行するコマンド(省略時は対話シェル)')
    args = parser.parse_args(argv)
    filename = args.filename or os.environ.get('EYEDROP_DB')
    explicit = filename is not None
    if not explicit:
        filename = str(DEFAULT_DB)
    if explicit and not args.create and not Path(filename).exists():
        parser.error(f'データベースファイルが見つかりません: {filename}'
                     '(新しく作る場合は --create)')
    with DrugDb(filename) as db:
        shell = DrugDbShell(db)
        if args.command:
            shell.onecmd(shlex.join(args.command))
            return 1 if shell.failed else 0
        try:
            shell.cmdloop()
        except KeyboardInterrupt:
            print()
    return 0
