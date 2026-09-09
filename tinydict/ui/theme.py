"""主题模块：浅色 / 深色 / 跟随系统三套样式。

负责：
- 检测 Windows 10/11 系统主题（读取注册表 AppsUseLightTheme）
- 提供 APP_QSS、WB_QSS、词条 DEFAULT_CSS 的深/浅两套
- 把主题应用到 QApplication（Qt 控件）与 QWebEngineView（词条 HTML）
- 暴露 theme_changed 信号供 MainWindow 刷新已加载的词条
"""

from PySide6.QtCore import QObject, Signal


# ----------------------------------------------------------------------
# 系统主题检测
# ----------------------------------------------------------------------

def detect_system_is_dark() -> bool:
    """Windows 10/11 上读取注册表，判断系统是否启用了深色模式。

    读取失败（其他系统 / 注册表不可用）时返回 False，
    此时 theme="system" 会回退到浅色主题。
    """
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            0, winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return value == 0
    except Exception:  # noqa: BLE001
        return False


def resolve_theme(theme: str) -> str:
    """把配置里的 theme 值解析为实际使用的主题（"light" / "dark"）。"""
    if theme == "dark":
        return "dark"
    if theme == "light":
        return "light"
    if detect_system_is_dark():
        return "dark"
    return "light"


# ----------------------------------------------------------------------
# 词条 HTML 默认样式
# ----------------------------------------------------------------------

_CSS_LIGHT = """
body{font-family:'Microsoft YaHei','Segoe UI',Arial,sans-serif;
     font-size:15px;line-height:1.65;color:#24292f;background:#fff;
     margin:18px 28px;}
img{max-width:100%;height:auto;}
table{max-width:100%;border-collapse:collapse;}
a{color:#2563eb;text-decoration:none;}
a:hover{text-decoration:underline;}
.sd-headword{font-size:24px;font-weight:600;color:#111827;
     margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #e5e7eb;}
.sd-plain{white-space:pre-wrap;}
.sd-tip{color:#6b7280;font-size:13px;}
.sd-welcome h1{font-size:30px;color:#1d4ed8;margin-bottom:4px;}
.sd-welcome li{margin:6px 0;}
.sd-notfound p{color:#4b5563;}
code{background:#f3f4f6;border-radius:3px;padding:1px 5px;
     font-family:Consolas,monospace;font-size:13px;}
"""

_CSS_DARK = """
body{font-family:'Microsoft YaHei','Segoe UI',Arial,sans-serif;
     font-size:15px;line-height:1.65;color:#d4d4d4;background:#1e1e1e;
     margin:18px 28px;}
img{max-width:100%;height:auto;filter:brightness(0.9);}
table{max-width:100%;border-collapse:collapse;}
a{color:#60a5fa;text-decoration:none;}
a:hover{text-decoration:underline;}
.sd-headword{font-size:24px;font-weight:600;color:#e5e7eb;
     margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #374151;}
.sd-plain{white-space:pre-wrap;}
.sd-tip{color:#9ca3af;font-size:13px;}
.sd-welcome h1{font-size:30px;color:#93c5fd;margin-bottom:4px;}
.sd-welcome li{margin:6px 0;}
.sd-notfound p{color:#9ca3af;}
code{background:#2d2d30;border-radius:3px;padding:1px 5px;
     font-family:Consolas,monospace;font-size:13px;color:#d4d4d4;}
/* 词库自带样式的兜底覆盖：强制白底改为深色背景 */
::selection{background:#3b82f6;color:#fff;}
"""

# 注意：上面的 _CSS_LIGHT / _CSS_DARK 只用于应用「自己生成」的页面
# （欢迎页 / 未找到 / 加载中 / 纯文本词条模板），不对真实词库词条生效。
#
# 真实词库词条的配色走下面的通用方案（见 entry_filter_css /
# resolve_entry_theme），核心原则是「同一套规则对待所有词库」：
#   - 绝不向词条注入高特异性的 !important 覆盖（那会把词库自带的配色、
#     背景、排版全压平，表现为窗口换肤后词条页「变样」）；
#   - 先让词库自带的主题系统（applyTheme / matchMedia）按目标明暗切换；
#   - 再实测页面整体明暗，仍不一致时套用通用反色滤镜，明暗对调但保留
#     词库原生的配色关系与排版；
#   - 全程不出现任何词库名、不针对具体词库做特判。


def entry_css(mode: str) -> str:
    """返回指定主题模式下应用自生成页面的默认 CSS（不含任何词库覆盖）。"""
    return _CSS_DARK if mode == "dark" else _CSS_LIGHT


