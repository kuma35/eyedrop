# -*- coding: utf-8 -*-
"""define sql statements for tables

JP:
テーブル定義の SQL 文です。
わざわざファイル分けてあるのはインデントなしでSQL文を崩さずに
三連引用符 で記述したかったからです。

日付は全て ISO 形式の文字列 'YYYY-MM-DD' で保持します。

drug
----

薬(代表目薬名)を管理します。同じ効能なら drug_id はひとつだけです。
ジェネリック等で実際に貰う薬の名前が変わった場合は drug_alias に
名前を追加します(drug_id は変えない)。

- end_date: 使用終了日。NULL なら使用中。
- max_days: 開封後の廃棄期限日数(例: キサラタンは 28 = 4週間で廃棄)。NULL なら無し。
  推定の上限にはせず、超過したら info で知らせるだけ。
- default_days: 実績が無いときの想定使用日数。
- as_needed: 随時使用(毎日使うものではない。例: ヒアレイン)なら 1。
  必要本数を計算せず、推定使用日数は参考表示のみ。

drug_alias
----------

目薬名(実際に支給される薬の名前。ジェネリック等)。代表目薬名(drug.name)は固定。
end_date(利用終了日)が空欄の名前は利用中です。切替時期は利用中の名前が
2つになることもあります。目薬名がすべて利用終了した代表目薬名は利用終了扱い。
名前が1件も無ければ drug.name をそのまま使います。

stock
-----

未開封の在庫の入出庫。 kind は

- 'in': 入庫(処方)
- 'out': 出庫(開封など)
- 'inventory': 棚卸し(それまでの残高を無視して qty を正しい在庫数とする)

残高は (stock_date, stock_id) 順に積算して求めます。
1日の中で入庫出庫両方発生することもあるので、同日内は登録順です。

lifetime
--------

開封から使い切るまでの期間。封を切ったら1レコード増やします。
use_end が NULL のものが現在使用中(開封中)です。
irregular は途中廃棄・紛失・中断など、使用日数の算定根拠に
使えないレコードを表します。
out_stock_id, prev_lifetime_id は開封の取り消し用で、開封時に出庫した
stock_id と使用終了にした前の lifetime_id です(該当無しは 0)。
NULL は旧バージョンで開封したもの(取り消し時は日付から推定します)。

lifetime_summary
----------------

年次更新で退避したライフタイム実績(イレギュラーを除いた妥当な値)の
年ごとの要約。直近実績が無いときの推定に使います。

drug_note
---------

「両眼再開」「手術後左眼中止」など、日付付きのメモ。
"""

SCHEMA_VERSION = 5

DRUG = """
CREATE TABLE IF NOT EXISTS drug (
    drug_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,   -- 代表目薬名 例:コソプト
    start_date TEXT,             -- 使用開始日
    end_date TEXT,               -- 使用終了日。NULLなら使用中
    max_days INTEGER,            -- 開封後の廃棄期限日数 例:28
    default_days INTEGER,        -- 実績が無いときの想定使用日数
    note TEXT,
    as_needed INTEGER NOT NULL DEFAULT 0  -- 随時使用
);
"""

DRUG_ALIAS = """
CREATE TABLE IF NOT EXISTS drug_alias (
    alias_id INTEGER PRIMARY KEY,
    drug_id INTEGER NOT NULL REFERENCES drug(drug_id),
    alias_name TEXT NOT NULL,    -- 例:ドルモロール
    start_date TEXT,             -- 例:2022-01-01
    note TEXT,
    end_date TEXT                -- 利用終了日。NULLなら利用中
);
"""

STOCK = """
CREATE TABLE IF NOT EXISTS stock (
    stock_id INTEGER PRIMARY KEY,
    drug_id INTEGER NOT NULL REFERENCES drug(drug_id),
    stock_date TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('in', 'out', 'inventory')),
    qty INTEGER NOT NULL CHECK (qty >= 0),
    note TEXT
);
"""

LIFETIME = """
CREATE TABLE IF NOT EXISTS lifetime (
    lifetime_id INTEGER PRIMARY KEY,
    drug_id INTEGER NOT NULL REFERENCES drug(drug_id),
    use_start TEXT NOT NULL,     -- 開封日
    use_end TEXT,                -- 使い切った日。NULLなら使用中
    irregular INTEGER NOT NULL DEFAULT 0,  -- 途中廃棄、紛失、中断等
    note TEXT,
    out_stock_id INTEGER,        -- 開封時の出庫 stock_id。0なら出庫無し
    prev_lifetime_id INTEGER     -- 開封時に使用終了にした lifetime_id。0なら無し
);
"""

LIFETIME_SUMMARY = """
CREATE TABLE IF NOT EXISTS lifetime_summary (
    drug_id INTEGER NOT NULL REFERENCES drug(drug_id),
    year INTEGER NOT NULL,
    count INTEGER NOT NULL,
    avg_days REAL NOT NULL,
    min_days INTEGER NOT NULL,
    max_days INTEGER NOT NULL,
    PRIMARY KEY (drug_id, year)
);
"""

DRUG_NOTE = """
CREATE TABLE IF NOT EXISTS drug_note (
    note_id INTEGER PRIMARY KEY,
    drug_id INTEGER NOT NULL REFERENCES drug(drug_id),
    note_date TEXT,
    text TEXT NOT NULL
);
"""

META = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS stock_drug_date ON stock (drug_id, stock_date);
CREATE INDEX IF NOT EXISTS lifetime_drug_start
    ON lifetime (drug_id, use_start);
"""

# 旧バージョンで作成済のテーブルに追加する列 {テーブル名: [(列名, 定義)]}
ADD_COLUMNS = {
    'drug': [('as_needed', 'INTEGER NOT NULL DEFAULT 0')],
    'drug_alias': [('end_date', 'TEXT')],
    'lifetime': [('out_stock_id', 'INTEGER'),
                 ('prev_lifetime_id', 'INTEGER')],
}

# 名前はテーブル名と合わせてください
CREATE_TABLES = {
    'drug': DRUG,
    'drug_alias': DRUG_ALIAS,
    'stock': STOCK,
    'lifetime': LIFETIME,
    'lifetime_summary': LIFETIME_SUMMARY,
    'drug_note': DRUG_NOTE,
    'meta': META,
}
