"""国际化（i18n）支持：简体中文（源语言）+ 英文。

设计取舍：
- 源语言是中文，因此 ``_("中文")`` 在默认语言（zh_CN）下直接原样返回，
  不需要为每种语言维护「msgid」编号——以可见的中文文本本身作 key。
- 其它语言在翻译表里按「中文原文 -> 译文」映射；查不到时回退到中文原文
  （不会崩，只是该处仍是中文）。
- 动态文本用 ``_("模板{}").format(x)``，占位符统一用 ``{}``。
- 切换语言后整进程重启（见 ``restart_application``），避免逐个控件重刷文本。
"""

from __future__ import annotations

import os
import sys

DEFAULT_LANGUAGE = "zh_CN"
LANGUAGE_NAMES = {
    "zh_CN": "简体中文",
    "en_US": "English",
}

#: 各语言的译文表，按「中文原文 -> 译文」映射。
_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en_US": {
        # ---- 通用 / 顶栏 ----
        "后退": "Back",
        "重新加载": "Reload",
        "全选": "Select all",
        "前进": "Forward",
        "搜索「{}」": "Search “{}”",
        "输入单词，回车查词": "Type a word, press Enter to look up",
        "输入单词查询，回车查词（Ctrl+Alt+D 显示/隐藏窗口）":
            "Look up a word; press Enter (Ctrl+Alt+D to show/hide window)",
        "点 ★ 选择加入 / 移出哪些生词本分组":
            "Click ★ to choose which wordbook groups to add/remove this entry",
        "词库": "Dictionaries",
        "管理 MDX 词库（导入 / 删除 / 优先级）":
            "Manage MDX dictionaries (import / delete / order)",
        "生词本": "Wordbook",
        "查看生词本": "View wordbook",
        "历史": "History",
        "查看查询历史": "View lookup history",
        "更多": "More",
        "置顶窗口、设置、关于": "Pin window, Settings, About",
        "置顶窗口": "Pin window",
        "窗口常驻最前": "Keep window always on top",
        "设置": "Settings",
        "快捷键等设置": "Shortcuts and other settings",
        "关于": "About",
        "关于本软件": "About this software",

        # ---- 设置 ----
        "显示 / 隐藏主窗口：": "Show / hide main window:",
        "默认": "Default",
        "屏幕划词取词：": "Screen text capture:",
        "启用屏幕划词取词": "Enable screen text capture",
        "点击关闭按钮时最小化到系统托盘（不勾选则直接退出）":
            "Minimize to system tray on close (uncheck to quit directly)",
        "点击左侧候选词条时，将词条填入搜索框":
            "Fill the search box with the selected suggestion",
        "禁止词典访问网络（强制离线）":
            "Block dictionary network access (force offline)",
        "记录查询历史（可在「历史」中查看）":
            "Record lookup history (viewable under History)",
        "外观主题：": "Appearance theme:",
        "词条页配色：": "Entry page colors:",
        "语言：": "Language:",
        "切换语言需要重启程序才能完全生效。":
            "Changing the language requires a restart to take full effect.",
        "恢复为默认快捷键：": "Restore default shortcut: ",
        "关闭时：点击左侧词条只显示释义，不改变上方搜索框内容；"
        "开启时：点击后搜索框也会变成该词条（默认关闭）":
            "Off: clicking a suggestion shows its definition only and leaves the "
            "search box unchanged. On: the search box also becomes that word "
            "(default: off).",
        "勾选后：所有词库的网络请求（在线发音 / 图片等）将被拦截，"
        "仅可使用词库自带的离线资源。\n"
        "不勾选（默认）：允许词库按需在线获取资源。":
            "Checked: all dictionary network requests (online audio / images, "
            "etc.) are blocked; only the dictionary's bundled offline resources "
            "are available.\n"
            "Unchecked (default): dictionaries may fetch resources online on "
            "demand.",
        "开启后：每次查词会自动记入查询历史，方便回头翻看。\n"
        "关闭后：不再新增记录，已有历史仍保留，可随时在「历史」中清空。":
            "On: every lookup is recorded to history for later review.\n"
            "Off: no new records are added; existing history is kept and can be "
            "cleared anytime under History.",
        "选择「跟随系统」后，会根据 Windows 的深色/浅色设置自动切换。\n切换主题会立即生效，无需重启。":
            "Choosing “Follow system” switches with Windows dark/light mode.\n"
            "Theme changes apply immediately, no restart needed.",
        "只对「词条正文」生效，应用窗口本身始终跟随上面的外观主题。\n"
        "跟随应用主题：对所有词库使用同一套通用方案，不针对任何具体词库。\n"
        "保持词库原样：完全不干预词条页，词库设计是什么样就显示什么样。\n"
        "若觉得通用方案的处理效果不理想，选「保持词库原样」即可。":
            "Applies only to the entry body; the app window always follows the "
            "appearance theme above.\n"
            "Follow app theme: one generic scheme for all dictionaries, not "
            "tailored to any specific one.\n"
            "Keep dictionary original: do not touch the entry page at all; it "
            "shows exactly as the dictionary designed.\n"
            "If the generic scheme does not look good, choose "
            "“Keep dictionary original”.",
        "提示：快捷键请避免与其他软件冲突；划词取词通过模拟 Ctrl+C 读取"
        "选中文字，随后自动恢复剪贴板内容。":
            "Tip: avoid shortcut conflicts with other apps; text capture "
            "simulates Ctrl+C to read the selection, then restores the clipboard.",
        "跟随系统": "Follow system",
        "浅色": "Light",
        "深色": "Dark",
        "跟随应用主题": "Follow app theme",
        "保持词库原样": "Keep dictionary original",
        "始终浅色": "Always light",
        "始终深色": "Always dark",

        # ---- 关于 ----
        "关于 {}": "About {}",
        "一款 Windows 上的 MDX 词典：添加自己的 .mdx 词库后即加即用，"
        "查词全程在你自己的电脑上完成，不上传任何内容。":
            "A Windows MDX dictionary: add your own .mdx files and look up "
            "instantly; everything runs locally on your computer, nothing "
            "is uploaded.",
        "开源地址": "Source code",
        "问题反馈": "Feedback",
        "在 GitHub 上提交问题": "Report an issue on GitHub",
        "已启用词典": "Enabled dictionaries",
        "本软件只负责本地解析与展示，词典文件由你自行提供，"
        "其中的内容版权归各词典原作者所有。":
            "This app only parses and displays locally. Dictionary files are "
            "provided by you; their content copyright belongs to the original "
            "authors.",
        "复制开源地址": "Copy source URL",
        "把项目地址复制到剪贴板": "Copy the project URL to clipboard",
        "查看新版本": "Check for updates",
        "打开 Releases 页面，看看有没有更新的版本":
            "Open the Releases page to see if a newer version is available",

        # ---- 托盘 ----
        "显示 / 隐藏主窗口": "Show / hide main window",
        "词库管理…": "Manage dictionaries…",
        "生词本…": "Wordbook…",
        "查询历史…": "History…",
        "查询历史": "Lookup history",
        "关于 TinyDict…": "About TinyDict…",
        "退出": "Quit",
        "已最小化到系统托盘，右键托盘图标可选择退出。":
            "Minimized to the system tray. Right-click the tray icon to quit.",
        "划词取词：没读到选中的文字。\n"
        "请先在其他程序中选中文字再按快捷键；少数程序不支持复制，可试试用鼠标右键复制。":
            "Text capture: no selected text was read.\n"
            "Please select text in another app first, then press the shortcut; "
            "a few apps do not support copy, try right-click copy.",

        # ---- 生词本 ----
        "分组": "Groups",
        "全部": "All",
        "清空生词本": "Clear wordbook",
        "新建": "New",
        "重命名": "Rename",
        "重命名分组": "Rename group",
        "删除": "Delete",
        "删除分组": "Delete group",
        "上移": "Move up",
        "下移": "Move down",
        "加入到分组 ▸": "Add to group ▸",
        "把选中的生词加入其它分组（保留原有分组归属）":
            "Add the selected words to other groups (keeping their existing "
            "group membership)",
        "从本分组移除": "Remove from this group",
        "把选中的生词移出当前分组；只属于本分组的词会自动归入「默认分组」":
            "Remove the selected words from the current group; words that "
            "belong only to this group auto-move to “Default group”",
        "彻底删除": "Delete permanently",
        "清空本分组": "Clear this group",
        "导入…": "Import…",
        "导出生词本": "Export wordbook",
        "从 txt / csv 导入生词，或从 json 备份恢复":
            "Import words from txt / csv, or restore from a json backup",
        "导出…": "Export…",
        "导出当前分组的生词；选 json 则导出含分组结构的完整备份":
            "Export words of the current group; choosing json exports a full "
            "backup including group structure",
        "关闭": "Close",
        "全部（{}）": "All ({})",
        "「{}」共 {} 个生词 · 双击查词": "“{}” has {} words · double-click to look up",
        "新建分组": "New group",
        "分组名称：": "Group name:",
        "分组「{}」已存在。": "Group “{}” already exists.",
        "已新建分组「{}」": "Created group “{}”",
        "已重命名为「{}」": "Renamed to “{}”",
        "「默认分组」不可删除（可重命名）。\n它是点 ★ 时的兜底分组，"
        "删除后新收藏的生词将无处可放。":
            "“Default group” cannot be deleted (you can rename it).\n"
            "It is the fallback group when clicking ★; deleting it would leave "
            "newly favorited words with nowhere to go.",
        "确定删除分组「{}」？": "Delete group “{}”?",
        "「仅删除分组」：分组内的生词继续保留在生词本中"
        "（只属于本分组的词会自动归入「默认分组」）。\n"
        "「同时删除生词」：这些生词将从生词本彻底移除"
        "（包括它们在其它分组中的记录）。":
            "“Delete group only”: words in the group stay in the wordbook "
            "(words belonging only to this group auto-move to “Default group”).\n"
            "“Delete words too”: these words are removed from the wordbook "
            "entirely (including their records in other groups).",
        "仅删除分组": "Delete group only",
        "同时删除生词": "Delete words too",
        "取消": "Cancel",
        "已删除分组「{}」（{} 个生词保留）":
            "Deleted group “{}” ({} words kept)",
        "已删除分组「{}」及其中的 {} 个生词":
            "Deleted group “{}” and its {} words",
        "新建分组…": "New group…",
        "重命名…": "Rename…",
        "删除分组…": "Delete group…",
        "加入到分组": "Add to group",
        "请先在右侧选择生词（可按住 Ctrl / Shift 多选）。":
            "Select words on the right first (hold Ctrl / Shift for multiple).",
        "已把 {} 个生词加入「{}」（{} 个已在其中）":
            "Added {} words to “{}” ({} already there)",
        "已从「{}」移除 {} 个生词": "Removed {} words from “{}”",
        "确定从生词本彻底删除选中的 {} 个生词？\n"
        "（会同时移除它们在所有分组中的记录，不可撤销）":
            "Permanently delete the selected {} words from the wordbook?\n"
            "(Their records in all groups are also removed, cannot be undone)",
        "清空": "Clear",
        "确定清空整个生词本？\n所有生词及其分组关联都会被删除，不可撤销。":
            "Clear the entire wordbook?\nAll words and their group links are "
            "deleted, cannot be undone.",
        "确定清空分组「{}」？\n只属于本分组的生词会被彻底删除"
        "（同时也在其它分组的词会保留在那些分组里）。":
            "Clear group “{}”?\nWords belonging only to this group are deleted "
            "permanently (words also in other groups are kept there).",
        "确定清空分组「{}」？\n只属于本分组的生词会自动归入「默认分组」，不会丢失。":
            "Clear group “{}”?\nWords belonging only to this group auto-move to "
            "“Default group” and are not lost.",
        "已清空「{}」": "Cleared “{}”",
        "已彻底删除 {} 个生词": "Permanently deleted {} words",
        "导出": "Export",
        "当前分组没有可导出的生词。":
            "The current group has no words to export.",
        "导出失败": "Export failed",
        "写入文件失败：\n{}": "Failed to write file:\n{}",
        "已导出 {} 个生词到 {}": "Exported {} words to {}",
        "导入生词": "Import words",
        "导入失败": "Import failed",
        "读取文件失败：\n{}": "Failed to read file:\n{}",
        "导入": "Import",
        "没有从「{}」读到生词。\n纯文本 / CSV 里每行写一个词即可"
        "（CSV 取第一列）。":
            "No words were read from “{}”.\n"
            "In plain text / CSV, put one word per line (CSV uses the first "
            "column).",
        "备份文件里没有生词。": "The backup file contains no words.",
        "导入备份": "Import backup",
        "备份包含 {} 个生词、{} 个分组。\n将合并到现有生词本："
        "缺少的分组自动新建，重复的词跳过。":
            "Backup contains {} words and {} groups.\n"
            "It will be merged into the existing wordbook: missing groups are "
            "created, duplicate words skipped.",
        "已导入备份：新增 {} 个生词、{} 条分组归属、{} 个分组":
            "Imported backup: {} new words, {} group links, {} groups",
        "已从 {} 导入 {} 个生词到「{}」{}":
            "Imported {} words from {} into “{}”{}",
        "（{} 个已在其中）": "({} already there)",
        "查词": "Look up",
        "复制": "Copy",
        "从「{}」移除": "Remove from “{}”",
        "{}    （{}）": "{}    ({})",

        # ---- 词库管理 ----
        "词库管理": "Dictionary manager",
        "就绪": "Ready",
        "加载中": "Loading",
        "文件缺失": "File missing",
        "已禁用": "Disabled",
        "已加载完成，可正常查询": "Loaded, ready for lookup",
        "正在后台加载 key 索引，稍候即可查询":
            "Loading key index in the background; available shortly",
        "已取消启用，不参与查询（勾选可重新启用）":
            "Disabled, not used in lookup (check to enable)",
        "原始 .mdx 文件找不到，需「修复路径」":
            "Original .mdx file not found; use “Repair path”",
        "原始 .mdx 文件找不到（可能被改名 / 移动 / 删除）":
            "Original .mdx file not found (possibly renamed/moved/deleted)",
        "列表顺序即查询优先级（排在前面的词库优先展示结果）。"
        "注册即时生效：词条保留在原始 .mdx 文件中，按需读取，无需等待导入；"
        "删除仅取消注册，不影响原文件。":
            "List order is the lookup priority (dictionaries higher up are "
            "shown first). Registration takes effect immediately: entries stay "
            "in the original .mdx file and are read on demand, no import wait; "
            "removing only unregisters, the original file is untouched.",
        "启用": "Enabled",
        "词库名称": "Dictionary",
        "词条数": "Entries",
        "状态": "Status",
        "添加文件…": "Add file…",
        "添加失败": "Add failed",
        "添加文件夹…": "Add folder…",
        "重新挂载": "Re-mount",
        "修复路径…": "Repair path…",
        "为路径失效（改名 / 移动过文件夹）的词库重新指定 .mdx 文件":
            "Re-select the .mdx file for a dictionary whose path is broken "
            "(renamed/moved folder)",
        "移除词库": "Remove",
        "修复路径": "Repair path",
        "请先选中一行词库。": "Select a dictionary row first.",
        "为「{}」选择 .mdx 文件": "Select .mdx file for “{}”",
        "修复失败": "Repair failed",
        "已更新「{}」的词库路径为：\n{}\n\n正在后台重新加载。":
            "Updated the dictionary path for “{}” to:\n{}\n\n"
            "Reloading in the background.",
        "修复成功": "Repair succeeded",
        "确定移除词库「{}」？\n仅从词库列表取消注册，原始 .mdx/.mdd 文件不受影响，"
        "可随时重新添加。":
            "Remove dictionary “{}” from the list?\n"
            "Only unregisters it; the original .mdx/.mdd files are untouched "
            "and can be re-added anytime.",
        "选择 MDX 词库文件（可多选）": "Select MDX dictionary files (multiple)",
        "选择词库文件夹（将扫描其中全部 .mdx）":
            "Select a dictionary folder (scans all .mdx inside)",
        "部分文件添加失败": "Some files failed to add",
        "以下文件添加失败：\n\n{}": "The following files failed to add:\n\n{}",
        "添加完成": "Added",
        "已添加 {} 部词库并开始后台加载。{}\n"
        "加载完成后即可查询（列表「状态」列显示进度）。":
            "Added {} dictionaries and started background loading.{}\n"
            "Ready to look up once loading finishes (the Status column shows "
            "progress).",
        "（跳过已添加 {} 部）": "({} already added skipped)",
        "原始 .mdx 文件找不到（可能被改名 / 移动 / 删除）":
            "Original .mdx file not found (possibly renamed/moved/deleted)",
        "⚠ 有 {} 部词库文件缺失（通常是文件夹被改名 / 移动后路径失效）：{}。\n"
        "选中后点「修复路径…」重新指定 .mdx 文件即可恢复。":
            "⚠ {} dictionary file(s) missing (usually the folder was "
            "renamed/moved so the path is invalid): {}\n"
            "Select it and click “Repair path…” to re-specify the .mdx file to "
            "recover.",

        # ---- 查询历史 ----
        "输入片段筛选查过的词": "Filter looked-up words",
        "只显示包含这段文字的记录（不区分大小写）":
            "Show only records containing this text (case-insensitive)",
        "查询选中的记录（也可直接双击）":
            "Look up the selected record (or just double-click)",
        "从历史中移除选中的记录": "Remove the selected records from history",
        "清空历史": "Clear history",
        "匹配 {} 条（共 {} 条） · 双击查词":
            "Matched {} of {} · double-click to look up",
        "共 {} 条查询记录 · 双击查词": "{} lookup records · double-click to look up",
        "{} · 查过 {} 次": "{} · looked up {} times",
        "删除记录": "Delete record",
        "删除这条记录": "Delete this record",
        "请先选择要删除的记录（可按住 Ctrl / Shift 多选）。":
            "Select records to delete first (hold Ctrl / Shift for multiple).",
        "确定从查询历史中删除选中的 {} 条记录？":
            "Delete the selected {} record(s) from history?",
        "确定清空全部查询历史？\n（只清除这里的记录，不影响生词本和词库）":
            "Clear all lookup history?\n"
            "(Only this list is cleared; wordbook and dictionaries are "
            "unaffected)",

        # ---- 主窗口状态 / 提示 ----
        "未找到词条": "No entry found",
        "还有 {} 部词库正在加载，完成后自动重新查询":
            "Still loading {} dictionary(ies); will re-query when done",
        "词典：{}": "Dictionary: {}",
        " · 另有 {} 部词库命中": " · {} other dictionaries also matched",
        " · 另有 {} 部词库仍在加载，完成后自动补齐":
            " · {} more still loading, will complete automatically",
        "当前未启用查询历史。": "Lookup history is currently disabled.",
        "{} · 最近查过": "{} · looked up recently",
        "未启用任何词库，点击「词库」添加 .mdx 文件或词库文件夹":
            "No dictionaries enabled. Click “Dictionaries” to add .mdx files or "
            "a folder",
        "⚠ {} 部词库文件缺失或无法加载，"
        "<a href='manage'>点击「词库管理」查看并修复</a>":
            "⚠ {} dictionary file(s) missing or failed to load, "
            "<a href='manage'>click “Dictionary manager” to view and repair</a>",
        "缺失词库：{}\n（通常是文件夹被改名 / 移动后路径失效）\n"
        "打开「词库管理」选中后点「修复路径…」重新指定 .mdx 文件":
            "Missing dictionaries: {}\n"
            "(usually the folder was renamed/moved so the path is invalid)\n"
            "Open “Dictionary manager”, select it, then click "
            "“Repair path…” to re-specify the .mdx file",
        "词库加载中 {}/{} 部（{} 部加载中） · 已就绪 {} 词条":
            "Loading dictionaries {}/{} ({} loading) · {} entries ready",
        "已启用 {} 部词库 · {} 词条": "{} dictionaries enabled · {} entries",
        "{} 部（{} 部已就绪）": "{} dictionaries ({} ready)",
        "词库加载中 {}/{}：{}": "Loading dictionaries {}/{}: {}",
        "已新建分组：{}": "Created group: {}",
        "已加入「{}」：{}": "Added to “{}”: {}",
        "{} 已在「{}」中": "{} is already in “{}”",
        "已从「{}」移除：{}": "Removed from “{}”: {}",
        "{}（{}）": "{name} ({count})",
        "＋ 新建分组…": "+ New group…",
        "所属分组：{}\n点 ★ 选择加入 / 移出哪些生词本分组":
            "Groups: {}\nClick ★ to choose which wordbook groups to add/remove "
            "this entry",
        "所属分组：{}\n": "Groups: {}\n",
        "{} · 最近查过": "{} · looked up recently",

        # ---- 备份文件解析错误（core/wordbook_io.py）----
        "不是 TinyDict 生词本备份文件": "Not a TinyDict wordbook backup file",
        "不支持的备份文件版本：{}": "Unsupported backup file version: {}",
        "无法解析：{}": "Failed to parse: {}",
    },
}

