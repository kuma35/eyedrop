# -*- coding: utf-8 -*-
"""database operations

JP:
データベース操作
================

在庫管理(入庫・出庫・棚卸し)とライフタイム管理(開封日からの経過日数)を
行います。コマンドライン版は ``python3 -m drugdb`` で起動します
(cli.py 参照)。

Kivy には依存しません。 GUI からも同じクラスを使います。
"""
import logging
import sqlite3
from datetime import date
from typing import Optional

from . import sql_edit as E
from .estimate import (Estimate, Requirement, estimate_days, requirement,
                       to_date)
from .sql_table import ADD_COLUMNS, CREATE_TABLES, INDEXES, SCHEMA_VERSION

logger = logging.getLogger(__name__)

STOCK_KINDS = ('in', 'out', 'inventory')

# 終了日なしで残った古い開封を直したときのメモ
STALE_NOTE = '(終了日なしのため次の開封日で終了扱い)'

# 更新を許可する drug の列
DRUG_COLUMNS = ('name', 'start_date', 'end_date', 'max_days',
                'default_days', 'as_needed', 'note')


class DrugDbError(Exception):
    """error for DrugDb operations

    JP:
    DrugDb 操作のエラー(薬が見つからない等)。
    """


def iso(value=None) -> str:
    """date (or ISO string, None=today) to ISO string

    JP:
    日付を 'YYYY-MM-DD' 文字列にする。 None なら今日。
    """
    if value is None:
        return date.today().isoformat()
    return to_date(value).isoformat()


def _add_columns(conn: sqlite3.Connection):
    """add columns missing in tables created by older version

    JP:
    旧バージョンで作成済のテーブルに無い列を追加する。
    """
    for table, columns in ADD_COLUMNS.items():
        exists = {row['name'] for row in
                  conn.execute(f'PRAGMA table_info({table});')}
        for name, definition in columns:
            if name not in exists:
                conn.execute(
                    f'ALTER TABLE {table} ADD COLUMN {name} {definition};')
                logger.info('DrugDb: add column %s.%s', table, name)


def _open_database(filename: str) -> sqlite3.Connection:
    """open database and create tables if not exist

    JP:
    指定のファイル名のデータベースを開き、無いテーブルを作成します。

    エラー
    ......

    sqlite3.OperationalError 'unable to open database file':
    filename のファイルが作成できなかった。たぶん書き込み権限の無い場所に
    新しく filename を作ろうとしています。

    sqlite3.OperationalError 'attempt to write a readonly database':
    読み取り専用のファイルを指定した。既にあるファイルなら connect() は
    正常に終了し、代わりにテーブル作成時にこのエラーになります。
    """
    try:
        conn = sqlite3.connect(filename)
    except sqlite3.OperationalError:
        logger.critical('DrugDb: can not open db:%s', filename)
        raise
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON;')
    try:
        with conn:
            for sql in CREATE_TABLES.values():
                conn.execute(sql)
            _add_columns(conn)
            conn.executescript(INDEXES)
            conn.execute(E.SET_META, {'key': 'schema_version',
                                      'value': str(SCHEMA_VERSION)})
    except sqlite3.OperationalError as msg:
        logger.critical('DrugDb: %s:%s', msg.args[0], filename)
        conn.close()
        raise
    return conn


