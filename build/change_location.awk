# -*- coding:utf-8 -*-
# pot(po)ファイルの location ( #: で始まる行) のファイルの
# 相対パスを書き換え、実際に翻訳作業する
# build/locale/<countory>/LC_MESSAGES/hoge.po
# から参照(emacs po-mode s コマンド)したときに当該
# 原文ファイルがちゃんと開くようにする
#
# extract/eyedrop.kv については、 実際のファイルは
# (eydrop root)/eyedrop.kv であるのでそのようになるように
# 調整する
#
# run at build/ 
# xgettext -o -  -p gettext -L Python --from-code UTF-8 --no-wrap extract/eyedrop.kv ../document/hoge.py | gawk -f change_location.awk > gettext/eyedrop.pot
$1 == "#:" {
    for (i = 1; i <= NF; i = i+1) {
	# print "$" i "=" $i > "/dev/stderr"
	if (match($i, /\.\.\/(([-_[:alnum:]]+\/)*[-_[:alnum:]]+\.py:[0-9]*)/, a)) {
	    # print "a[" 0 "]="  a[0] > "/dev/stderr"
	    # print "a[" 1 "]="  a[1] > "/dev/stderr"  # use
	    # print "a[" 2 "]="  a[2] > "/dev/stderr"  
	    $i = "../../../../" a[1]  # $i をこれに書換た $0 にする
	}
    }
    gsub(/extract\//, "../../../../")
    print
    next
}

{
    # 上記以外の行は何もしない
    print
    next
}