_current = DEFAULT_LANGUAGE


def get_language() -> str:
    """当前生效的语言代码（如 "zh_CN" / "en_US"）。"""
    return _current


def set_language(code: str) -> None:
    """切换语言。非法值忽略（保持当前语言）。"""
    global _current
    if code in LANGUAGE_NAMES:
        _current = code


def available_languages():
    """返回 [(code, 显示名), ...]，供设置界面生成下拉。"""
    return list(LANGUAGE_NAMES.items())


def _(text: str) -> str:
    """按当前语言翻译可见文本。

    - 非字符串（如 None、数值）原样返回；
    - 源语言（zh_CN）下原样返回（源字符串本身就是中文）；
    - 其它语言查表，查不到回退到原文（不会崩）。
    """
    if not isinstance(text, str) or _current == DEFAULT_LANGUAGE:
        return text
    table = _TRANSLATIONS.get(_current)
    if table is None:
        return text
    return table.get(text, text)


def restart_application() -> None:
    """以相同参数重启当前进程。

    用于切换语言等「需要重建全部 UI」的场景——比逐个控件重刷文本更可靠。
    调用前请先保存窗口几何等需要持久化的状态。
    """
    # 打包成 exe 后 sys.argv[0] 本身就是可执行文件路径，直接复用；
    # 以 python 脚本方式运行时则需要把解释器补到最前面。
    args = sys.argv if getattr(sys, "frozen", False) else [sys.executable, *sys.argv]
    os.execv(sys.executable, args)
