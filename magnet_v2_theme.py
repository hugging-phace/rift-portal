"""
MagnetOS v2 shared design system.

Provides a global stylesheet, shadow helpers, and backend reset styles so
all v2 pages, pop-out windows, and backend widgets look modern, uniform,
and intentional.
"""

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QPointF
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import QGraphicsDropShadowEffect


def build_global_stylesheet(theme) -> str:
    """Return a comprehensive QApplication stylesheet for the v2 theme."""
    c = theme.css
    bg = c(theme.bg)
    surface = c(theme.surface)
    elevated = c(theme.elevated)
    panel = c(theme.panel)
    text = c(theme.text)
    muted = c(theme.muted)
    accent = c(theme.accent)
    accent_hover = c(theme.accent_hover)
    on_accent = c(theme.on_accent)
    border = c(theme.border)
    success = c(theme.success)
    warning = c(theme.warning)
    error = c(theme.error)

    return f"""
/* Base ------------------------------------------------------------ */
* {{
    outline: none;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, sans-serif;
}}

QWidget {{
    color: {text};
}}

QMainWindow, QDialog {{
    background: {bg};
}}

QLabel {{
    color: {text};
    background: transparent;
}}

/* Buttons --------------------------------------------------------- */
QPushButton {{
    background: {surface};
    color: {text};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 10px 16px;
    font-size: 13px;
    font-weight: 600;
}}

QPushButton:hover {{
    background: {elevated};
    border: 1px solid {accent};
}}

QPushButton:pressed, QPushButton:checked {{
    background: {accent};
    color: {on_accent};
    border: 1px solid {accent};
}}

QPushButton:disabled {{
    background: {panel};
    color: {muted};
    border: 1px solid {border};
}}

/* Primary / destructive accents via object names -------------------- */
QPushButton#primary {{
    background: {accent};
    color: {on_accent};
    border: 1px solid {accent};
}}
QPushButton#primary:hover {{ background: {accent_hover}; border: 1px solid {accent_hover}; }}

QPushButton#danger {{
    background: rgba(235, 90, 90, 0.12);
    color: {error};
    border: 1px solid rgba(235, 90, 90, 0.45);
}}
QPushButton#danger:hover {{ background: rgba(235, 90, 90, 0.22); border: 1px solid {error}; }}

QPushButton#success {{
    background: rgba(40, 200, 110, 0.12);
    color: {success};
    border: 1px solid rgba(40, 200, 110, 0.45);
}}
QPushButton#success:hover {{ background: rgba(40, 200, 110, 0.22); border: 1px solid {success}; }}

/* Inputs ---------------------------------------------------------- */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{
    background: {surface};
    color: {text};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 8px;
    font-size: 13px;
    selection-background-color: {accent};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
    border: 1px solid {accent};
}}

QLineEdit::placeholder, QTextEdit::placeholder, QComboBox::placeholder {{
    color: {muted};
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox::down-arrow {{
    image: none;
    border: none;
    width: 0px;
    height: 0px;
}}

QComboBox QAbstractItemView {{
    background: {surface};
    color: {text};
    border: 1px solid {border};
    border-radius: 10px;
    selection-background-color: {accent};
    padding: 4px;
}}

/* Lists & trees --------------------------------------------------- */
QListWidget, QListView, QTreeWidget, QTreeView {{
    background: {surface};
    color: {text};
    border: 1px solid {border};
    border-radius: 12px;
    outline: none;
    padding: 6px;
}}

QListWidget::item, QListView::item, QTreeView::item {{
    padding: 8px;
    border-radius: 8px;
}}

QListWidget::item:selected, QListView::item:selected, QTreeView::item:selected {{
    background: {accent};
    color: {on_accent};
}}

QListWidget::item:hover, QListView::item:hover, QTreeView::item:hover {{
    background: {elevated};
}}

QHeaderView::section {{
    background: {panel};
    color: {text};
    border: none;
    padding: 8px;
    font-weight: 600;
    border-radius: 6px;
}}

QSplitter::handle {{
    background: {border};
    border-radius: 2px;
}}
QSplitter::handle:horizontal {{ width: 4px; }}
QSplitter::handle:vertical {{ height: 4px; }}

/* Menus & tooltips ------------------------------------------------ */
QMenu {{
    background: {panel};
    color: {text};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 6px;
}}

QMenu::item {{
    padding: 8px 14px;
    border-radius: 6px;
}}

QMenu::item:selected {{
    background: {accent};
    color: {on_accent};
}}

QToolTip {{
    background: {panel};
    color: {text};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 12px;
}}

/* Scrollbars ------------------------------------------------------ */
QScrollBar:vertical {{
    background: {surface};
    width: 10px;
    border-radius: 8px;
    margin: 4px;
}}

QScrollBar::handle:vertical {{
    background: {accent};
    border-radius: 8px;
    min-height: 32px;
}}

QScrollBar::handle:vertical:hover {{
    background: {accent_hover};
}}

QScrollBar:horizontal {{
    background: {surface};
    height: 10px;
    border-radius: 8px;
    margin: 4px;
}}

QScrollBar::handle:horizontal {{
    background: {accent};
    border-radius: 8px;
    min-width: 32px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {accent_hover};
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0px;
    height: 0px;
}}

/* Group boxes & tabs --------------------------------------------- */
QGroupBox {{
    background: {panel};
    color: {text};
    border: 1px solid {border};
    border-radius: 14px;
    padding: 16px;
    margin-top: 12px;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: {muted};
    font-size: 12px;
}}

QTabWidget::pane {{
    background: {panel};
    border: 1px solid {border};
    border-radius: 14px;
}}

QTabBar::tab {{
    background: {surface};
    color: {text};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 8px 16px;
    margin: 4px;
    font-weight: 600;
}}

QTabBar::tab:selected {{
    background: {accent};
    color: {on_accent};
    border: 1px solid {accent};
}}

QTabBar::tab:hover {{
    background: {elevated};
}}

/* Progress & sliders --------------------------------------------- */
QProgressBar {{
    background: {surface};
    border-radius: 6px;
    height: 8px;
    text-align: center;
}}

QProgressBar::chunk {{
    background: {accent};
    border-radius: 6px;
}}

QSlider::groove:horizontal {{
    height: 6px;
    background: {surface};
    border-radius: 3px;
}}

QSlider::sub-page:horizontal {{
    background: {accent};
    border-radius: 3px;
}}

QSlider::handle:horizontal {{
    background: {accent};
    width: 16px;
    height: 16px;
    border-radius: 8px;
}}

/* Status labels --------------------------------------------------- */
QLabel#status-muted {{ color: {muted}; }}
QLabel#status-success {{ color: {success}; }}
QLabel#status-warning {{ color: {warning}; }}
QLabel#status-error {{ color: {error}; }}
"""


