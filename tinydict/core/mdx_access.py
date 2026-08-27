"""挂载式 MDX/MDD 访问器（文件常驻原位、按需读取）。

与"全量展开导入"相对，本模块：

- 挂载时只读取 MDX 头部 + 全部 key 列表（key 只占文件一小部分，
  不触碰正文 record 块），并把 key 列表 pickle 缓存到本地，
  二次启动直接加载缓存，实现"选完文件夹立刻能用"；
- 查词时在内存 key 有序表上二分定位，再从 MDX 原文件按需解压
  **单个** record 块，取出该词条的 HTML —— 每次查词毫秒级；
- MDD 资源同理：注册资源路径 -> 偏移的映射，请求时按需读单块；
- @@@LINK 跳转词条自动跟随（多级，防循环）。

解析能力基于 mdict_utils 内置的 readmdict（纯 Python，无 C 扩展
硬依赖），继承其块解压 / 加密处理逻辑。
"""

import hashlib
import os
import pickle
import re
import threading
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from mdict_utils.base.readmdict import MDX as _MDX, MDD as _MDD
    try:
        import xxhash
    except ImportError:  # pragma: no cover
        xxhash = None
except ImportError as e:  # pragma: no cover
    raise RuntimeError(
        "未安装 MDX 解析库，请先执行：pip install mdict-utils"
    ) from e

_LINK_RE = re.compile(rb"^\s*@@@LINK\s*=\s*(.+?)\s*$", re.S)

# 单个挂载实例的解压块 LRU 缓存上限（字节）
BLOCK_CACHE_LIMIT = 64 * 1024 * 1024

# @@@LINK 最大跟随深度（防循环引用）
MAX_LINK_DEPTH = 6


def normalize_resource_path(raw: str) -> str:
    """MDD 资源路径归一化：统一正斜杠、去前导分隔符、小写。"""
    p = (raw or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.strip("/").lower()


def quick_mdx_title(fname: str) -> str:
    """秒级读取 MDX 头部 XML 中的 Title 属性（注册词库时用，不解析正文）。

    失败时返回空字符串（调用方回退到文件名）。
    """
    try:
        with open(fname, "rb") as f:
            n = int.from_bytes(f.read(4), "big")
            header_bytes = f.read(n)
        if header_bytes[-2:] == b"\x00\x00":
            text = header_bytes[:-2].decode("utf-16", errors="ignore")
        else:
            text = header_bytes[:-1].decode("utf-8", errors="ignore")
        m = re.search(r'Title\s*=\s*"([^"]*)"', text, re.S)
        if m:
            title = m.group(1).strip()
            # 头部属性实体反转义
            for ent, ch in (("&lt;", "<"), ("&gt;", ">"),
                            ("&quot;", '"'), ("&amp;", "&")):
                title = title.replace(ent, ch)
            return title
    except OSError:
        pass
    return ""


class _KeyCache:
    """key 列表 pickle 缓存：以"绝对路径+大小+mtime"作为指纹。

    词库文件变更（重新发布 / 覆盖）后指纹变化，自动失效重建。
    """

    def __init__(self, dirpath):
        self._dir = Path(dirpath)

    def _cache_file(self, fname: str) -> Path:
        st = os.stat(fname)
        key = hashlib.md5(
            f"{os.path.abspath(fname)}|{st.st_size}|{int(st.st_mtime)}".encode("utf-8")
        ).hexdigest()
        return self._dir / f"keys_{key}.pkl"

    def load(self, fname: str) -> Optional[dict]:
        try:
            with open(self._cache_file(fname), "rb") as f:
                payload = pickle.load(f)
            if payload.get("src") == os.path.abspath(fname):
                return payload
        except Exception:  # noqa: BLE001 缓存损坏等同未命中
            pass
        return None

    def save(self, fname: str, key_list, record_block_offset: int):
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "src": os.path.abspath(fname),
                "keys": key_list,
                "record_offset": record_block_offset,
            }
            tmp = self._cache_file(fname).with_suffix(".tmp")
            with open(tmp, "wb") as f:
                pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, self._cache_file(fname))
        except OSError:
            pass  # 缓存写失败不影响功能，只是下次慢一点


