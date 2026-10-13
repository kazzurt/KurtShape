"""Initial application window placement."""
from __future__ import annotations


def maximize_on_primary_screen(main):
    """Open on the primary monitor using its full available desktop area.

    A saved maximized window can belong to another monitor. Clear that state
    before assigning the screen and restore rectangle, then maximize once.
    Qt accounts for the monitor's scaling and the Windows taskbar.
    """
    from PySide import QtCore, QtGui

    main.setWindowState(main.windowState() & ~(
        QtCore.Qt.WindowMinimized | QtCore.Qt.WindowMaximized | QtCore.Qt.WindowFullScreen))
    # Native handle/state changes can recreate Qt's QScreen wrappers on a
    # mixed-DPI desktop. Fetch the target afterwards and copy its rectangle
    # before moving the window; never retain the wrapper across GUI events.
    main.winId()
    screen = QtGui.QApplication.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
        handle = main.windowHandle()
        if handle is not None:
            handle.setScreen(screen)
        width = min(1440, round(available.width() * .9))
        height = min(920, round(available.height() * .85))
        main.setGeometry(available.x() + (available.width() - width) // 2,
                         available.y() + (available.height() - height) // 2,
                         width, height)
    main.showMaximized()

