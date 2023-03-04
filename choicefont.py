# -*- coding: utf-8 -*-
# __all__ 回避してDefaultFontFinderを使うため、from...import...
# 形式ではなく import ... as ... を使う
"""choice font from application config"""
from kivy.config import Config
from kivy.logger import Logger
import kivy_garden.i18n.localizer as Localizer

# type hints
Fontname = Localizer.Fontname


class ConfigFontFinder(Localizer.DefaultFontFinder):
    """configured font finder

    application config file の fonts セクションに
    指定の lang (たとえば 'ja' ) のがあるかどうか
    調べ、あれば、それをその lang の フォント名と
    して使います。

    それが不正だった時はどうなっても知りません。

    application config file から見つからない時は
    DefaultFontFinnder の動作を行います。
    """
    config = None

    def __init__(self, config: Config):
        """override __init__ """
        self.config = config
        super().__init__()

    def __call__(self, lang: Localizer.Lang) -> Fontname:
        """override __call__ """
        font_section = 'fonts'
        if self.config.has_option(font_section, lang):
            config_font = self.config.get(font_section, lang)
            Logger.debug(f'choicefont: {config_font=}')
            if config_font is not None:
                super().PRESET[lang] = config_font
        return super().__call__(lang=lang)
