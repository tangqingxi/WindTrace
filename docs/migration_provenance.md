# 独立化迁移记录（WindTrace W1）

本文件记录 WindTrace 从源项目独立成仓时，迁移了什么、剔除了什么、消除了哪些跨仓依赖。
逐文件来源与哈希见 [../IMPORT_PROVENANCE.json](../IMPORT_PROVENANCE.json)。

## 来源

| 项 | 值 |
|---|---|
| 源仓库 | <https://github.com/tangqingxi/Ducted-Fan-SHC09-matlab> |
| 源分支 | `refactor/phase3-source` |
| 源提交 | `d422cb34e495fbe786395d9586694fe4ef6f88df` |
| 源目录 | `apps/windtrace/` |
| 迁移日期 | 2026-11-07 |

源仓库未被修改：迁移只读取文件，源仓库的 HEAD、`main`、C8 分支、历史 MAT/WTR、
锁文件与旧 EXE 保持原样。

## 迁移内容（Viewer）

- `app.py`：命令行入口、`--smoke` 校验、离屏截图流程。
- `core/flight.py`：`.wtr` 读取与契约校验（唯一的核心依赖）。
- `ui/`：主窗口、三维视图、相机语言、运镜解析、主题、shell 组件、GLB 示意模型解析。
- `assets/`：logo、运镜示例脚本、`geometry_source.json`（溯源用，运行时不读取）。
- `ui/assets/SHC09.glb`：SHC09 示意模型。
- `tests/`：容器契约、界面、相机、主题与参数测试。
- `docs/`：WTR v1 与运镜 v1 契约。

## 剔除内容（数据生产端）

| 文件 | 原因 |
|---|---|
| `core/exporter.py` | MATLAB 日志 → `.wtr` 转换器，属于数据生产端，留在源项目 |
| `core/visual_geometry.py` | 仅被 exporter 调用；等价逻辑并入测试专用生成器 |
| `analysis/export_windtrace_flight.m` | MATLAB 导出入口，留在源项目 |
| `tools/export_windtrace.py`、`tools/audit_windtrace.py` | 导出与审计脚本，留在源项目 |

测试不再依赖 exporter：`tests/wtr_builder.py` 直接按契约写容器（含把随包 GLB 转成
FRD 网格的逻辑），只服务测试，不是用户需要安装的组件。

## 已消除的跨仓依赖

| 原位置 | 依赖 | 处理 |
|---|---|---|
| `core/exporter.py:18` | `ROOT = Path(__file__).resolve().parents[3]`（指向 MATLAB 仓库根） | 随 exporter 移除 |
| `core/exporter.py:217` | `ROOT/'analysis/export_windtrace_flight.m'` 源码哈希 | 随 exporter 移除 |
| `core/exporter.py:195` | `assets/geometry_source.json`（原为导出输入） | 转为测试生成器读取的溯源资产 |
| `README.md` | `../../docs/...`、`apps/windtrace/tests`、旧 `.venv` 绝对路径 | README 重写为独立使用说明 |
| `docs/interfaces/*.md` | 仓库外相对链接 | 迁入 `docs/` 并改为仓内链接 |
| `assets/cameras/README.md`、`ui/camera.py` | `docs/interfaces/...` 路径 | 改为 `docs/windtrace_camera_v1.md` |
| `ui/glb_model.py` | 无（只用 `ui/assets/` 相对路径） | 保持 |

迁移后，从 GitHub 克隆本仓库只需 `requirements.txt` 列出的 PyPI 包即可运行；
不需要 MATLAB，不需要源仓库，也不依赖任何本机历史绝对路径。

## 保持不变的契约

- `windtrace.flight.v1` 与 `.wtr` 成员、时间/坐标/四元数/参数语义完全保留；
- `.wtr` 的写入方仍是数据生产端，WindTrace 只读，不写回、不改格式；
- 本机最近记录与相机设置仍使用同一 QSettings 键，升级后原有个人设置继续有效。