class DrugDb():
    """database I/O

    JP:
    データベース入出力。
    """
    def __init__(self, filename: str):
        self.filename = filename
        self.conn = _open_database(filename)

    def close(self):
        """close connection"""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------ drug
    def add_drug(self, name: str, start_date=None,
                 max_days: Optional[int] = None,
                 default_days: Optional[int] = None,
                 note: Optional[str] = None,
                 as_needed: bool = False) -> int:
        """register new drug, return drug_id

        JP:
        薬を登録し drug_id を返す。
        """
        try:
            with self.conn:
                cur = self.conn.execute(E.NEW_DRUG, {
                    'name': name, 'start_date': iso(start_date),
                    'max_days': max_days, 'default_days': default_days,
                    'note': note, 'as_needed': int(as_needed)})
        except sqlite3.IntegrityError as err:
            raise DrugDbError(f'同じ代表目薬名の目薬が既にあります: {name}') \
                from err
        return cur.lastrowid

    def find_drug(self, key) -> sqlite3.Row:
        """find drug by id, name or alias name

        JP:
        drug_id、登録名、別名(現在・過去の薬の名前)のいずれかで薬を探す。
        """
        if isinstance(key, int) or str(key).isdigit():
            rows = self.conn.execute(
                E.FIND_DRUG_BY_ID, {'key': int(key)}).fetchall()
        else:
            rows = self.conn.execute(
                E.FIND_DRUG_BY_NAME, {'key': key}).fetchall()
        if not rows:
            raise DrugDbError(f'薬が見つかりません: {key}')
        if len(rows) > 1:
            names = ', '.join(f"{r['drug_id']}:{r['name']}" for r in rows)
            raise DrugDbError(f'薬が特定できません: {key} ({names})')
        return rows[0]

    def list_drugs(self, active_only: bool = False) -> list[sqlite3.Row]:
        """list drugs

        JP:
        薬の一覧。 active_only なら利用中のものだけ(is_active 参照)。
        """
        rows = self.conn.execute(E.LIST_DRUGS).fetchall()
        if active_only:
            rows = [r for r in rows if self.is_active(r['drug_id'])]
        return rows

    def is_active(self, key, as_of=None) -> bool:
        """drug is in use

        JP:
        利用中か。代表目薬名の使用終了日(drug.end_date)が無く、かつ
        目薬名が1件も無いか、利用中の目薬名が1件以上あるとき。
        """
        drug = self.find_drug(key)
        if drug['end_date'] is not None:
            return False
        rows = self.aliases(drug['drug_id'])
        return not rows or bool(self.active_aliases(drug['drug_id'], as_of))

    def update_drug(self, key, **values):
        """update drug columns

        JP:
        薬の列を更新する。例: update_drug('キサラタン', max_days=28)
        """
        drug_id = self.find_drug(key)['drug_id']
        try:
            with self.conn:
                for column, value in values.items():
                    if column not in DRUG_COLUMNS:
                        raise DrugDbError(f'更新できない項目です: {column}')
                    if column.endswith('_date') and value is not None:
                        value = iso(value)
                    self.conn.execute(E.UPDATE_DRUG.format(column=column),
                                      {'value': value, 'drug_id': drug_id})
        except sqlite3.IntegrityError as err:
            raise DrugDbError(f'同じ代表目薬名の目薬が既にあります: '
                              f"{values.get('name')}") from err

    def add_alias(self, key, alias_name: str, start_date=None,
                  note: Optional[str] = None) -> int:
        """add current drug name (generic etc.)

        JP:
        実際に貰っている薬の名前(ジェネリック等)を追加する。
        """
        drug_id = self.find_drug(key)['drug_id']
        with self.conn:
            cur = self.conn.execute(E.NEW_ALIAS, {
                'drug_id': drug_id, 'alias_name': alias_name,
                'start_date': iso(start_date), 'note': note})
        return cur.lastrowid

    def aliases(self, key) -> list[sqlite3.Row]:
        """actual name history, oldest first"""
        drug_id = self.find_drug(key)['drug_id']
        return self.conn.execute(E.LIST_ALIASES,
                                 {'drug_id': drug_id}).fetchall()

    def active_aliases(self, key, as_of=None) -> list[sqlite3.Row]:
        """actual names in use

        JP:
        利用中の目薬名(利用終了日が空欄か、as_of(省略時今日)以降)。
        """
        day = iso(as_of)
        return [r for r in self.aliases(key)
                if r['end_date'] is None or r['end_date'] >= day]

    def end_alias(self, key, alias_name: str, end_date=None) -> int:
        """set end date of actual name (None: back in use)

        JP:
        目薬名の利用終了日を設定する。 end_date に '' を渡すと
        利用中に戻す。同じ名前が複数あれば一番新しいもの。
        """
        rows = [r for r in self.aliases(key) if r['alias_name'] == alias_name]
        if not rows:
            raise DrugDbError(f'目薬名がありません: {alias_name}')
        value = None if end_date == '' else iso(end_date)
        with self.conn:
            self.conn.execute(E.SET_ALIAS_END, {
                'end_date': value, 'alias_id': rows[-1]['alias_id']})
        return rows[-1]['alias_id']

    def current_name(self, key) -> str:
        """current drug name

        JP:
        現在の目薬名。利用中の名前が複数(切替時期)なら「・」でつなぐ。
        目薬名が無ければ代表目薬名。すべて利用終了なら最後の名前。
        """
        drug = self.find_drug(key)
        rows = self.aliases(drug['drug_id'])
        if not rows:
            return drug['name']
        active = self.active_aliases(drug['drug_id'])
        if not active:
            return rows[-1]['alias_name']
        return '・'.join(r['alias_name'] for r in active)

    def add_note(self, key, text: str, note_date=None) -> int:
        """add dated note

        JP:
        日付付きメモを追加する。 note_date が None なら日付なし。
        """
        drug_id = self.find_drug(key)['drug_id']
        with self.conn:
            cur = self.conn.execute(E.NEW_NOTE, {
                'drug_id': drug_id, 'text': text,
                'note_date': iso(note_date) if note_date else None})
        return cur.lastrowid

    def notes(self, key) -> list[sqlite3.Row]:
        """dated notes"""
        drug_id = self.find_drug(key)['drug_id']
        return self.conn.execute(E.LIST_NOTES,
                                 {'drug_id': drug_id}).fetchall()

    # ------------------------------------------------------------ stock
    def add_stock(self, key, kind: str, qty: int, stock_date=None,
                  note: Optional[str] = None) -> int:
        """add stock record

        JP:
        在庫記録を追加する。 kind は 'in' 入庫, 'out' 出庫,
        'inventory' 棚卸し。
        """
        if kind not in STOCK_KINDS:
            raise DrugDbError(f'kind が不正です: {kind}')
        if qty < 0:
            raise DrugDbError(f'数量が負です: {qty}')
        drug_id = self.find_drug(key)['drug_id']
        with self.conn:
            cur = self.conn.execute(E.NEW_STOCK, {
                'drug_id': drug_id, 'stock_date': iso(stock_date),
                'kind': kind, 'qty': qty, 'note': note})
        return cur.lastrowid

    def receive(self, key, qty: int, stock_date=None, note=None) -> int:
        """stock in (prescription)

        JP:
        入庫(処方)。
        """
        return self.add_stock(key, 'in', qty, stock_date, note)

    def inventory(self, key, qty: int, stock_date=None, note=None) -> int:
        """stocktaking

        JP:
        棚卸し。その時点の在庫数を qty とする。
        """
        return self.add_stock(key, 'inventory', qty, stock_date, note)

    def delete_stock(self, stock_id: int):
        """delete stock record (for correction)

        JP:
        在庫記録を削除する(誤入力の訂正用)。
        """
        with self.conn:
            cur = self.conn.execute(E.DELETE_STOCK, {'stock_id': stock_id})
        if cur.rowcount == 0:
            raise DrugDbError(f'在庫記録がありません: {stock_id}')

    def stock_history(self, key) -> list[dict]:
        """stock records with running balance

        JP:
        在庫記録と、その時点の残高(balance)。
        """
        drug_id = self.find_drug(key)['drug_id']
        balance = 0
        result = []
        for row in self.conn.execute(E.LIST_STOCK, {'drug_id': drug_id}):
            if row['kind'] == 'in':
                balance += row['qty']
            elif row['kind'] == 'out':
                balance -= row['qty']
            else:
                balance = row['qty']
            item = dict(row)
            item['balance'] = balance
            result.append(item)
        return result

    def balance(self, key, as_of=None) -> int:
        """unopened stock count (as of date, inclusive)

        JP:
        未開封の在庫数。 as_of を指定するとその日(を含む)時点の在庫数。
        """
        limit = iso(as_of) if as_of is not None else None
        balance = 0
        for row in self.stock_history(key):
            if limit is not None and row['stock_date'] > limit:
                break
            balance = row['balance']
        return balance

    # ------------------------------------------------------------ lifetime
    def open_bottle(self, key, open_date=None, note=None,
                    from_stock: bool = True) -> int:
        """open new bottle

        JP:
        新しい1本を開封する。
        開封中のもの(一番新しい1件)を開封日で使用終了とし、新しい
        ライフタイムを開始する。 from_stock なら在庫から1本出庫する。
        古い開封中が残っていても一緒に終わらせない(異常に長い使用期間に
        なるため。 close_stale_lifetimes 参照)。
        """
        drug_id = self.find_drug(key)['drug_id']
        day = iso(open_date)
        with self.conn:
            for row in self.conn.execute(E.OPEN_LIFETIME,
                                         {'drug_id': drug_id}).fetchall()[:1]:
                if row['use_start'] > day:
                    raise DrugDbError(
                        f"開封日 {day} が使用中の開封日 {row['use_start']}"
                        ' より前です')
                self.conn.execute(E.CLOSE_LIFETIME, {
                    'use_end': day, 'lifetime_id': row['lifetime_id']})
            if from_stock:
                self.conn.execute(E.NEW_STOCK, {
                    'drug_id': drug_id, 'stock_date': day, 'kind': 'out',
                    'qty': 1, 'note': note})
            cur = self.conn.execute(E.NEW_LIFETIME, {
                'drug_id': drug_id, 'use_start': day, 'use_end': None,
                'irregular': 0, 'note': note})
        return cur.lastrowid

    def close_stale_lifetimes(self, key=None) -> list[dict]:
        """close old open lifetimes left by import

        JP:
        開封中(終了日なし)のまま残った古いライフタイムを直す。
        一番新しい開封中以外で終了日が無いものは、次の開封日で終了とし、
        イレギュラー(推定に使わない)にする。 ods で終了日の欄が空だった
        記録など。 key を省略すると全部の薬。直したものを返す。
        """
        drugs = [self.find_drug(key)] if key is not None \
            else self.list_drugs()
        fixed = []
        with self.conn:
            for drug in drugs:
                rows = self.conn.execute(E.LIST_LIFETIME, {
                    'drug_id': drug['drug_id']}).fetchall()
                for index, row in enumerate(rows[:-1]):
                    if row['use_end'] is not None:
                        continue
                    later = [r['use_start'] for r in rows[index + 1:]
                             if r['use_start'] > row['use_start']]
                    if not later:
                        continue
                    note = ((row['note'] + ' ') if row['note'] else '') \
                        + STALE_NOTE
                    self.conn.execute(
                        'UPDATE lifetime SET use_end = ?, irregular = 1,'
                        ' note = ? WHERE lifetime_id = ?',
                        (later[0], note, row['lifetime_id']))
                    fixed.append({'name': drug['name'],
                                  'lifetime_id': row['lifetime_id'],
                                  'use_start': row['use_start'],
                                  'use_end': later[0]})
        return fixed

    def finish_bottle(self, key, end_date=None, irregular: bool = False,
                      note=None) -> int:
        """finish opened bottle without opening next

        JP:
        次を開封せずに開封中の1本を使用終了にする(中止・紛失等)。
        """
        drug_id = self.find_drug(key)['drug_id']
        rows = self.conn.execute(E.OPEN_LIFETIME,
                                 {'drug_id': drug_id}).fetchall()
        if not rows:
            raise DrugDbError('開封中のものがありません')
        lifetime_id = rows[0]['lifetime_id']
        with self.conn:
            self.conn.execute(E.CLOSE_LIFETIME, {
                'use_end': iso(end_date), 'lifetime_id': lifetime_id})
            if irregular or note:
                self.conn.execute(E.SET_IRREGULAR, {
                    'irregular': int(irregular), 'note': note,
                    'lifetime_id': lifetime_id})
        return lifetime_id

    def add_lifetime(self, key, use_start, use_end=None,
                     irregular: bool = False, note=None) -> int:
        """add lifetime record directly (for import)

        JP:
        ライフタイムを直接追加する(取り込み用。在庫は動かさない)。
        """
        drug_id = self.find_drug(key)['drug_id']
        with self.conn:
            cur = self.conn.execute(E.NEW_LIFETIME, {
                'drug_id': drug_id, 'use_start': iso(use_start),
                'use_end': iso(use_end) if use_end else None,
                'irregular': int(irregular), 'note': note})
        return cur.lastrowid

    def set_irregular(self, lifetime_id: int, irregular: bool = True,
                      note=None):
        """mark lifetime record as irregular

        JP:
        ライフタイムをイレギュラー(推定に使わない)にする/戻す。
        """
        with self.conn:
            cur = self.conn.execute(E.SET_IRREGULAR, {
                'irregular': int(irregular), 'note': note,
                'lifetime_id': lifetime_id})
        if cur.rowcount == 0:
            raise DrugDbError(f'ライフタイムがありません: {lifetime_id}')

    def delete_lifetime(self, lifetime_id: int):
        """delete lifetime record (for correction)"""
        with self.conn:
            cur = self.conn.execute(E.DELETE_LIFETIME,
                                    {'lifetime_id': lifetime_id})
        if cur.rowcount == 0:
            raise DrugDbError(f'ライフタイムがありません: {lifetime_id}')

    def lifetimes(self, key, as_of=None) -> list:
        """lifetime records, oldest first

        JP:
        ライフタイムを開封日の古い順に返す。
        as_of を指定するとその日時点の状態(その日以前の開封分だけ。
        その日より後に終了したものは使用中 use_end=None 扱い)を dict で返す。
        """
        drug_id = self.find_drug(key)['drug_id']
        rows = self.conn.execute(E.LIST_LIFETIME,
                                 {'drug_id': drug_id}).fetchall()
        if as_of is None:
            return rows
        limit = iso(as_of)
        result = []
        for row in rows:
            if row['use_start'] > limit:
                continue
            item = dict(row)
            if item['use_end'] is not None and item['use_end'] > limit:
                item['use_end'] = None
            result.append(item)
        return result

    def opened(self, key, as_of=None):
        """opened lifetime record (as of date) or None

        JP:
        開封中のライフタイム。無ければ None。
        as_of を指定するとその日時点で開封中だったもの。
        """
        drug_id = self.find_drug(key)['drug_id']
        if as_of is None:
            return self.conn.execute(E.OPEN_LIFETIME,
                                     {'drug_id': drug_id}).fetchone()
        rows = [row for row in self.lifetimes(drug_id, as_of)
                if row['use_end'] is None]
        return rows[-1] if rows else None

    def summaries(self, key) -> list[sqlite3.Row]:
        """past years lifetime summary"""
        drug_id = self.find_drug(key)['drug_id']
        return self.conn.execute(E.LIST_SUMMARY,
                                 {'drug_id': drug_id}).fetchall()

    def estimate(self, key, as_of=None, **kwargs) -> Estimate:
        """estimated days per bottle

        JP:
        1本の推定使用日数。 as_of を指定するとその日までの実績で推定。
        """
        drug = self.find_drug(key)
        return estimate_days(self.lifetimes(drug['drug_id'], as_of),
                             self.summaries(drug['drug_id']),
                             default_days=drug['default_days'], **kwargs)

    def requirement(self, key, span: int, today=None, margin_days: int = 0,
                    **kwargs) -> Requirement:
        """required count until next visit

        JP:
        次回受診(today + span 日後)までの必要本数と依頼数。
        在庫・開封中・推定は today 時点の記録で計算する(過去日付でも可)。
        """
        drug = self.find_drug(key)
        today = to_date(iso(today))
        opened = self.opened(drug['drug_id'], as_of=today)
        return requirement(
            stock=self.balance(drug['drug_id'], as_of=today),
            est=self.estimate(drug['drug_id'], as_of=today, **kwargs),
            opened=opened['use_start'] if opened else None,
            today=today, span=span, max_days=drug['max_days'],
            margin_days=margin_days, as_needed=bool(drug['as_needed']))

    # ------------------------------------------------------------ meta
    def get_meta(self, key: str) -> Optional[str]:
        """get meta value"""
        row = self.conn.execute(E.GET_META, {'key': key}).fetchone()
        return row['value'] if row else None

    def set_meta(self, key: str, value: str):
        """set meta value"""
        with self.conn:
            self.conn.execute(E.SET_META, {'key': key, 'value': value})