class _LazyMixin:
    """挂载式基类逻辑：缓存化初始化 + 二分查找 + 按需单块读取。

    与 mdict_utils 的 MDict.__init__ 相比，这里把 _read_keys 的结果
    接入 pickle 缓存（命中时跳过全量 key 块解压）。
    """

    def _lazy_init(self, fname: str, cache_dir=None):
        # ---- 复刻 MDict.__init__ 的头部/加密初始化 ----
        self._fname = fname
        self._encoding = getattr(self, "_forced_encoding", "") or ""
        self._encrypted_key = None
        self.header = self._read_header()

        if self._version >= 3.0:
            uuid_ = self.header.get(b"UUID")
            if uuid_:
                if xxhash is None:  # pragma: no cover
                    raise RuntimeError("读取 MDict 3.0 需要 xxhash 支持")
                mid = (len(uuid_) + 1) // 2
                self._encrypted_key = (
                    xxhash.xxh64_digest(uuid_[:mid])
                    + xxhash.xxh64_digest(uuid_[mid:])
                )

        # ---- 挂载态运行时结构 ----
        self._substyle = False        # 不做 stylesheet 内联替换（保留原样）
        self._lock = threading.RLock()
        self._layout = None            # (file_offs, bases, comps, decomps, data_start, total)
        self._block_cache = OrderedDict()
        self._block_cache_bytes = 0

        # ---- key 列表：优先 pickle 缓存 ----
        cache = _KeyCache(cache_dir) if cache_dir else None
        cached = cache.load(fname) if cache is not None else None
        if cached is not None:
            self._key_list = cached["keys"]
            self._record_block_offset = cached["record_offset"]
        else:
            self._key_list = self._read_keys()
            if cache is not None:
                cache.save(fname, self._key_list, self._record_block_offset)
        self._num_entries = len(self._key_list)

        # ---- 查询辅助结构（挂载完成后只读） ----
        self._sorted_entries = sorted(self._key_list, key=lambda kv: kv[1])
        self._sorted_texts = [t for _, t in self._sorted_entries]
        self._ids = sorted(k for k, _ in self._key_list)

    # -------------------------------------------------------------- 查找
    @staticmethod
    def _variants(word: str) -> List[str]:
        """查词的大小写变体（MDX key 大小写不保证与输入一致）。"""
        seen: List[str] = []
        for v in (word, word.lower(), word.capitalize(), word.upper()):
            if v and v not in seen:
                seen.append(v)
        return seen

    def _lookup_entry(self, word: str) -> Optional[Tuple[int, bytes]]:
        for variant in self._variants(word):
            b = variant.encode("utf-8")
            i = bisect_left(self._sorted_texts, b)
            if i < len(self._sorted_texts) and self._sorted_texts[i] == b:
                key_id, text = self._sorted_entries[i]
                return key_id, text
        return None

    def _record_end(self, key_id: int) -> Optional[int]:
        """该词条 record 的结束偏移（下一词条起点）；最后一条返回 None。"""
        j = bisect_right(self._ids, key_id)
        if j < len(self._ids):
            return self._ids[j]
        return None

    # -------------------------------------------------------------- 按需读
    def _ensure_layout(self):
        """读取 record block 布局（每块压缩/解压尺寸与文件偏移），只读一次。"""
        with self._lock:
            if self._layout is not None:
                return self._layout
            f = open(self._fname, "rb")
            try:
                f.seek(self._record_block_offset)
                if self._version >= 3:
                    n = self._read_int32(f)
                    self._read_number(f)  # num_bytes 占位
                    infos = []
                    for _ in range(n):
                        d = self._read_int32(f)
                        c = self._read_int32(f)
                        infos.append((c, d))
                else:
                    n = self._read_number(f)
                    self._read_number(f)  # num_entries
                    self._read_number(f)  # record_block_info_size
                    self._read_number(f)  # record_block_size
                    infos = []
                    for _ in range(n):
                        c = self._read_number(f)
                        d = self._read_number(f)
                        infos.append((c, d))
                data_start = f.tell()
            finally:
                f.close()

            file_offs, bases, comps, decomps = [], [], [], []
            fo = bo = 0
            for c, d in infos:
                file_offs.append(fo)
                bases.append(bo)
                comps.append(c)
                decomps.append(d)
                fo += c
                bo += d
            self._layout = (file_offs, bases, comps, decomps, data_start, bo)
            return self._layout

    def _get_block(self, i: int) -> Optional[bytes]:
        """解压第 i 个 record 块（带 LRU 缓存）。"""
        with self._lock:
            blk = self._block_cache.get(i)
            if blk is not None:
                self._block_cache.move_to_end(i)
                return blk
            file_offs, _, comps, decomps, data_start, _ = self._layout
            with open(self._fname, "rb") as f:
                f.seek(data_start + file_offs[i])
                raw = f.read(comps[i])
            blk = self._decode_block(raw, decomps[i])
            self._block_cache[i] = blk
            self._block_cache_bytes += len(blk)
            while (self._block_cache_bytes > BLOCK_CACHE_LIMIT
                   and len(self._block_cache) > 1):
                _, old = self._block_cache.popitem(last=False)
                self._block_cache_bytes -= len(old)
            return blk

    def _read_record(self, key_id: int) -> Optional[bytes]:
        """按需读取单条 record（定位所在块 -> 解压 -> 切片）。"""
        self._ensure_layout()
        _, bases, _, decomps, _, _ = self._layout
        i = bisect_right(bases, key_id) - 1
        if i < 0:
            return None
        end = self._record_end(key_id)
        if end is None:
            end = bases[i] + decomps[i]
        end = min(end, bases[i] + decomps[i])
        if key_id - bases[i] > end - bases[i]:
            return None
        block = self._get_block(i)
        if block is None:
            return None
        return block[key_id - bases[i]: end - bases[i]]

    # -------------------------------------------------------------- 建议
    def _prefix_scan(self, prefix: str, limit: int) -> List[str]:
        pfx = (prefix or "").strip()
        if not pfx:
            return []
        out: List[str] = []
        for variant in (pfx, pfx.lower()):
            b = variant.encode("utf-8")
            i = bisect_left(self._sorted_texts, b)
            n = len(self._sorted_texts)
            while i < n and len(out) < limit:
                t = self._sorted_texts[i]
                if not t.startswith(b):
                    break
                out.append(t.decode("utf-8", errors="ignore"))
                i += 1
        return out

    # -------------------------------------------------------------- 状态
    @property
    def path(self) -> str:
        return self._fname

    def __len__(self):
        return self._num_entries