# ----------------------------------------------------------------------
# 词条页配色（通用方案：同一套规则对待所有词库，不含任何词库名）
# ----------------------------------------------------------------------

# 「词条页配色」下拉框的可选值
ENTRY_THEME_OPTIONS = [
    ("跟随应用主题", "follow"),
    ("保持词库原样", "native"),
    ("始终浅色", "light"),
    ("始终深色", "dark"),
]


def resolve_entry_theme(entry_theme: str, app_mode: str) -> str:
    """把配置里的 entry_theme 解析成词条页目标模式。

    返回 "light" / "dark" / "native"：
    - "native"：完全不干预词条页，词库长什么样就什么样；
    - "light" / "dark"：词条页需要呈现该明暗。
    """
    value = str(entry_theme or "follow")
    if value in ("light", "dark"):
        return value
    if value == "native":
        return "native"
    # follow（或任何未知值）→ 跟随应用主题
    return "dark" if app_mode == "dark" else "light"


# 通用反色滤镜：对每一个词库都完全一样，既不写死词库名，也不写死
# 任何词库专有的类名/标签。工作方式：
#   1) 先让词库自带的主题系统（applyTheme / matchMedia）切到目标明暗；
#   2) 实测页面整体明暗，若与目标不一致，才给 <html> 加 sd-invert 类，
#      用 invert(1) 翻转明暗、hue-rotate(180deg) 把色相转回来——
#      这样配色关系、层次、排版都保持词库原生设计，只是明暗对调；
#   3) 图片/视频等媒体再反一次，避免被翻成负片。
#
# 不强制设置 background：词条页画布色由 Qt 侧 setBackgroundColor 提供，
# 它不受 CSS 滤镜影响，天然等于目标明暗，无需在 CSS 里重复指定
# （强行指定反而会在翻转后变成相反的颜色）。
_CSS_ENTRY_FILTER = """
html.sd-invert{filter:invert(1) hue-rotate(180deg);}
html.sd-invert img,html.sd-invert video,html.sd-invert picture,
html.sd-invert canvas,html.sd-invert iframe,html.sd-invert embed,
html.sd-invert svg{filter:invert(1) hue-rotate(180deg);}
"""


def entry_filter_css() -> str:
    """通用反色滤镜 CSS（与具体词库无关，所有词库共用同一份）。"""
    return _CSS_ENTRY_FILTER


# ----------------------------------------------------------------------
# Qt 控件 QSS
# ----------------------------------------------------------------------

# 滚动条必须显式定义，否则 Fusion 会用默认绘制（换肤时不跟随，
# 表现为浅色主题下滚动条「滑块之外的轨道」仍是深色的）。
# 这里把滑块、轨道、上/下箭头、翻页区都写死成当前主题的颜色：
#   - 箭头上/下区域高度设为 0，隐藏原生三角箭头，只留滑块 + 轨道；
#   - add-page / sub-page 用透明，轨道底色由 QScrollBar 自身背景提供，
#     这样滑块之外就是一层干净的主题色，不会露出默认深色。
_SCROLLBAR_QSS_LIGHT = """
QScrollBar:vertical{
    background:#f3f4f6;border:none;width:12px;margin:0;padding:0;
}
QScrollBar:horizontal{
    background:#f3f4f6;border:none;height:12px;margin:0;padding:0;
}
QScrollBar::handle:vertical{
    background:#cbd5e1;border-radius:5px;min-height:28px;margin:2px;
}
QScrollBar::handle:vertical:hover{background:#94a3b8;}
QScrollBar::handle:vertical:pressed{background:#64748b;}
QScrollBar::handle:horizontal{
    background:#cbd5e1;border-radius:5px;min-width:28px;margin:2px;
}
QScrollBar::handle:horizontal:hover{background:#94a3b8;}
QScrollBar::handle:horizontal:pressed{background:#64748b;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{
    height:0px;width:0px;subcontrol-origin:margin;border:none;
}
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{
    width:0px;height:0px;subcontrol-origin:margin;border:none;
}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{
    background:transparent;
}
QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{
    background:transparent;
}
"""

_SCROLLBAR_QSS_DARK = """
QScrollBar:vertical{
    background:#2d2d30;border:none;width:12px;margin:0;padding:0;
}
QScrollBar:horizontal{
    background:#2d2d30;border:none;height:12px;margin:0;padding:0;
}
QScrollBar::handle:vertical{
    background:#4f5462;border-radius:5px;min-height:28px;margin:2px;
}
QScrollBar::handle:vertical:hover{background:#6b7280;}
QScrollBar::handle:vertical:pressed{background:#9ca3af;}
QScrollBar::handle:horizontal{
    background:#4f5462;border-radius:5px;min-width:28px;margin:2px;
}
QScrollBar::handle:horizontal:hover{background:#6b7280;}
QScrollBar::handle:horizontal:pressed{background:#9ca3af;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{
    height:0px;width:0px;subcontrol-origin:margin;border:none;
}
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{
    width:0px;height:0px;subcontrol-origin:margin;border:none;
}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{
    background:transparent;
}
QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{
    background:transparent;
}
"""


