.. -*- coding: utf-8; mode:

欲しいもの
==========

キサラタンの4週間で強制排気処理

Lifetime は平均よりも直前実績の方が適切かもしれない。 直前実績が極端に短い場合はさらにその前を使うろ過するそこは手動選択する。 前回実績よりオークス書いてる場合は前回実績より X 日多く使えてますと表示する

最終的には角目薬を日数単位で管理できるようになる

- 現在の在庫量(特定日付時点での在庫量)
- 入庫数・入庫日付
- 出庫数・出庫日付(開封日)
- 使用中数
- 必要数(定数)(特定期間、例えば次の診察の2ヶ月で必要な数)
- 現在の在庫量と定数から導きだされる要求入庫数

ライフタイム(?)管理
ある目薬が利用される期間(開封日から使い切った日、または次の開封までの期間)。
※定数の算出の一助とする。

先生には
「コソプト相当が定数nで在庫mなので(n-mで)o個下さい」
「グラなテックは定数xで…」
と言えるようにする。
   
費用の最小化を図る。
手元に保持する薬の数が最小かつ十分である数だけ保持するようにする。

アプリの場合、
MIT等、商用OKのものにする。具体的には広告モデルOKにする。
目が悪くても見やすいようハイコントラスト(黒字に白等)をデフォルト設定とする。
文字の大きさを変えられるようにする。はじめから大きくする。ピンチアウトピンチインでもOK?

アプリ作成環境・ツールの選定。
商用利用制限が無い事。(ライセンス表示はあってもOK)

.. code-block:: sql

   create table drug_master (
		drug_id int NOT NULL,
		drug_name text NOT NULL,
		primary key(drug_id)
		);

.. code-block:: sql

   create table drug_alias (
		drug_id int NOT NULL,
		drug_alias_id int NOT NULL,
		alias_name text NOT NULL,
		start_date date,
		primary key(drug_id, drug_alias)
		);

.. code-block:: sql

   create table drug_lifetime (
		drug_id int NOT NULL,
		use_start date NOT NULL,
		use_end date,
		lifetime_note text,
		primary key(drug_id, use_start)
		);

.. code-block:: sql

   create table drug_stock(
		drug_id int NOT NULL,
		drug_stock_date date NOT NULL,
		stock_in int,
		stock_out int,
		stock_balance int,
		primary key(drug_id, drug_stock_date)
		);
