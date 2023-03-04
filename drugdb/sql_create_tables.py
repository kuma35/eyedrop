# -*- coding: utf-8 -*-
"""define sql statements

SQL文を定義しています。
わざわざファイル分けてあるのはインデントなしでSQL文を崩さずに
 三連引用符 で記述したかったからです。
これでもまぁ、余分な空白とか改行が入ってしまう訳ですが、
バックスラッシュで繋ぎましょうとか、 textwrap モジュールで
加工しましょうとかなんか実行コスト掛かりそう(?) なので
この辺りが妥協点ですかねぇ…

drug_master
-----------

同じ効能なら割り当てる drug_id はひとつだけです。
drug_name にはその時々で自分がわかりやすい名前に変えます。
最初に貰った名前のままでもいいですし、
ちょと変えて「コソプト相当」などとしても構いません。

create table drug_master (
             drug_id int NOT NULL,
             drug_name text NOT NULL,
             primary key(drug_id)
             );

drug_alias
----------

同じ効能でもジェネリック等、別の薬を貰うことがあります。
drug_id は変えずに、 drug_alias に名前を追加します。

alias_name は貰った薬の名前。例えば「ドルモロール」。

start_date はもらい始めた日付です。例えば 2020/4/1

この 同じ drug_id の中で drug_alias_id の一番大きいものが、
現在使用中の薬になります。

なお、 drug_alias が存在しない場合は drug_master の名前を
そのまま使います。 例えばキサラタンは最初から現在まで
キサラタンのままですので drug_alias にレコードがありません。
なので drug_master のを使います。

create table drug_alias (
             drug_id int NOT NULL,
             drug_alias_id int NOT NULL,
             alias_name text NOT NULL, ジェネリックなど、現在使っている薬の名前。
             start_date date,  もらい始めた日付、など。
             primary key(drug_id, drug_alias)
             );

drug_lifetime
-------------

封をきり、現在使用中の薬の利用日数を調べます。
今の所一度に1つの前提でテーブル設計・プログラム設計
しています。

次のを封切りしたらレコードを１つ増やします。

dispose_flag は途中廃棄、紛失など、
日付算定根拠に使えないレコードを表します。
この場合は理由として lifetime_note に
決まった文言が入るかと思います「途中廃棄」「紛失」「その他」

use_end は次のレコードが出来れば自明ですけども、
キサラタンなど利用日数が決まっている場合は入ることがあります。
この場合記入時点で未来日付なのがミソです。


create table drug_lifetime (
             drug_id int NOT NULL,
             use_start date NOT NULL, もらった薬を使用開始した日付
             use_end date, 使い切った日付
             dispose_flag boolean, 使用中止、紛失、意図せぬ廃棄など、この利用期間が参考にできないとき
             lifetime_note text,
             primary key(drug_id, use_start)
             );

drug_stock
----------

封切り前の薬が現在手元に幾つあるか、

出庫日(封切り)、出庫数(普通は1)

入庫日(通院、処方)、入個数

inventory
棚卸し(それまでの在庫数を無視して
棚卸しした在庫数を正しい在庫数とする)

入出庫がそんなに激しいものでもないので
管理は日単位ぐらいにしておきます。
1日の中で出庫入庫両方発生する可能性はあります。
そこを考慮して在庫カウント。
棚卸し

薬の入出庫、在庫数を管理します。
create table drug_stock(
             drug_id int NOT NULL,
             drug_stock_date date NOT NULL,
             stock_in int,
             stock_out int,
             stock_balance int,
             primary key(drug_id, drug_stock_date)
             );

"""
DRUG_MASTER = """
create table drug_master (
             drug_id int NOT NULL,
             drug_name text NOT NULL, -- 例:コソプト相当
             primary key(drug_id)
             );
"""

DRUG_ALIAS = """-- ジェネリック等、同じ効能の薬を貰った時
create table drug_alias (
             drug_id int NOT NULL,
             drug_alias_id int NOT NULL,
             alias_name text NOT NULL, -- 例:ドルモロール
             start_date date, -- 例:2020/4/1〜
             primary key(drug_id, drug_alias_id)
             );
"""

DRUG_LIFETIME = """
create table drug_lifetime (
             drug_id int NOT NULL,
             use_start date NOT NULL,
             use_end date,
             dispose_flag boolean,
             lifetime_note text,
             primary key(drug_id, use_start)
             );
"""

DRUG_STOCK = """
create table drug_stock(
             drug_id int NOT NULL,
             drug_stock_date date NOT NULL,
             stock_in int,
             stock_out int,
             stock_balance int,
             inventory boolean,
             primary key(drug_id, drug_stock_date)
             );
"""

CREATE_TABLES = {
    'drug_master': DRUG_MASTER,
    'drug_alias': DRUG_ALIAS,
    'drug_lifetime': DRUG_LIFETIME,
    'drug_stock': DRUG_STOCK,
}
