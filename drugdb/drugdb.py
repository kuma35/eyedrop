# -*- coding: utf-8 -*-
"""
データベース操作
================

- if __main__ ではコマンドライン版が動く

"""
import sqlite3
from kivy.logger import Logger
from sql_create_tables import CREATE_TABLES


class DrugDb():
    """database I/O"""
    def __init__(self, filename: str):
        """open database and checking exist tables

        指定のファイル名のデータベースを開きます。

        エラー
        ......

        sqlite3.OperationalError as msg:
        msg.args[0] = 'unable to open database file'

        filenameのファイルが作成できなかった、
        たぶん書き込み権限の無い場所に新しく filename を作ろう
        としています。

        一方、読み取り専用のファイルを指定しても既にある
        ファイルなら connect() は正常に終了します。
        代わりに execute() で
        sqlite3.OperationalError as msg:
        msg.args[0] = 'attempt to write a readonly database'
        になります。
        """
        try:
            self.conn = sqlite3.connect(filename)
        except sqlite3.OperationalError as msg:
            if msg.args[0] == 'unable to open database file':
                raise
            Logger.debug(f'DrugDb: {msg.args[0]}:connect({filename})')
        self.conn.row_factory = sqlite3.Row
        for table_name, sql in CREATE_TABLES.items():
            try:
                self.conn.execute(sql)
            except sqlite3.OperationalError as msg:
                if msg.args[0] == 'attempt to write a readonly database':
                    Logger.debug(f'DrugDb: read only:{filename}')
                    raise
                if msg.args[0] != f'table {table_name} already exists':
                    raise
                Logger.debug(f'DrugDb:{msg.args[0]}:{sql}')
            finally:
                self.conn.commit()


if __name__ == '__main__':
    from argparse import ArgumentParser
    p = ArgumentParser(
        description='DrugDb command line interface.')
    p.add_argument('-f', '--file',
                   dest='filename',
                   default='../eyedrop.db',
                   metavar='FILENAME',
                   help='open/create database filename')
    args = p.parse_args()
    db = DrugDb(args.filename)
