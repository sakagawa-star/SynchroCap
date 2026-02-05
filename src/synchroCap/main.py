
import imagingcontrol4 as ic4

from PySide6.QtWidgets import QApplication

from mainwindow import MainWindow

def main():
    with ic4.Library.init_context():
        app = QApplication()
        app.setApplicationName("synchroCap")
        app.setApplicationDisplayName("SynchroCap")
        app.setStyle("fusion")

        w = MainWindow()
        w.show()

        app.exec()

if __name__ == "__main__":
    main()