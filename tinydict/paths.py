"""应用数据目录与文件路径约定。

所有用户数据（词库数据库、索引、配置）集中存放在 ~/.tinydict/ 下，
与源码目录解耦，便于升级与备份。
"""

import shutil
from pathlib import Path

APP_NAME = "TinyDict"

# 旧版数据目录名（项目由 SuperDict 更名为 TinyDict 时遗留），首次启动迁移到新目录
LEGACY_DATA_DIR = Path.home() / ".superdict"


def data_dir() -> Path:
    """用户数据根目录（不存在则创建）。

    首次启动若发现旧目录 ~/.superdict 且新目录 ~/.tinydict 尚不存在，
    自动整体迁移过去，避免已导入的词库 / 配置丢失。
    """
    d = Path.home() / ".tinydict"
    if LEGACY_DATA_DIR.exists() and not d.exists():
        try:
            shutil.move(str(LEGACY_DATA_DIR), str(d))
        except OSError:
            # 迁移失败不致命：退回“新建空目录”，后续由导入流程重建
            pass
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    """SQLite 主数据库：词库元数据 / 词条内容 / MDD 资源 / 生词本。"""
    return data_dir() / "dictionary.db"


def cache_dir() -> Path:
    """MDX/MDD key 索引 pickle 缓存目录（挂载加速，二次启动秒开）。"""
    return data_dir() / "cache"


def config_path() -> Path:
    """JSON 配置文件路径。"""
    return data_dir() / "config.json"
