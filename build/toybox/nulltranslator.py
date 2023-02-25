# -*- coding: utf-8 -*-
from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen


class SummaryScreen(Screen):
    pass


class StockScreen(Screen):
    pass


class EyedropApp(App):
    def build_config(self, config):
        config.setdefaults('i18n', {
            'lang': 'en',
            'domain': 'eyedrop',
            })

    @staticmethod
    def setup_localizer(config):
        from kivy_garden.i18n.localizer import KXLocalizer, GettextTranslator
        from pathlib import Path, PurePath
        lang = config.get('i18n', 'lang')
        domain = config.get('i18n', 'domain')
        locale_dir = PurePath(__file__).parent / 'locale'
        domain_path = PurePath(locale_dir, lang, 'LC_MESSAGES', domain).with_suffix('.mo')
        if Path(domain_path).exists():
            translator = GettextTranslator(
                domain='eyedrop',
                localedir=locale_dir,
            )
        else:
            translator = None
        loc = KXLocalizer(
            lang=lang,
            translator=translator,
        )
        loc.install(name='l')  # small 'l' 
        return loc

    def build(self):
        config = self.config
        self.loc = self.setup_localizer(config)
        self.loc.lang = 'en'
        sm = ScreenManager()
        sm.add_widget(SummaryScreen(name='summary'))
        sm.add_widget(StockScreen(name='stock'))
        return sm


if __name__ == '__main__':
    EyedropApp().run()
