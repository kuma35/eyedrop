# -*- coding: utf-8 -*-
"""backup and restore database

JP:
バックアップと復元
==================

スマホ版はデータが端末内にしか無いので、DB ファイルを丸ごと書き出して
保存・共有できるようにします。復元は書き出したファイル(または PC の
eyedrop.db)を取り込みます。

- backup_bytes: DB を sqlite の backup API で複製し、その内容を bytes で返す
  (使用中の DB でも整合性の取れたコピーになる)
- restore_bytes: bytes が eyedrop の DB か検査してから、DB ファイルを置き換える
"""
import sqlite3
import tempfile
from datetime import date
from pathlib import Path

from .drugdb import DrugDb, DrugDbError

SQLITE_HEADER = b'SQLite format 3\x00'


def backup_file_name(today=None) -> str:
    """default backup file name

    JP:
    バックアップファイルの既定の名前。例: eyedrop-backup-20260925.db
    """
    today = today or date.today()
    return f'eyedrop-backup-{today.strftime("%Y%m%d")}.db'


def backup_bytes(db: DrugDb) -> bytes:
    """consistent copy of database as bytes

    JP:
    DB の整合性の取れたコピーを bytes で返す。
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'backup.db'
        dest = sqlite3.connect(path)
        try:
            db.conn.backup(dest)
        finally:
            dest.close()
        return path.read_bytes()


def check_backup(data: bytes) -> int:
    """check bytes is eyedrop database, return number of drugs

    JP:
    bytes が eyedrop の DB か検査し、登録されている薬の数を返す。
    DB でない・drug テーブルが無い場合は DrugDbError。
    """
    if not data.startswith(SQLITE_HEADER):
        raise DrugDbError('SQLite のデータベースファイルではありません')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'check.db'
        path.write_bytes(data)
        conn = sqlite3.connect(path)
        try:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            if 'drug' not in tables or 'stock' not in tables:
                raise DrugDbError('目薬管理のデータベースではありません')
            return conn.execute('SELECT count(*) FROM drug').fetchone()[0]
        except sqlite3.DatabaseError as err:
            raise DrugDbError(f'データベースが読めません: {err}') from err
        finally:
            conn.close()


def restore_bytes(data: bytes, filename) -> int:
    """replace database file with backup bytes, return number of drugs

    JP:
    バックアップの bytes で DB ファイルを置き換え、薬の数を返す。
    検査に通ったときだけ置き換える。置き換える前の DB は
    <filename>.before-restore として残す。
    呼び出し側は置き換える前に DB を閉じ、置き換えた後に開き直すこと。
    """
    count = check_backup(data)
    path = Path(filename)
    tmp = path.with_name(path.name + '.restoring')
    tmp.write_bytes(data)
    if path.exists():
        path.replace(path.with_name(path.name + '.before-restore'))
    tmp.replace(path)
    return count
