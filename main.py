# -*- coding: utf-8 -*-
from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen


class SummaryScreen(Screen):
    pass


class StockScreen(Screen):
    pass


class EyedropApp(App):
    def build(self):
        sm = ScreenManager()
        sm.add_widget(SummaryScreen(name='summary'))
        sm.add_widget(StockScreen(name='stock'))
        return sm


if __name__ == '__main__':
    EyedropApp().run()
