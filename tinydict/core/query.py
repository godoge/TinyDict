"""词典查询服务（挂载式 / 按需读取）。

- 注册词库 = 只读 MDX 头部 Title（秒级），不做任何数据展开；
- 挂载 = 后台线程读取 key 索引（带 pickle 缓存，二次启动秒级），
  完成前该词库不参与查询，UI 通过信号感知进度；
- 查词 = 各启用词库在内存 key 有序表上二分 + 从原文件按需读单条
  record，按优先级排序返回；
- 建议 = 内存 key 表前缀扫描（不再需要 Whoosh 索引）；
- 资源 = 各词库关联 MDD 按需读取。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, QThread, Signal

from .database import Database, DictInfo
from .mdx_access import (
    LazyMDX, LazyMDD, find_mdd_files, quick_mdx_title, scan_mdx_files,
)


@dataclass
class EntryResult:
    """一次查词命中的单个词条。"""
    word: str            # 词库中的原始词条（保留大小写）
    dict_id: int
    dict_name: str
    encoding: str
    definition: bytes    # 原始 HTML 字节（已统一 UTF-8）

    def html(self) -> str:
        return self.definition.decode(self.encoding or "utf-8", errors="replace")


@dataclass
class DictMount:
    """一部已挂载的词库（MDX + 关联 MDD）。"""
    info: DictInfo
    mdx: LazyMDX
    mdds: List[LazyMDD]

    @property
    def entry_count(self) -> int:
        return len(self.mdx)

    @property
    def resource_count(self) -> int:
        return sum(len(m) for m in self.mdds)


class MountTask(QThread):
    """后台挂载线程：逐部加载启用词库的 key 索引。"""

    mounted = Signal(object)          # DictMount
    mount_failed = Signal(int, str)   # dict_id, 错误信息
    progress = Signal(int, int, str)  # done, total, dict_name

    def __init__(self, dicts: List[DictInfo], cache_dir, parent=None):
        super().__init__(parent)
        self._dicts = [d for d in dicts if d.enabled]
        self._cache_dir = str(cache_dir)

    def run(self):
        total = len(self._dicts)
        for i, d in enumerate(self._dicts, start=1):
            try:
                mdx_path = Path(d.filename)
                if not mdx_path.is_file():
                    self.mount_failed.emit(
                        d.id, f"词库文件不存在：{d.filename}")
                else:
                    mdx = LazyMDX(str(mdx_path), self._cache_dir)
                    mdds = []
                    for mdd_path in find_mdd_files(mdx_path):
                        try:
                            mdds.append(LazyMDD(str(mdd_path), self._cache_dir))
                        except Exception as e:  # noqa: BLE001 单个 MDD 失败不致命
                            print(f"警告：无法挂载资源 {mdd_path.name}：{e}")
                    self.mounted.emit(DictMount(info=d, mdx=mdx, mdds=mdds))
            except Exception as e:  # noqa: BLE001 后台线程兜底
                self.mount_failed.emit(d.id, str(e) or e.__class__.__name__)
            self.progress.emit(i, total, d.name)


class DictionaryService(QObject):
    """词典服务门面：注册 / 挂载 / 查词 / 建议 / 资源。"""

    mount_progress = Signal(int, int, str)   # done, total, name
    dict_mounted = Signal(int)               # 一部词库挂载完成
    mount_finished = Signal()                # 本轮全部处理完成

    def __init__(self, db: Database, cache_dir, parent=None):
        super().__init__(parent)
        self._db = db
        self._cache_dir = str(cache_dir)
        self._mounts = {}          # dict_id -> DictMount（挂载完成才放入）
        self._loader = None        # 当前 MountTask
        self._pending_reload = False
        self._folder_res_cache = {}  # (dict_id, path) -> bytes 仅缓存命中

    # ------------------------------------------------------------------ 词库
    def all_dicts(self) -> List[DictInfo]:
        return self._db.list_dicts()

    def enabled_dicts(self) -> List[DictInfo]:
        """启用中的词库，按优先级从高到低。"""
        return [d for d in self._db.list_dicts() if d.enabled]

    def enabled_dict_ids(self) -> List[int]:
        return [d.id for d in self.enabled_dicts()]

    def is_mounted(self, dict_id: int) -> bool:
        return dict_id in self._mounts

    def mount_status(self, dict_id: int) -> str:
        """词库状态：ready / loading / missing / disabled。"""
        for d in self.all_dicts():
            if d.id == dict_id:
                if not d.enabled:
                    return "disabled"
                return "ready" if dict_id in self._mounts else "loading"
        return "missing"

    def mount_count(self) -> int:
        return len(self._mounts)

    # ------------------------------------------------------------------ 注册
    def register_file(self, mdx_path: str) -> Optional[DictInfo]:
        """注册单个 MDX（秒级：只读头部 Title）。已注册则返回 None。"""
        path = Path(mdx_path)
        if not path.is_file():
            raise RuntimeError(f"文件不存在：{path}")
        if path.suffix.lower() != ".mdx":
            raise RuntimeError(f"不是 .mdx 文件：{path.name}")
        if self._db.find_dict_by_filename(str(path)):
            return None  # 已注册
        title = quick_mdx_title(str(path))
        name = self._db.unique_dict_name(title or path.stem)
        dict_id = self._db.add_dict(name, str(path), "utf-8")
        for d in self.all_dicts():
            if d.id == dict_id:
                return d
        return None

    def register_folder(self, folder: str) -> List[DictInfo]:
        """扫描文件夹并注册其中全部 .mdx（跳过已注册的）。"""
        registered = []
        for p in scan_mdx_files(Path(folder)):
            info = self.register_file(str(p))
            if info is not None:
                registered.append(info)
        return registered

    def unregister(self, dict_id: int):
        """取消注册（卸载内存挂载 + 删除注册记录，不影响原文件）。"""
        self._mounts.pop(dict_id, None)
        self._db.remove_dict(dict_id)

    # ------------------------------------------------------------------ 挂载
    def mount_all_async(self):
        """后台挂载全部启用词库（app 启动 / 词库变更后调用）。"""
        if self._loader is not None and self._loader.isRunning():
            self._pending_reload = True
            return
        task = MountTask(self.all_dicts(), self._cache_dir)
        task.mounted.connect(self._on_mounted)
        task.mount_failed.connect(lambda _id, _msg: None)
        task.progress.connect(self.mount_progress)
        task.finished.connect(self._on_task_finished)
        self._loader = task
        task.start()

    def mount_all_blocking(self):
        """同步挂载全部启用词库（测试 / 无 GUI 场景）。"""
        for d in list(self.enabled_dicts()):
            try:
                mdx = LazyMDX(d.filename, self._cache_dir)
                mdds = [LazyMDD(str(p), self._cache_dir)
                        for p in find_mdd_files(Path(d.filename))]
                mount = DictMount(info=d, mdx=mdx, mdds=mdds)
                self._mounts[d.id] = mount
                self._db.update_dict_counts(
                    d.id, mount.entry_count, mount.resource_count)
            except Exception as e:  # noqa: BLE001
                print(f"挂载失败 [{d.name}]：{e}")
        self.mount_finished.emit()

    def _on_mounted(self, mount: DictMount):
        dict_id = mount.info.id
        # 注册记录可能在挂载期间被删除
        if not any(d.id == dict_id for d in self.all_dicts()):
            return
        self._mounts[dict_id] = mount
        self._db.update_dict_counts(
            dict_id, mount.entry_count, mount.resource_count)
        self.dict_mounted.emit(dict_id)

    def _on_task_finished(self):
        self.mount_finished.emit()
        if self._pending_reload:
            self._pending_reload = False
            self.mount_all_async()

    # ------------------------------------------------------------------ 查词
    def lookup(self, word: str) -> List[EntryResult]:
        """按词库优先级返回全部命中词条（只查已挂载的启用词库）。"""
        word = (word or "").strip()
        if not word:
            return []
        results: List[EntryResult] = []
        for d in self.enabled_dicts():
            mount = self._mounts.get(d.id)
            if mount is None:
                continue  # 尚未挂载完成：暂不参与（挂载完成信号会触发重查）
            hit = mount.mdx.lookup(word)
            if hit is not None:
                w, data = hit
                results.append(EntryResult(
                    word=w, dict_id=d.id, dict_name=d.name,
                    encoding="utf-8", definition=data,
                ))
        return results

    def suggest(self, query: str, limit: int = 25) -> List[str]:
        """前缀搜索建议（输入框实时联想，按词库优先级合并去重）。"""
        q = (query or "").strip()
        if not q:
            return []
        out: List[str] = []
        seen = set()
        for d in self.enabled_dicts():
            mount = self._mounts.get(d.id)
            if mount is None:
                continue
            for w in mount.mdx.suggest(q, limit):
                key = w.lower()
                if key not in seen:
                    seen.add(key)
                    out.append(w)
                    if len(out) >= limit:
                        return out
        return out

    # ------------------------------------------------------------------ 资源
    def find_resource(
        self, preferred_dict_id: Optional[int], path: str
    ) -> Optional[bytes]:
        """词条 HTML 引用的资源（CSS/图片等）：优先所属词库，再按优先级。

        查找顺序（命中即返回）：
          1) MDX 自身内嵌资源（部分词典把图标直接存进 MDX）；
          2) 配套 .mdd 资源包；
          3) 词库文件夹下的同名/同 base 名明文文件
             （部分词典把 p.css / fy.js / config.ini 等资源以
              普通文件形式放在 .mdx 同目录，不打包进 .mdd）。
        """
        order = self.enabled_dict_ids()
        if preferred_dict_id is not None and preferred_dict_id in order:
            order = [preferred_dict_id] + [
                i for i in order if i != preferred_dict_id
            ]
        for dict_id in order:
            mount = self._mounts.get(dict_id)
            if mount is None:
                continue
            # 1) 先查 MDX 自身（很多词典把图标内嵌在 MDX 内，而非单独 .mdd）
            data = mount.mdx.get_resource(path)
            if data is not None:
                return data
            # 2) 配套 .mdd 资源包
            for mdd in mount.mdds:
                data = mdd.get_resource(path)
                if data is not None:
                    return data
            # 3) 词库文件夹下的明文资源文件（css/js/ini/图片）
            data = self._find_folder_resource(dict_id, path)
            if data is not None:
                return data
        return None

    def _find_folder_resource(
        self, dict_id: int, path: str
    ) -> Optional[bytes]:
        """从词库 .mdx 同目录的明文文件中读取资源（带命中缓存）。

        命中缓存避免对同一文件（如 fy.js）重复磁盘读取；未命中不缓存，
        以便用户后续把资源放进文件夹后能立即生效。
        """
        cache_key = (dict_id, path)
        hit = self._folder_res_cache.get(cache_key)
        if hit is not None:
            return hit
        mount = self._mounts.get(dict_id)
        if mount is None:
            return None
        folder = Path(mount.info.filename).parent
        base = path.rsplit("/", 1)[-1]
        for cand in (folder / path, folder / base):
            if cand.is_file():
                try:
                    data = cand.read_bytes()
                except OSError:
                    continue
                self._folder_res_cache[cache_key] = data
                return data
        return None
