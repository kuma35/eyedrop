#!/usr/bin/env python3
"""make a Japanese man page (roff) readable with groff

JP:
日本語の man ページ(roff)を groff で読みやすくする。

groff は日本語の文字の間で改行できず、行の両端をそろえようとして単語間の空白を
大きく広げる(「cannot adjust line」「cannot break line」の警告も出る)。そこで

- .TH の直後に .ds AD l(man マクロが段落ごとに戻す既定の行そろえを左寄せに)、
  .ad l(左寄せ)、.nh(ハイフネーションなし)を入れる
- 日本語の文字の後に、改行してよい位置の印 \\: を入れる。ただし
  次が句読点・閉じ括弧・長音のとき(行頭に「、」などが来ないように)、行末、
  マクロの行(. や ' で始まる)、整形済みの範囲(.nf 〜 .fi)には入れない

使い方:
    fix_man_ja.py page.1            # その場で書き換える
    fix_man_ja.py -o out.1 page.1   # 別のファイルに書く
何度実行しても結果は同じ(既に手直し済みのファイルはそのまま)。
"""
import argparse
import re
import sys
from pathlib import Path

# 日本語の文字(全角記号・かな・漢字・全角英数)の直後。次が句読点・閉じ括弧・長音なら除く
CJK = re.compile(r'([\u3000-\u30ff\u3400-\u9fff\uff00-\uffef])'
                 r'(?![、。,.)」』】〕!?ー\uff09\uff0c\uff0e\uff01\uff1f]|\\:)')
HEADER = ['.ds AD l', '.ad l', '.nh']


def fix(text: str) -> str:
    """fix roff text for Japanese"""
    lines = text.split('\n')
    out = []
    fill = True
    for index, line in enumerate(lines):
        if line.startswith('.TH '):
            out.append(line)
            if lines[index + 1:index + 1 + len(HEADER)] != HEADER:
                out += HEADER
            continue
        if line.startswith('.nf'):
            fill = False
        elif line.startswith('.fi'):
            fill = True
        if fill and not line.startswith(('.', "'")):
            line = CJK.sub(r'\1\\:', line)
            if line.endswith('\\:'):
                line = line[:-2]   # 行末は改行するので印は不要
        out.append(line)
    return '\n'.join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('page', nargs='+', help='man ページ(roff)')
    parser.add_argument('-o', '--output', help='出力先(ページが1つのとき)')
    args = parser.parse_args(argv)
    if args.output and len(args.page) != 1:
        parser.error('-o はページが1つのときだけ使えます')
    for name in args.page:
        text = Path(name).read_text(encoding='utf-8')
        Path(args.output or name).write_text(fix(text), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
