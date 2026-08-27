# TinyDict — Windows 桌面离线 MDX 词典

一款基于 MDX / MDD 格式的 **单机离线** 词典软件：

- 仅本地解析 MDX / MDD 词库，**无任何联网查词功能**，运行时不发起网络请求；
- **挂载式词库**：选择 `.mdx` 文件或词库文件夹后**即加即用**，
  无需导入等待 —— 词条数据始终保留在原始 `.mdx/.mdd` 文件中，
  查询时按需从文件读取，磁盘占用近乎为零；
- QWebEngineView 渲染词条 HTML（音标、图片、样式，支持词条内跳转、`@@@LINK` 跟随）；
- SQLite 生词本、全局快捷键唤起、屏幕划词取词、系统托盘常驻。

> 技术栈：Python + PySide6 + mdict-utils（MDX 解析，纯 Python 无 C 扩展）
> + keyboard / pywin32（全局快捷键与系统能力）。

---

## 1. 环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 10 / 11 |
| Python | **3.10 – 3.12**（3.13 一般也可运行，但以 3.10–3.12 为准） |
| 磁盘 | 程序本身很小；用户数据存放于 `~/.tinydict/`，仅含 key 索引缓存与生词本，占用极小 |

## 2. 安装依赖

本机开发环境启用了本地代理，pip 安装时请带上代理参数：

```bash
pip install --proxy http://127.0.0.1:7897 -r requirements.txt
```

或逐个安装：

```bash
pip install --proxy http://127.0.0.1:7897 PySide6 mdict-utils pywin32 keyboard
```

> 不需要代理的机器，去掉 `--proxy http://127.0.0.1:7897` 即可。
> `mdict-utils` 仅依赖 `tqdm`、`xxhash`，不强制 `readmdict`/`python-lzo`，
> 可避免 Windows 上编译 C 扩展的麻烦。

也可用 **uv** 运行（更快、依赖解析更干净，且能避开 pip 在 Windows 上
安装 PySide6 时偶发的"回收站安全删除"失败）：

```bash
uv venv
uv pip install -r requirements.txt   # 代理需用环境变量：set HTTP_PROXY=http://127.0.0.1:7897
uv run main.py
```

## 3. 源码运行

在项目根目录执行：

```bash
python main.py
```

首次启动会在用户目录创建数据文件夹 `C:\Users\<用户名>\.tinydict\`：

```
~/.tinydict/
├── dictionary.db   # SQLite：词库注册信息 / 生词本（不含词条正文）
├── cache/          # MDX/MDD key 索引 pickle 缓存（挂载加速）
└── config.json     # 快捷键等配置
```

## 4. 使用说明

### 4.1 添加 MDX 词库（即加即用，无需导入）

1. 点击主窗口右上角 **「词库」** 按钮，打开词库管理；
2. 点 **「添加文件…」** 选择一个或多个 `.mdx` 文件；或点 **「添加文件夹…」**
   选择词库目录，程序会递归扫描其中全部 `.mdx`；
   - 同目录下的同名 `.mdd`（以及 `xx.1.mdd`、`xx.2.mdd` …）会自动一并挂载
     （图片 / CSS / 字体等资源）；
   - **注册只读取 MDX 头部，秒级完成**；随后后台加载 key 索引，
     列表「状态」列显示「加载中 → 就绪」，加载完成即可查询；
   - 第二次启动会直接加载本地 key 缓存，几乎无等待；
3. 列表顺序即**查询优先级**：排在前面的词库优先展示结果，用「上移 / 下移」调整；
4. 取消勾选「启用」可临时禁用某词库；**「移除词库」仅取消注册**，
   不影响原始 `.mdx/.mdd` 文件，可随时重新添加。

> 与旧版"导入式"不同：词条正文与资源**不再展开进本地数据库**，
> 查询时直接从原文件按需读取单条 record（MDX 自带索引，二分定位 + 单块解压，
> 毫秒级）。因此首次添加几乎瞬时，磁盘占用近乎为零。

### 4.2 查词

- 顶部搜索框输入单词，**回车**精确查词；输入过程中左侧列表实时给出前缀联想，
  单击联想词直接查询；
- 多部词库同时命中时，词条区顶部出现**词典切换标签**；
- 词条内的 `entry://` 交叉引用链接可直接点击跳转；
- `@@@LINK=xxx` 跳转词条自动跟随（多级，防循环）；
- `←` `→` 按钮在历史记录中前进后退；**「置顶」**让窗口常驻最前。

### 4.3 生词本

- 查词后点 **★** 将当前词条加入生词本（再点一次移除）；
- 点 **「生词本」** 打开生词本窗口：双击词条回查、删除选中、清空。

### 4.4 快捷键 / 划词 / 托盘（默认配置，可在「设置」中修改）

