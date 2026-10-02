# Configuration file for the Sphinx documentation builder.
#
# 公開用ドキュメント(GitHub Pages)。ビルドは docs/v版/ に出力する:
#   venv/bin/sphinx-build -b html -d document/_build/doctrees document docs/v版
#   (-d で中間ファイルを公開用の docs/ の外に出す)
# man ページ(eyedrop.rst から作り、日本語向けに手直しして man/eyedrop.1 に置く。
# install.sh で入れる):
#   venv/bin/sphinx-build -b man -d document/_build/doctrees \
#       document document/_build/man
# 版は mobile/pyproject.toml の version から読む(アプリと版を揃えるため)。
import re
import tomllib
from pathlib import Path

_PYPROJECT = (Path(__file__).resolve().parent.parent / 'mobile'
              / 'pyproject.toml')
_VERSION = tomllib.loads(
    _PYPROJECT.read_text(encoding='utf-8'))['project']['version']

# -- Project information -----------------------------------------------------

project = '目薬管理(eyedrop)'
copyright = '2023-2026, kuma35'
author = 'kuma35'
version = _VERSION
release = _VERSION

# -- General configuration ---------------------------------------------------

extensions = [
    'sphinx_rtd_theme',
    'sphinx_rtd_dark_mode',
]
# アプリに合わせて既定は黒地(画面右下のボタンで切り替え可)
default_dark_mode = True

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

language = 'ja'

# -- Options for HTML output -------------------------------------------------

html_theme = 'sphinx_rtd_theme'
html_title = f'目薬管理 {release}'
html_static_path = ['_static']
html_show_sourcelink = False
html_copy_source = False
html_theme_options = {
    'navigation_depth': 3,
}

# -- Options for manual page output ------------------------------------------

man_pages = [
    ('eyedrop', 'eyedrop', '目薬の在庫管理と次回来院までに必要な本数の計算',
     [author], 1),
]
man_show_urls = True

# 日本語の文字(かな・漢字・全角記号)。この直後に改行してよい位置の印 \: を入れる
# ただし次が句読点・閉じ括弧・長音なら入れない(行頭に「、」などが来ないように)
_CJK = re.compile(r'([\u3000-\u30ff\u3400-\u9fff\uff00-\uffef])'
                  r'(?![、。,.)」』】〕!?ー\uff09\uff0c\uff0e\uff01\uff1f])')
_MAN_DIR = Path(__file__).resolve().parent.parent / 'man'


def _fix_man_for_japanese(text: str) -> str:
    """make man page readable in Japanese

    JP:
    groff は日本語の文字の間で改行できず、行をそろえようとして空白を広げる。
    左寄せ(.ds AD l・.ad l)・ハイフンなし(.nh)にし、文字の後に改行してよい印 \\: を入れる。
    マクロの行(. で始まる)と整形済みの範囲(.nf 〜 .fi)は変えない。
    """
    out = []
    fill = True
    for line in text.split('\n'):
        if line.startswith('.TH '):
            # man マクロは段落ごとに AD(既定は両端そろえ)へ戻すので AD も左寄せに
            out += [line, '.ds AD l', '.ad l', '.nh']
            continue
        if line.startswith('.nf'):
            fill = False
        elif line.startswith('.fi'):
            fill = True
        if fill and not line.startswith(('.', "'")):
            line = _CJK.sub(r'\1\\:', line)
            if line.endswith('\\:'):
                line = line[:-2]   # 行末は改行するので印は不要
        out.append(line)
    return '\n'.join(out)


def _install_man(app, exception):
    """after man build: fix for Japanese and copy to man/

    JP:
    man のビルドの後、日本語向けに手直ししてリポジトリの man/ に置く。
    """
    if exception or app.builder.name != 'man':
        return
    _MAN_DIR.mkdir(exist_ok=True)
    for page in Path(app.outdir).glob('*.[1-9]'):
        text = page.read_text(encoding='utf-8')
        (_MAN_DIR / page.name).write_text(_fix_man_for_japanese(text),
                                          encoding='utf-8')


def setup(app):
    app.connect('build-finished', _install_man)
