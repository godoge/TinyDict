"""JSON 配置读写：全局快捷键、划词开关、关闭行为等。"""

import copy
import json
from pathlib import Path


class Config:
    # 默认配置：
    # - hotkey_show_hide : 唤起 / 隐藏主窗口（keyboard 库格式）
    # - hotkey_capture   : 屏幕划词取词
    # - capture_enabled  : 是否启用划词
    # - minimize_to_tray : 点关闭按钮时最小化到托盘（否则直接退出）
    # - fill_input_on_select : 点击左侧候选词条时，是否把该词条也填入搜索框
    #                         （关闭则只显示释义、不改变搜索框内容；默认关闭）
    # - offline_mode         : 强制离线。True 时拦截所有远程请求（仅可用词库自带
    #                         离线资源）；False 时允许词库按需在线获取资源。
    #                         默认关闭，因为部分词库（如 OALDPEX）可能需要在线发音/图片。
    # - wordbook_group_id    : 顶栏选中的生词本分组 id（★ 收录的归属分组），
    #                         重启后保持上次选择；分组被删除时自动回退到默认分组 1。
    DEFAULTS = {
        "hotkey_show_hide": "ctrl+alt+d",
        "hotkey_capture": "ctrl+alt+q",
        "capture_enabled": True,
        "minimize_to_tray": True,
        "fill_input_on_select": False,
        "offline_mode": False,
        "wordbook_group_id": 1,
    }

    def __init__(self, path: Path):
        self._path = Path(path)
        self._data = copy.deepcopy(self.DEFAULTS)
        self.reload()

    def reload(self):
        """从磁盘加载配置并与默认值合并（未知键保留，缺失键补默认值）。"""
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self._data.update(loaded)
            except (OSError, json.JSONDecodeError):
                # 配置损坏时使用默认值，不中断启动
                pass

    def save(self):
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def __getitem__(self, key: str):
        return self._data.get(key, self.DEFAULTS.get(key))

    def __setitem__(self, key: str, value):
        self._data[key] = value

    def as_dict(self) -> dict:
        return dict(self._data)
