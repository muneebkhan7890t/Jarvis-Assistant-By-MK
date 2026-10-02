"""Windowless Windows entry point with a stable working directory and disk logs."""
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import traceback

BASE = Path(__file__).resolve().parent


class LogStream:
    encoding = 'utf-8'

    def __init__(self, logger):
        self.logger = logger

    def write(self, text):
        if text.strip():
            self.logger.info(text.rstrip())
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return False


def launch():
    os.chdir(BASE)
    (BASE / 'logs').mkdir(exist_ok=True)
    handler = RotatingFileHandler(BASE / 'logs' / 'assistant.log', maxBytes=2_000_000,
                                  backupCount=3, encoding='utf-8')
    logger = logging.getLogger('jarvis')
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    sys.stdout = sys.stderr = LogStream(logger)
    try:
        if '--settings' in sys.argv or '--workspaces' in sys.argv:
            from PyQt6.QtWidgets import QApplication, QTabWidget
            from core.control_panel import ControlPanel
            app = QApplication(sys.argv)
            panel = ControlPanel()
            tabs = panel.findChild(QTabWidget)
            if tabs is not None:
                for index in range(tabs.count()):
                    if tabs.tabText(index) == ('Continue Work' if '--workspaces' in sys.argv else 'Remote Devices'):
                        tabs.setCurrentIndex(index)
                        break
            panel.show()
            app.exec()
            return
        from main import main
        main()
    except Exception:
        traceback.print_exc()
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,
                f'JARVIS could not start. Run Setup Windows.cmd first.\nDetails: {BASE / "logs" / "assistant.log"}',
                'JARVIS startup error', 0x10)
        raise


if __name__ == '__main__':
    launch()
