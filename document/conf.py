# Configuration file for the Sphinx documentation builder.
#
# 公開用ドキュメント(GitHub Pages)。ビルドは docs/v版/ に出力する:
#   venv/bin/sphinx-build -b html -d document/_build/doctrees document docs/v版
#   (-d で中間ファイルを公開用の docs/ の外に出す)
# 版は mobile/pyproject.toml の version から読む(アプリと版を揃えるため)。
import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent / 'mobile' / 'pyproject.toml'
_VERSION = tomllib.loads(_PYPROJECT.read_text(encoding='utf-8'))['project']['version']

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
