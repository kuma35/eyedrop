SRC_DIR = ..
EXTRACT_DIR = extract
POT_DIR = gettext
EN_DIR = locale/en/LC_MESSAGES
JA_DIR = locale/ja/LC_MESSAGES

KV_FILE = $(SRC_DIR)/eyedrop.kv
EXTRACT_KV = $(EXTRACT_DIR)/eyedrop.kv

SRC_FILES = $(EXTRACT_KV) $(SRC_DIR)/main.py 

EYEDROP_POT = $(POT_DIR)/eyedrop.pot

PO_EN_FILE = $(EN_DIR)/eyedrop.po
PO_JA_FILE = $(JA_DIR)/eyedrop.po

PO_FILES = $(PO_EN_FILE) $(PO_JA_FILE)

MO_EN_FILE = $(EN_DIR)/eyedrop.mo
MO_JA_FILE = $(JA_DIR)/eyedrop.mo

# MO_FILES = $(MO_EN_FILE) $(MO_JA_FILE)

all: $(MO_EN_FILE) $(MO_JA_FILE)

# gettext モジュールでは NullTranslations から派生したもう一つのクラス
#: GNUTranslations を提供しています。
# このクラスはビッグエンディアン、およびリトルエンディアン両方の
# バイナリ形式の GNU gettext .mo ファイルを読み出せるように
# _parse() を上書きしています。
$(MO_EN_FILE) : $(PO_EN_FILE)
	msgfmt -o $@ $<

$(MO_JA_FILE) : $(PO_JA_FILE)
	msgfmt -o $@ $<


# $@が既にあるときは msgmerge で、まだ存在しないときは
# POTをPOにコピー(その際にCHARSET等をセットする)
# 参考: https://qiita.com/kkdd/items/c84d819f1bd54ed77b6a
$(PO_FILES) : $(EYEDROP_POT)
	[ -e $@ ] && msgmerge -U --previous --no-wrap $@ $< || sed -f set_po.sed < $< > $@

$(EYEDROP_POT) : $(SRC_FILES)
	xgettext -o - -L Python --from-code UTF-8 --no-wrap $^ | gawk -f change_location.awk > $@

# location を使えるようにするため、extract後の py ファイルも
# ファイル名は *.kv のまま(extract/ フォルダに格納)
$(EXTRACT_KV) : $(KV_FILE)
	gawk -f extract_kv_msg.awk $< > $@

.PHONEY: all
