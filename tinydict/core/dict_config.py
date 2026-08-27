"""按词典（dict_id）持久化词典自带配置。

为什么需要它
------------
许多 MDX 词典（如 OALDPEX、牛津、剑桥）把自身配置写在浏览器的 localStorage
里（发音/图片在线离线开关、排版偏好等）。但 TinyDict 用自定义 scheme
`mdx://<id>/` 渲染词条页，Chromium 不会为这类 origin 提供可落盘的存储分区，
于是每次重启后词典读到的 localStorage 都是空的，等于「配置被重置」。

本模块在 Python 侧提供按 dict_id 隔离的持久化目录，配合
`tinydict/ui/resource_inliner.py` 注入的 JS 桥（重写 Storage.prototype），
让词典对 localStorage 的读写透明地落到本机 JSON 文件上——对任意词典通用，
无需写死任何词典的具体配置键。
"""

import json
import os
from pathlib import Path

from ..paths import data_dir


def _dict_config_path(dict_id: int) -> Path:
    d = Path(data_dir()) / "dict_config"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{int(dict_id)}.json"


def get_dict_config(dict_id: int) -> dict:
    """读取某词典已持久化的配置（字典）。不存在/损坏时返回空字典。"""
    p = _dict_config_path(dict_id)
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def replace_dict_config(dict_id: int, mapping: dict) -> None:
    """用 mapping 整体替换某词典的配置（原子写，避免半截文件）。

    采用「整份快照覆盖」而非逐项更新：JS 桥每次回传的是当前 localStorage 的完整
    快照，这样词典 removeItem 删除的键也能被正确移除（若用 update 则删不掉）。
    """
    if not isinstance(mapping, dict):
        return
    p = _dict_config_path(dict_id)
    tmp = p.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except OSError:
        # 写入失败（如磁盘满/权限）时丢弃临时文件，不影响运行
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