| 功能 | 默认快捷键 |
|---|---|
| 显示 / 隐藏主窗口（全局） | `Ctrl + Alt + D` |
| 屏幕划词取词（全局） | `Ctrl + Alt + Q` |

- **划词取词**：在其他应用（Word、浏览器、PDF 阅读器等）中选中文字后按取词快捷键，
  程序会模拟一次 `Ctrl+C` 读取选中文本并弹出查询（随后自动恢复剪贴板内容）。
  需要目标程序支持「Ctrl+C 复制选中内容」；
- 点击窗口关闭按钮默认**最小化到系统托盘**（托盘右键菜单可退出，或在设置中改为直接退出）；
- 托盘图标单击/双击同样可以显示/隐藏主窗口。

## 5. 手动打包指引（PyInstaller）

本仓库**不包含**任何打包脚本与安装器工程，以下步骤请自行执行。

### 5.1 安装 PyInstaller

```bash
pip install --proxy http://127.0.0.1:7897 pyinstaller
```

### 5.2 打包命令（推荐 --onedir 文件夹方式）

在项目根目录执行：

```bash
pyinstaller --noconfirm --clean --onedir --windowed --name TinyDict main.py
```

- `--onedir`：输出为 `dist\TinyDict\` 文件夹（启动快、误报率相对低），
  整个文件夹拷到目标机器即可运行；
- `--windowed`（等价 `-w`）：不显示控制台窗口；
- 如需单文件 exe，把 `--onedir` 换成 `--onefile`（启动较慢且更容易被杀软误报，不推荐）。

### 5.3 体积与注意事项

- **QWebEngineView 附带 Chromium 内核**，打包产物中会包含 `Qt6WebEngineCore.dll`、
  `resources\`、`translations\qtwebengine_*.qm` 等约 **150–300 MB** 的文件，
  最终目录体积较大属正常现象，请勿手工删除这些文件；
- 若运行打包版时报缺少 `QtWebEngineProcess.exe` 等组件，可追加参数让 PyInstaller
  完整收集 PySide6 二进制：
  `pyinstaller ... --collect-binaries PySide6 --collect-submodules PySide6`
- **杀毒软件误报**：PyInstaller 打包的 exe（尤其 `--onefile` 单文件模式）被杀软误报
  是常见现象。如遇拦截，请把 `dist\TinyDict\` 目录加入杀软白名单；本软件不联网、
  无恶意行为，可放心使用；
- 全局快捷键 / 划词功能使用 `keyboard` 库的低级键盘钩子，个别安全软件可能提示
  「键盘记录器」类风险，属该库的固有工作方式，请自行判断是否放行。

### 5.4 制作桌面安装程序（可选）

PyInstaller 只输出可执行目录。如需做成带开始菜单 / 桌面图标的安装程序
（`.msi` / `.exe` 安装包），可自行使用 **Inno Setup** 等工具把 `dist\TinyDict\`
封装，本仓库不提供相关工程。

## 6. 已知限制

- 不支持加密（需要注册码/序列号）的 MDX 词库，挂载时会提示失败；
- 词条内的音频播放（`sound://` 资源）暂未支持，音标/图片/样式渲染正常；
- 划词取词依赖「Ctrl+C 复制」机制，个别禁止复制的应用中无效；
- 部分词库 CSS 中引用的外部字体若未包含在 MDD 中，可能显示为系统默认字体；
- 超大词库（数百万词条）首次挂载需读取全部 key 建索引（几秒至几十秒），
  之后由本地缓存加速，二次启动秒级。

## 7. 项目结构

```
TinyDict/
├── main.py                        # 启动入口（注册 mdx:// scheme 并创建应用）
├── requirements.txt
├── README.md
└── tinydict/
    ├── paths.py                   # 数据目录约定（~/.tinydict/）
    ├── config.py                  # JSON 配置
    ├── app.py                     # 组装层：托盘 / 热键 / 划词接线
    ├── core/
    │   ├── database.py            # SQLite：词库注册信息 / 生词本
    │   ├── mdx_access.py          # 挂载式 MDX/MDD 访问器（key 缓存 + 按需读单块）
    │   ├── query.py               # 词典服务：注册 / 后台挂载 / 查词 / 建议 / 资源
    │   └── wordbook.py            # 生词本
    ├── ui/
    │   ├── main_window.py         # 主窗口（搜索 / 渲染 / 历史 / 星标 / 挂载状态）
    │   ├── scheme_handler.py      # mdx:// 资源请求处理器（从 MDD 原文件按需读）
    │   ├── dict_manager_dialog.py # 词库管理对话框（添加文件 / 文件夹）
    │   ├── wordbook_dialog.py     # 生词本窗口
    │   ├── settings_dialog.py     # 设置对话框
    │   └── icons.py               # 程序图标（代码绘制）
    └── system/
        ├── hotkeys.py             # 全局快捷键（keyboard 库）
        └── capture.py             # 屏幕划词取词
```