def scrollbar_qss(mode: str) -> str:
    """滚动条样式表（浅/深两套）。

    单独提供一份，方便挂到 QApplication 上：这样主窗口、生词本、
    词典管理等所有对话框的滚动条都能统一跟随主题，而不必在每个
    窗口的 QSS 里各写一遍。
    """
    return _SCROLLBAR_QSS_DARK if mode == "dark" else _SCROLLBAR_QSS_LIGHT


_APP_QSS_LIGHT = """
/* 搜索框与候选词列表同属一张卡片：外层画整框，内部两控件只留一条分隔线，
   拼成一个整体控件，而不是两个各自带框的独立部件。 */
QFrame#search_panel{
    border:1px solid #d1d5db;border-radius:8px;background:#fff;
}
/* 输入框与候选列表同属一张卡片，但用不同底色分成上下两段：
   输入框像"内嵌的填写区"，列表是纯白的结果区，一眼能分清哪里能打字。 */
QLineEdit#search_edit{
    border:none;border-bottom:1px solid #d1d5db;border-radius:7px 7px 0 0;
    padding:8px 12px;font-size:15px;background:#f1f3f5;color:#111827;
    selection-background-color:#dbeafe;
}
QLineEdit#search_edit:focus{background:#e8edf3;border-bottom-color:#2563eb;}
QListWidget#suggest_list{
    border:none;border-radius:0 0 7px 7px;background:#fff;
    font-size:14px;outline:0;
}
QListWidget#suggest_list::item{padding:5px 10px;color:#374151;}
QListWidget#suggest_list::item:hover{background:#f1f3f5;}
QListWidget#suggest_list::item:selected{background:#dbeafe;color:#111827;}
QTabBar::tab{padding:5px 14px;background:#f3f4f6;color:#4b5563;}
QTabBar::tab:selected{background:#fff;color:#1d4ed8;
    border:1px solid #e5e7eb;border-bottom:1px solid #fff;}
QStatusBar{color:#6b7280;}
QStatusBar QLabel{padding:0 10px;}
QComboBox#group_combo{
    border:1px solid #d1d5db;border-radius:13px;padding:3px 10px;
    font-size:13px;background:#fff;color:#374151;
}
QComboBox#group_combo:hover{border-color:#2563eb;}
QComboBox#group_combo::drop-down{border:none;width:16px;}
"""

_APP_QSS_DARK = """
QFrame#search_panel{
    border:1px solid #374151;border-radius:8px;background:#1e1e1e;
}
QLineEdit#search_edit{
    border:none;border-bottom:1px solid #374151;border-radius:7px 7px 0 0;
    padding:8px 12px;font-size:15px;background:#2d2d30;color:#d4d4d4;
    selection-background-color:#3b82f6;selection-color:#fff;
}
QLineEdit#search_edit:focus{background:#33333a;border-bottom-color:#60a5fa;}
QListWidget#suggest_list{
    border:none;border-radius:0 0 7px 7px;background:#1e1e1e;
    font-size:14px;outline:0;color:#d4d4d4;
}
QListWidget#suggest_list::item{padding:5px 10px;}
QListWidget#suggest_list::item:hover{background:#2d2d30;}
QListWidget#suggest_list::item:selected{background:#1f4e79;color:#fff;}
QTabBar::tab{padding:5px 14px;background:#2d2d30;color:#9ca3af;}
QTabBar::tab:selected{background:#1e1e1e;color:#93c5fd;
    border:1px solid #374151;border-bottom:1px solid #1e1e1e;}
QStatusBar{color:#9ca3af;}
QStatusBar QLabel{padding:0 10px;color:#9ca3af;}
QComboBox#group_combo{
    border:1px solid #374151;border-radius:13px;padding:3px 10px;
    font-size:13px;background:#2d2d30;color:#d4d4d4;
}
QComboBox#group_combo:hover{border-color:#60a5fa;}
QComboBox#group_combo::drop-down{border:none;width:16px;}
QToolButton{color:#d4d4d4;border:1px solid transparent;padding:4px 8px;border-radius:4px;}
QToolButton:hover{background:#374151;}
"""