def apply_global_styles(app, theme):
    """Apply the v2 design system to a QApplication instance."""
    app.setStyleSheet(build_global_stylesheet(theme))

    # Set a clean cross-platform typeface; Qt will fall back gracefully.
    from PySide6.QtGui import QFont
    try:
        f = QFont("Inter", 10)
        f.setStyleHint(QFont.StyleHint.SansSerif)
        app.setFont(f)
    except Exception:
        pass


def apply_shadow(widget, theme, blur: int = 22, offset: tuple = (0, 5), alpha: int = 55):
    """Attach a soft, modern drop shadow to a widget."""
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setColor(theme.shadow)
    shadow.setOffset(*offset)
    widget.setGraphicsEffect(shadow)


def animate_shadow(widget, theme, hover: bool = True):
    """Animate a widget's shadow offset/blur for a subtle lift on hover."""
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsDropShadowEffect):
        apply_shadow(widget, theme)
        effect = widget.graphicsEffect()

    start = effect.offset()
    end = QPointF(0, 8) if hover else QPointF(0, 5)
    anim = QPropertyAnimation(effect, b"offset")
    anim.setDuration(180)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.start()


def backend_reset_stylesheet(theme) -> str:
    """
    Scoped reset for the production backend views embedded in BackendPage.
    Uses !important to override the older inline stylesheets while staying
    within the v2 palette.
    """
    c = theme.css
    surface = c(theme.surface)
    elevated = c(theme.elevated)
    panel = c(theme.panel)
    text = c(theme.text)
    accent = c(theme.accent)
    on_accent = c(theme.on_accent)
    border = c(theme.border)
    muted = c(theme.muted)

    return f"""
#backendPage QPushButton {{
    background: {surface} !important;
    color: {text} !important;
    border: 1px solid {border} !important;
    border-radius: 10px !important;
    padding: 10px 16px !important;
    font-size: 13px !important;
    font-weight: 600 !important;
}}
#backendPage QPushButton:hover {{
    background: {elevated} !important;
    border: 1px solid {accent} !important;
}}
#backendPage QPushButton:pressed, #backendPage QPushButton:checked {{
    background: {accent} !important;
    color: {on_accent} !important;
    border: 1px solid {accent} !important;
}}

#backendPage QLineEdit, #backendPage QTextEdit, #backendPage QComboBox {{
    background: {surface} !important;
    color: {text} !important;
    border: 1px solid {border} !important;
    border-radius: 10px !important;
    padding: 8px !important;
    font-size: 13px !important;
}}
#backendPage QLineEdit:focus, #backendPage QTextEdit:focus, #backendPage QComboBox:focus {{
    border: 1px solid {accent} !important;
}}

#backendPage QLabel {{
    color: {text} !important;
    background: transparent !important;
    border: none !important;
}}
#backendPage QLabel#title {{
    color: {accent} !important;
    font-weight: 700 !important;
    letter-spacing: 2px !important;
}}

#backendPage QListWidget, #backendPage QListView, #backendPage QTreeWidget, #backendPage QTreeView {{
    background: {surface} !important;
    color: {text} !important;
    border: 1px solid {border} !important;
    border-radius: 12px !important;
    padding: 6px !important;
}}
#backendPage QListWidget::item:selected, #backendPage QTreeWidget::item:selected {{
    background: {accent} !important;
    color: {on_accent} !important;
}}
#backendPage QListWidget::item:hover, #backendPage QTreeWidget::item:hover {{
    background: {elevated} !important;
}}

#backendPage QHeaderView::section {{
    background: {panel} !important;
    color: {text} !important;
    border: none !important;
    padding: 8px !important;
    font-weight: 600 !important;
}}

#backendPage QScrollBar:vertical, #backendPage QScrollBar:horizontal {{
    background: {surface} !important;
    border-radius: 8px !important;
}}
#backendPage QScrollBar::handle:vertical, #backendPage QScrollBar::handle:horizontal {{
    background: {accent} !important;
    border-radius: 8px !important;
}}
"""
