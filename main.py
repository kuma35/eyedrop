# -*- coding: utf-8 -*-
"""eyedrop main routine"""
from pathlib import Path, PurePath
from kivy.app import App
from kivy.logger import Logger
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy_garden.i18n.localizer import KXLocalizer, GettextTranslator
from choicefont import ConfigFontFinder


def config_translator(config):
    """get translator for lang. else None
    """
    lang = config.get('i18n', 'lang')
    domain = config.get('i18n', 'domain')
    locale_dir = PurePath(__file__).parent / 'locale'
    msg_path = PurePath(
        locale_dir,
        lang,
        'LC_MESSAGES',
        domain).with_suffix('.mo')
    if Path(msg_path).exists():
        translator = GettextTranslator(
            domain=domain,
            localedir=locale_dir,
        )
    else:
        translator = None
    return translator


class SummaryScreen(Screen):
    """name is 'summary' screen"""
    pass


class StockScreen(Screen):
    """ name is 'stock' screen"""
    pass


class EyedropApp(App):
    """eydrop Application class"""
    loc = None

    def build_config(self, config):
        """overload buind_config"""
        config.setdefaults('i18n', {
            'lang': 'en',
            'domain': 'eyedrop',
        })
        config.setdefaults('fonts', {
            'en': 'Roboto',
        })
        config.setdefaults('db', {
            'filename': 'eyedorop.db',
            })

    @staticmethod
    def setup_localizer(config) -> KXLocalizer:
        """setup localizer, load application config"""

        localizer = KXLocalizer(
            lang=config.get('i18n', 'lang'),
            translator=config_translator(config),
            fontfinder=ConfigFontFinder(config),
        )
        localizer.install(name='h')  # initial of honyaku
        return localizer

    def build(self):
        """overload build() """
        self.loc = self.setup_localizer(self.config)
        Logger.debug(f'App: {self.loc.font_name=}')

        self.title = self.loc._('eyesdrop stock management')

        screen_manager = ScreenManager()
        screen_manager.add_widget(SummaryScreen(name='summary'))
        screen_manager.add_widget(StockScreen(name='stock'))
        return screen_manager


if __name__ == '__main__':
    EyedropApp().run()