class LazyMDX(_LazyMixin, _MDX):
    """挂载式 MDX：lookup 返回 (原始词条文本, HTML bytes)。"""

    def __init__(self, fname: str, cache_dir=None):
        self._forced_encoding = ""
        self._lazy_init(fname, cache_dir)

    def lookup(self, word: str, _depth: int = 0) -> Optional[Tuple[str, bytes]]:
        word = (word or "").strip()
        if not word:
            return None
        hit = self._lookup_entry(word)
        if hit is None:
            return None
        key_id, key_text = hit
        data = self._read_record(key_id)
        if data is None:
            return None
        data = self._treat_record_data(data)

        # @@@LINK=xxx 跳转词条跟随
        if _depth < MAX_LINK_DEPTH:
            m = _LINK_RE.match(data)
            if m:
                raw = m.group(1).decode("utf-8", errors="ignore")
                targets = [t.strip() for t in re.split(r"[\r\n|]+", raw) if t.strip()]
                for t in targets:
                    r = self.lookup(t, _depth + 1)
                    if r is not None:
                        return r
        return key_text.decode("utf-8", errors="ignore"), data

    def suggest(self, prefix: str, limit: int = 20) -> List[str]:
        return self._prefix_scan(prefix, limit)

    def get_resource(self, path: str) -> Optional[bytes]:
        """从 MDX 自身读取内嵌资源（图片/音频等）。

        与 lookup 不同：不 follow @@@LINK，且直接返回原始 bytes
        （不做文本 decode，避免破坏二进制图片）。
        """
        p = normalize_resource_path(path)
        hit = self._lookup_entry(p)
        if hit is None:
            # 尝试去掉目录前缀后的 basename
            base = p.rsplit("/", 1)[-1]
            if base != p:
                hit = self._lookup_entry(base)
        if hit is None:
            return None
        key_id, _ = hit
        return self._read_record(key_id)


class LazyMDD(_LazyMixin, _MDD):
    """挂载式 MDD：资源路径 -> 偏移映射，get_resource 按需读取。"""

    def __init__(self, fname: str, cache_dir=None):
        self._forced_encoding = "UTF-16"
        self._lazy_init(fname, cache_dir)
        self._res_map = {}
        for key_id, text in self._key_list:
            p = normalize_resource_path(text.decode("utf-8", errors="ignore"))
            if p and p not in self._res_map:
                self._res_map[p] = key_id

    def get_resource(self, path: str) -> Optional[bytes]:
        p = normalize_resource_path(path)
        key_id = self._res_map.get(p)
        if key_id is None:
            return None
        return self._read_record(key_id)

    @property
    def resource_count(self) -> int:
        return len(self._res_map)


def find_mdd_files(mdx_path: Path) -> list:
    """查找与 MDX 配套的 MDD 资源文件（按顺序：同名优先，其次同目录全部）。

    匹配规则（按常见词库发布习惯，MDX 生态通常关联同目录 MDD）：
    - 同名 .mdd           : oxford.mdx -> oxford.mdd
    - 编号续接 .mdd       : oxford.mdx -> oxford.1.mdd, oxford.2.mdd ...
    - 兜底：同目录其它 .mdd（覆盖「不同名但同目录」的资源包）
    """
    base = mdx_path.with_suffix(".mdd")
    found = []
    seen = set()

    def _add(p: Path):
        p = p.resolve()
        if p.is_file() and p not in seen:
            found.append(p)
            seen.add(p)

    _add(base)
    for i in range(1, 21):
        _add(mdx_path.with_name(f"{mdx_path.stem}.{i}.mdd"))
    # 兜底：同目录全部 .mdd（不含子目录），覆盖命名不一致的资源包
    for p in sorted(mdx_path.parent.glob("*.mdd")):
        _add(p)
    return found


def scan_mdx_files(folder: Path) -> List[Path]:
    """递归扫描文件夹下全部 .mdx（按名称排序，跳过隐藏目录）。"""
    out = []
    for p in folder.rglob("*.mdx"):
        if p.is_file() and not any(
            part.startswith(".") for part in p.parts[len(folder.parts):]
        ):
            out.append(p)
    return sorted(out, key=lambda p: str(p).lower())