def app_qss(mode: str) -> str:
    """主窗口（含顶栏控件 / 联想列表 / Tab / 搜索框）的样式表。"""
    base = _APP_QSS_DARK if mode == "dark" else _APP_QSS_LIGHT
    return base + scrollbar_qss(mode)


_WB_QSS_LIGHT = """
QListWidget#wb_group_list{
    border:1px solid #e5e7eb;border-radius:6px;background:#fff;font-size:14px;
    outline:0;
}
QListWidget#wb_group_list::item{padding:7px 10px;}
QListWidget#wb_group_list::item:selected{background:#dbeafe;color:#111827;}
QListWidget#wb_word_list{
    border:1px solid #e5e7eb;border-radius:6px;background:#fff;font-size:14px;
    outline:0;
}
QListWidget#wb_word_list::item{padding:5px 10px;}
QListWidget#wb_word_list::item:selected{background:#dbeafe;color:#111827;}
QLabel#wb_count{color:#6b7280;font-size:12px;padding:0 2px 2px 2px;}
QLabel#wb_title{color:#374151;font-size:12px;font-weight:600;}
QPushButton{padding:4px 10px;font-size:13px;}
"""

_WB_QSS_DARK = """
QListWidget#wb_group_list{
    border:1px solid #374151;border-radius:6px;background:#2d2d30;font-size:14px;
    outline:0;color:#d4d4d4;
}
QListWidget#wb_group_list::item{padding:7px 10px;}
QListWidget#wb_group_list::item:selected{background:#1f4e79;color:#fff;}
QListWidget#wb_word_list{
    border:1px solid #374151;border-radius:6px;background:#2d2d30;font-size:14px;
    outline:0;color:#d4d4d4;
}
QListWidget#wb_word_list::item{padding:5px 10px;}
QListWidget#wb_word_list::item:selected{background:#1f4e79;color:#fff;}
QLabel#wb_count{color:#9ca3af;font-size:12px;padding:0 2px 2px 2px;}
QLabel#wb_title{color:#e5e7eb;font-size:12px;font-weight:600;}
QPushButton{padding:4px 10px;font-size:13px;}
"""


def wb_qss(mode: str) -> str:
    """生词本对话框的样式表。"""
    base = _WB_QSS_DARK if mode == "dark" else _WB_QSS_LIGHT
    return base + scrollbar_qss(mode)


# ----------------------------------------------------------------------
# 词典管理对话框 / 提示 / 告警的颜色
# ----------------------------------------------------------------------

STATUS_LABELS_LIGHT = {
    "ready": ("就绪", "#059669"),
    "loading": ("加载中", "#b45309"),
    "missing": ("文件缺失", "#dc2626"),
    "disabled": ("已禁用", "#6b7280"),
}

STATUS_LABELS_DARK = {
    "ready": ("就绪", "#34d399"),
    "loading": ("加载中", "#fbbf24"),
    "missing": ("文件缺失", "#f87171"),
    "disabled": ("已禁用", "#9ca3af"),
}


def status_labels(mode: str) -> dict:
    """词库管理对话框中状态列的 {状态键: (文本, 颜色)} 映射。"""
    return STATUS_LABELS_DARK if mode == "dark" else STATUS_LABELS_LIGHT


def tip_color(mode: str) -> str:
    """通用次要提示文本颜色（设置对话框 tip、词库管理 tip）。"""
    return "#9ca3af" if mode == "dark" else "#6b7280"


def warn_style(mode: str) -> str:
    """词库管理对话框文件缺失告警条样式。"""
    if mode == "dark":
        return (
            "color:#fca5a5;font-size:12px;background:#3b1f1f;"
            "border:1px solid #7f1d1d;border-radius:6px;padding:6px 8px;"
        )
    return (
        "color:#dc2626;font-size:12px;background:#fef2f2;"
        "border:1px solid #fecaca;border-radius:6px;padding:6px 8px;"
    )


# ----------------------------------------------------------------------
# 主题管理器
# ----------------------------------------------------------------------

