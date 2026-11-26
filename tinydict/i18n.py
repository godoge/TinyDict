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
        "先选要导出的生词本和导出格式（默认全部生词本 / CSV）":
            "Choose which wordbooks to export and the format "
            "(all wordbooks / CSV by default)",
        # ---- 导出选项对话框（范围 + 格式）
        "导出哪些生词本：": "Wordbooks to export:",
        "全部生词本（默认）": "All wordbooks (default)",
        "全不选": "Select none",
        "导出格式：": "Export format:",
        "CSV 表格（推荐）": "CSV spreadsheet (recommended)",
        "纯文本（每行一个词）": "Plain text (one word per line)",
        "JSON 完整备份": "JSON full backup",
        "含分组与各分组收藏时间，Excel 可直接打开。":
            "Includes groups and per-group timestamps; opens directly in "
            "Excel.",
        "每行一个词，不含分组与收藏时间，适合纯词表。":
            "One word per line, without groups or timestamps; "
            "good for a plain word list.",
        "完整备份：保留分组结构（含空分组）与各分组收藏时间。":
            "Full backup: keeps the group structure (including empty groups) "
            "and per-group timestamps.",
        "所选生词本里没有可导出的生词。":
            "The selected wordbooks have no words to export.",
        "{} 等 {} 个分组": "{} etc. ({} groups)",
        "CSV 表格（含分组与各分组收藏时间） (*.csv)":
            "CSV spreadsheet (groups and per-group timestamps) (*.csv)",
        "纯文本（每行一个词） (*.txt)":
            "Plain text (one word per line) (*.txt)",
        "JSON 完整备份（含分组结构） (*.json)":
            "JSON full backup (includes group structure) (*.json)",
        "关闭": "Close",
        "全部（{}）": "All ({})",
        "「{}」共 {} 个生词 · 双击查词": "“{}” has {} words · double-click to look up",
        # ---- 生词本搜索 ----
        "搜索当前分组的生词…": "Search words in this group…",
        "只显示包含这段文字的生词（不区分大小写）。"
        "要搜整个生词本，请先在左侧选择「全部」。":
            "Show only words containing this text (case-insensitive). "
            "To search the whole wordbook, select “All” on the left first.",
        "「{}」匹配 {} 个（共 {} 个） · 双击查词":
            "“{}” matched {} of {} · double-click to look up",
        "清空的是整个「{}」，不受上方搜索影响。":
            "This clears the whole “{}”, regardless of the search above.",
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
        "没有从「{}」读到生词。\n"
        "纯文本每行写一个词；带表头的 CSV 会按原分组还原。":
            "No words were read from “{}”.\n"
            "Plain text: one word per line; a CSV with a header is restored "
            "into its original groups.",
        "备份文件里没有生词。": "The backup file contains no words.",
        "导入备份": "Import backup",
        "备份包含 {} 个生词、{} 个分组。\n"
        "记录了每个词的归属与各分组各自的收藏时间，将按原名还原；\n"
        "与现有数据合并，不会删除任何已有的分组或生词。":
            "Backup contains {} words and {} groups.\n"
            "It records each word's groups and the added time in each group, "
            "and restores them by name.\n"
            "This merges with existing data and never deletes any group or "
            "word.",
        "导入 {} 个生词": "Import {} words",
        "{} 等 {} 个": "{} etc. ({} groups)",
        "\n另有 {} 个词没写分组，将放入「{}」。":
            "\n{} words have no group and will go into “{}”.",
        "文件里记录了 {} 个生词的分组：{}。\n"
        "这些词会回到原来的分组，并保留各自的收藏时间；"
        "本机没有的同名分组会自动新建。{}\n"
        "与现有数据合并，不会删除任何已有的分组或生词。":
            "The file records groups for {} words: {}.\n"
            "These words go back to their original groups with their own "
            "added times; groups missing here are created automatically.{}\n"
            "This merges with existing data and never deletes any group or "
            "word.",
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
        "无需重复添加": "Already in the list",
        "选择的 {} 部词库已经在列表中了，无需重复添加。":
            "The {} dictionaries you selected are already in the list; "
            "no need to add them again.",
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
        "「{}」在词库里没有对应词条，仍可作为当前词条收藏到生词本。":
            "“{}” has no entry in the loaded dictionaries, but you can still "
            "keep it as the current entry and save it to a wordbook.",
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
        "已取消收藏：{}": "Removed from wordbook: {}",
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

        # ---- 词条笔记 / 跨设备同步（core/notes.py, ui/notes_dialog.py）----
        "笔记面板": "Notes panel",
        "显示 / 隐藏词条下方的笔记面板（笔记会自动保存）":
            "Show/hide the notes panel below the entry (saved automatically)",
        "笔记": "Notes",
        "显示笔记": "Show notes",
        "这个词条已有笔记；勾选「显示笔记」可展开查看":
            "This entry has notes; tick \"Show notes\" to view them",
        "笔记 · {}": "Notes · {}",
        "查看两端冲突的笔记并人工合并":
            "Review notes changed on both devices and merge manually",
        "导出笔记备份，或从另一台设备导入并合并":
            "Export a notes backup, or import and merge one from another device",
        "给当前词条写点笔记…（自动保存，词库没收录的词也可以写）":
            "Write a note for this entry… (saved automatically; works even for "
            "words missing from your dictionaries)",
        "正在保存…": "Saving…",
        "已保存": "Saved",
        "保存失败：{}": "Save failed: {}",
        "导入 / 导出": "Import / Export",
        "{} 条冲突待合并": "{} conflicts to merge",
        "笔记导入 / 导出": "Notes Import / Export",
        "导出格式：": "Export format:",
        "JSON 完整备份（推荐，可双向同步）":
            "JSON full backup (recommended, two-way sync)",
        "手机版生词本备份 JSON（带笔记）":
            "Mobile wordbook backup JSON (with notes)",
        "CSV 表格": "CSV spreadsheet",
        "手机版生词本 CSV（带笔记）": "Mobile wordbook CSV (with notes)",
        "MDX 词库快照（只读）": "MDX dictionary snapshot (read-only)",
        "导出到文件…": "Export to file…",
        "尚未选择文件": "No file selected",
        "选择文件…": "Choose file…",
        "开始导入": "Import",
        "导出笔记": "Export notes",
        "导出完成": "Export complete",
        "导入笔记": "Import notes",
        "导入完成": "Import complete",
        "导入完成，可以继续选择其它文件。":
            "Import complete. You can choose another file.",
        "合并冲突的笔记": "Merge conflicting notes",
        "保留本机": "Keep local",
        "采用导入": "Use imported",
        "保存合并结果": "Save merged result",
        "从手机或另一台电脑导出的笔记文件：":
            "Notes file exported from a phone or another computer:",
        "冲突处理方式：": "Conflict handling:",
        "还没有任何笔记。": "There are no notes yet.",
        "这个文件里没有笔记。\n如果是手机版导出的生词本备份，需要先在手机端合入笔记导出补丁。":
            "No notes found in this file.\nIf this is a wordbook backup from the "
            "mobile app, install the notes export patch there first.",
        "导入完成：{}。": "Import complete: {}.",
        "两端都修改过同一条笔记时，本机版本已保留。下面可以逐条选择保留哪个版本，或手工拼出最终内容。":
            "When both devices edited the same note, the local version was kept. "
            "Choose which version to keep, or write a merged version below.",
        "本机版本": "Local version",
        "导入版本": "Imported version",
        "合并结果（可编辑）": "Merged result (editable)",
        "所有冲突都已处理。": "All conflicts resolved.",
        "当前共 {} 条笔记、{} 条删除记录、{} 条未处理冲突。":
            "{} notes, {} deletion records, {} unresolved conflicts.",
        "已导出 {} 条记录到 {}。\n\n已记录同步基线：之后在另一台设备上的修改可以正确区分，不会误判成冲突。":
            "Exported {} records to {}.\n\nSync baseline recorded: later edits "
            "on another device can be told apart correctly.",
        "{}：{} 条笔记，来源 {}，导出时间 {}":
            "{}: {} notes, from {}, exported {}",
        "未知": "Unknown",
        "即将合并 {} 条笔记（来源 {}）。\n\n处理方式：{}\n\n三路合并会保留本机最近一次的修改；两端都改过的词不会静默覆盖，而是留下冲突副本供人工合并。继续吗？":
            "About to merge {} notes (from {}).\n\nStrategy: {}\n\n"
            "Three-way merge keeps recent local edits; notes changed on both "
            "sides are not overwritten silently — a conflict copy is kept for "
            "manual merge. Continue?",
        "\n\n{} 条笔记在两端都被修改过：已保留本机版本，另一端的完整内容存为冲突副本。点笔记面板右上角的「冲突」按钮即可人工合并。":
            "\n\n{} notes were edited on both devices: the local version was "
            "kept and the other version saved as a conflict copy. Use the "
            "conflicts button in the notes panel to merge them manually.",
        "时间未知": "Time unknown",
        "还有 {} 条冲突待处理。": "{} conflicts remaining.",

        # 导出格式 / 导入策略的说明文字是从常量里动态取出来再翻译的，
        # AST 扫描找不到，必须和上面的静态文案一起维护。
        "完整同步备份：带设备标识、修改时间、版本号和删除标记，适合电脑 ↔ 手机、电脑 ↔ 电脑双向同步。":
            "Full sync backup: device ID, edit time, revision and deletion "
            "markers. Use for two-way sync between devices.",
        "手机版现有生词本备份格式 + 可选笔记字段。未装配套补丁的旧版手机也能导入生词，只是暂不显示笔记。":
            "Mobile wordbook backup format with optional note fields. Older "
            "mobile builds can still import the words — notes just won't show up yet.",
        "通用表格，Excel 可直接打开；正文里带换行也能正确还原。":
            "Plain spreadsheet that Excel can open. Line breaks inside a note "
            "are preserved.",
        "手机版生词本 CSV + 笔记扩展列，列顺序与旧版兼容。":
            "Mobile wordbook CSV with extra note columns; existing column order "
            "is unchanged.",
        "把笔记打包成只读 MDX 词库，任何 MDX 词典软件都能查；它是快照，不参与同步与编辑。":
            "Packages notes as a read-only MDX dictionary any MDX reader can "
            "search. A snapshot — it does not sync or accept edits.",
        "用上次同步的内容做基线：只有一端改过就自动合并；两端都改过则保留本机，并把另一端完整存成冲突副本，可在笔记面板的「冲突」按钮里人工合并，不会静默丢内容。":
            "Uses the last agreed content as a baseline: one-sided edits merge "
            "automatically; when both sides edited, the local version is kept "
            "and the other saved as a conflict copy you can merge manually. "
            "Nothing is silently lost.",
        "本机已有的笔记一律不动（包括已删除的），只把文件里本机完全没有的词补进来。":
            "Existing local notes are left untouched (including deleted ones). "
            "Only words missing locally are added.",
        "同名笔记无条件用文件内容覆盖本机版本。":
            "Matching notes are overwritten with the file contents unconditionally.",
        "三路合并（推荐）": "Three-way merge (recommended)",
        "只补本地没有的": "Only add missing notes",
        "以导入文件为准": "Use imported file",
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
    """启动一个新的应用实例（用于切换语言后重启生效）。

    只负责「拉起新实例」，**退出旧实例由调用方负责**——调用方应走正常退出
    流程（MainWindow.quit_requested → 隐藏托盘图标 + QApplication.quit），
    这样 Qt 才能正常清理、释放数据库文件句柄。

    为什么不用 os.execv：Windows 上 os.execv 只是「新建进程 + 强杀当前
    进程」的模拟实现，不会执行任何 Python 层清理（aboutToQuit 不触发、
    数据库连接不关闭、托盘图标不隐藏）。结果是旧进程的文件句柄还没释放，
    新进程就去开数据库并设 WAL，触发
    sqlite3.OperationalError: disk I/O error，表现为「重启后软件起不来」。
    """
    import subprocess

    # 打包成 exe 后 sys.argv[0] 本身就是可执行文件路径，不能再当参数传进去；
    # 以 python 脚本方式运行时则需要把脚本路径补到解释器后面。
    if getattr(sys, "frozen", False):
        args = list(sys.argv[1:])
    else:
        args = [os.path.abspath(sys.argv[0])] + list(sys.argv[1:])

    # DETACHED_PROCESS：新实例独立于当前进程，当前进程退出不会带它一起走；
    # close_fds=True（Windows 默认）避免继承数据库等文件句柄。
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )

    subprocess.Popen([sys.executable] + args,
                     creationflags=creationflags, close_fds=True)
