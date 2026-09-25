# -*- coding: utf-8 -*-
"""manipulate sql(s)

JP:
追加したり削除したり編集したりする SQL 文。
テーブル定義は sql_table.py にあります。
"""

# drug_id は省略して自動採番する
NEW_DRUG = """
INSERT INTO drug (name, start_date, max_days, default_days, note,
                  as_needed)
    VALUES (:name, :start_date, :max_days, :default_days, :note,
            :as_needed);
"""

FIND_DRUG_BY_ID = """
SELECT * FROM drug WHERE drug_id = :key;
"""

# 登録名で見つからなければ別名(現在・過去の薬の名前)で探す
FIND_DRUG_BY_NAME = """
SELECT * FROM drug WHERE name = :key
UNION
SELECT drug.* FROM drug JOIN drug_alias USING (drug_id)
    WHERE drug_alias.alias_name = :key;
"""

LIST_DRUGS = """
SELECT * FROM drug ORDER BY drug_id;
"""

UPDATE_DRUG = """
UPDATE drug SET {column} = :value WHERE drug_id = :drug_id;
"""

NEW_ALIAS = """
INSERT INTO drug_alias (drug_id, alias_name, start_date, note)
    VALUES (:drug_id, :alias_name, :start_date, :note);
"""

SET_ALIAS_END = """
UPDATE drug_alias SET end_date = :end_date WHERE alias_id = :alias_id;
"""

LIST_ALIASES = """
SELECT * FROM drug_alias WHERE drug_id = :drug_id
    ORDER BY start_date IS NULL, start_date, alias_id;
"""

NEW_STOCK = """
INSERT INTO stock (drug_id, stock_date, kind, qty, note)
    VALUES (:drug_id, :stock_date, :kind, :qty, :note);
"""

LIST_STOCK = """
SELECT * FROM stock WHERE drug_id = :drug_id
    ORDER BY stock_date, stock_id;
"""

DELETE_STOCK = """
DELETE FROM stock WHERE stock_id = :stock_id;
"""

NEW_LIFETIME = """
INSERT INTO lifetime (drug_id, use_start, use_end, irregular, note)
    VALUES (:drug_id, :use_start, :use_end, :irregular, :note);
"""

LIST_LIFETIME = """
SELECT * FROM lifetime WHERE drug_id = :drug_id
    ORDER BY use_start, lifetime_id;
"""

OPEN_LIFETIME = """
SELECT * FROM lifetime WHERE drug_id = :drug_id AND use_end IS NULL
    ORDER BY use_start DESC, lifetime_id DESC;
"""

CLOSE_LIFETIME = """
UPDATE lifetime SET use_end = :use_end WHERE lifetime_id = :lifetime_id;
"""

SET_IRREGULAR = """
UPDATE lifetime SET irregular = :irregular,
    note = COALESCE(:note, note)
    WHERE lifetime_id = :lifetime_id;
"""

DELETE_LIFETIME = """
DELETE FROM lifetime WHERE lifetime_id = :lifetime_id;
"""

SET_OPEN_LINK = """
UPDATE lifetime SET out_stock_id = :out_stock_id,
    prev_lifetime_id = :prev_lifetime_id
    WHERE lifetime_id = :lifetime_id;
"""

# 旧バージョンで開封したものの取り消し用(日付から推定)
FIND_OPEN_OUT = """
SELECT * FROM stock WHERE drug_id = :drug_id AND kind = 'out'
    AND qty = 1 AND stock_date = :stock_date
    ORDER BY stock_id DESC LIMIT 1;
"""

FIND_CLOSED_AT = """
SELECT * FROM lifetime WHERE drug_id = :drug_id AND use_end = :use_end
    AND lifetime_id <> :lifetime_id
    ORDER BY use_start DESC, lifetime_id DESC LIMIT 1;
"""

GET_LIFETIME = """
SELECT * FROM lifetime WHERE lifetime_id = :lifetime_id;
"""

GET_STOCK = """
SELECT * FROM stock WHERE stock_id = :stock_id;
"""

REOPEN_LIFETIME = """
UPDATE lifetime SET use_end = NULL WHERE lifetime_id = :lifetime_id;
"""

LIST_SUMMARY = """
SELECT * FROM lifetime_summary WHERE drug_id = :drug_id ORDER BY year;
"""

# 同じ年が既にあれば合算する(年をまたぐライフタイムが後の年次更新で
# 追加される場合があるため)
MERGE_SUMMARY = """
INSERT INTO lifetime_summary
    (drug_id, year, count, avg_days, min_days, max_days)
    VALUES (:drug_id, :year, :count, :avg_days, :min_days, :max_days)
    ON CONFLICT (drug_id, year) DO UPDATE SET
        count = count + excluded.count,
        avg_days = (avg_days * count + excluded.avg_days * excluded.count)
                   / (count + excluded.count),
        min_days = min(min_days, excluded.min_days),
        max_days = max(max_days, excluded.max_days);
"""

NEW_NOTE = """
INSERT INTO drug_note (drug_id, note_date, text)
    VALUES (:drug_id, :note_date, :text);
"""

LIST_NOTES = """
SELECT * FROM drug_note WHERE drug_id = :drug_id
    ORDER BY note_date IS NULL, note_date, note_id;
"""

GET_META = """
SELECT value FROM meta WHERE key = :key;
"""

SET_META = """
INSERT INTO meta (key, value) VALUES (:key, :value)
    ON CONFLICT (key) DO UPDATE SET value = excluded.value;
"""