class ThemeManager(QObject):
    """统一管理当前主题：持有 Config，解析当前 mode，发送切换信号。

    在 QApplication 创建后、MainWindow 创建前实例化一次。
    """

    theme_changed = Signal(str)  # 新的实际主题模式 "light" / "dark"

    def __init__(self, config, qapp=None, parent=None):
        super().__init__(parent)
        self._config = config
        self._qapp = qapp
        self._mode = resolve_theme(str(config["theme"]))
        self._entry_theme = str(config["entry_theme"])

    @property
    def mode(self) -> str:
        """当前生效的主题模式（"light" 或 "dark"）。"""
        return self._mode

    def apply_to_qt(self):
        """把当前主题应用到整个 QApplication。"""
        if self._qapp is None:
            return
        # 先清除上一级的全局 QSS，防止叠加
        self._qapp.setStyleSheet("")

        from PySide6.QtGui import QColor, QPalette
        from PySide6.QtWidgets import QApplication

        # Fusion 样式是跨平台的，能配合自定义 QPalette 做出稳定的深浅色
        QApplication.setStyle("Fusion")

        if self._mode == "dark":
            self._apply_dark_palette()
        else:
            # Fusion 的默认 palette 在 Windows 深色系统上也会被染暗，
            # 所以浅色模式同样手动构造完整调色板，确保一定是白色系。
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Window, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(31, 41, 55))
            palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.AlternateBase,
                             QColor(249, 250, 251))
            palette.setColor(QPalette.ColorRole.ToolTipBase,
                             QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.ToolTipText,
                             QColor(31, 41, 55))
            palette.setColor(QPalette.ColorRole.Text, QColor(31, 41, 55))
            palette.setColor(QPalette.ColorRole.Button,
                             QColor(240, 240, 240))
            palette.setColor(QPalette.ColorRole.ButtonText,
                             QColor(31, 41, 55))
            palette.setColor(QPalette.ColorRole.BrightText,
                             QColor(220, 38, 38))
            palette.setColor(QPalette.ColorRole.Link,
                             QColor(37, 99, 235))
            palette.setColor(QPalette.ColorRole.Highlight,
                             QColor(219, 234, 254))
            palette.setColor(QPalette.ColorRole.HighlightedText,
                             QColor(17, 24, 39))
            palette.setColor(QPalette.ColorRole.PlaceholderText,
                             QColor(156, 163, 175))
            palette.setColor(QPalette.ColorGroup.Disabled,
                             QPalette.ColorRole.WindowText,
                             QColor(156, 163, 175))
            palette.setColor(QPalette.ColorGroup.Disabled,
                             QPalette.ColorRole.Text,
                             QColor(156, 163, 175))
            palette.setColor(QPalette.ColorGroup.Disabled,
                             QPalette.ColorRole.ButtonText,
                             QColor(156, 163, 175))
            self._qapp.setPalette(palette)

        # 最后在 QApplication 级挂一份滚动条样式：这样主窗口之外的
        # 对话框（生词本 / 词典管理 / 设置等）也能拿到正确颜色的滚动条，
        # 而不会退回 Fusion 的默认绘制（浅色主题下轨道发黑）。
        # 主窗口与各对话框自己的 setStyleSheet 会覆盖同名的规则，
        # 但内容一致，不存在冲突。
        self._qapp.setStyleSheet(scrollbar_qss(self._mode))

    def _apply_dark_palette(self):
        from PySide6.QtGui import QColor, QPalette
        from PySide6.QtWidgets import QApplication
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(212, 212, 212))
        palette.setColor(QPalette.ColorRole.Base, QColor(45, 45, 48))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(37, 37, 38))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(45, 45, 48))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(212, 212, 212))
        palette.setColor(QPalette.ColorRole.Text, QColor(212, 212, 212))
        palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 48))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(212, 212, 212))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(239, 83, 80))
        palette.setColor(QPalette.ColorRole.Link, QColor(96, 165, 250))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(31, 78, 121))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(120, 120, 120))
        palette.setColor(QPalette.ColorGroup.Disabled,
                         QPalette.ColorRole.WindowText, QColor(120, 120, 120))
        palette.setColor(QPalette.ColorGroup.Disabled,
                         QPalette.ColorRole.Text, QColor(120, 120, 120))
        palette.setColor(QPalette.ColorGroup.Disabled,
                         QPalette.ColorRole.ButtonText, QColor(120, 120, 120))
        self._qapp.setPalette(palette)

    def _apply_light_palette(self):
        # 现在不再单独调用，合并到 apply_to_qt 里用 standardPalette()
        pass

    def reapply(self):
        """配置改变后重新解析并应用主题（主题或词条页配色变了则发信号）。

        entry_theme 也要纳入比较：只改「词条页配色」而外观主题没变时，
        同样需要通知 MainWindow 重新渲染当前词条，否则新设置要等下次查词
        才生效。
        """
        new_mode = resolve_theme(str(self._config["theme"]))
        new_entry = str(self._config["entry_theme"])
        changed = (new_mode != self._mode) or (new_entry != self._entry_theme)
        self._mode = new_mode
        self._entry_theme = new_entry
        # 无论是否变化都重新应用一次 Qt 样式兜底
        self.apply_to_qt()
        if changed:
            self.theme_changed.emit(new_mode)
