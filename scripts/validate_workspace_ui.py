"""Render Continue Work with temporary records; never open apps or browser pages."""
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def main():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QFont, QFontDatabase
    from core.remote_store import RemoteStore
    from core.permission_manager import PermissionManager
    from core.workspaces import WorkspaceStore
    from core.workspace_panel import WorkspacePanel
    app = QApplication.instance() or QApplication([])
    if os.name == 'nt':
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
    app.setFont(QFont('Segoe UI', 10))
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = WorkspaceStore(RemoteStore(root / 'remote.db'), PermissionManager(root / 'permissions.json'))
        store.save({'name': 'Example development workspace', 'folder': tmp,
                    'notes': 'Finished the login form. Validation tests pass. The empty state still needs review.',
                    'next_steps': 'Review the empty-state copy\nRun the accessibility checks\nPrepare a change summary',
                    'apps': ['vscode'], 'urls': ['https://example.com/docs']})
        panel = WorkspacePanel(store=store)
        panel.setStyleSheet('QWidget {background:#0c1420;color:#d6e8f5;font-size:13px} QLineEdit,QPlainTextEdit,QTableWidget {background:#142237;border:1px solid #30465e;padding:5px} QPushButton {background:#17354a;border:1px solid #3584a4;padding:7px}')
        panel.resize(980, 850)
        panel.show()
        for _ in range(300):
            app.processEvents()
            if not panel.busy:
                break
            time.sleep(.01)
        assert not panel.busy and panel.row.get('id')
        assert 'Finished the login form' in panel.summary.toPlainText()
        output = ROOT / 'validation' / 'continue-work.png'
        output.parent.mkdir(exist_ok=True)
        panel.grab().save(str(output))
        panel.close()
        print('Continue Work rendered with temporary checkpoint; no app, folder or page opened.')


if __name__ == '__main__':
    main()
