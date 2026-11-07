# 第三方声明与来源

WindTrace 是独立的飞行仿真结果 Viewer。本仓库只包含 Viewer 自身需要的源码、示意资产与测试，
不包含 MATLAB 仿真、控制器、动力学或日志转换器。

## 来源

源项目：`tangqingxi/Ducted-Fan-SHC09-matlab`，分支 `refactor/phase3-source`，
提交 `d422cb34e495fbe786395d9586694fe4ef6f88df`，目录 `apps/windtrace/`。
逐文件来源与哈希见 [IMPORT_PROVENANCE.json](IMPORT_PROVENANCE.json) 与
[docs/migration_provenance.md](docs/migration_provenance.md)。

复用的组件：logo、SHC09 示意 GLB、几何来源 JSON、GLB 解析器、shell/theme 设计组件，
以及单飞行 `.wtr` 读取器。数据生产端（MATLAB 日志 → `.wtr` 转换器）留在源项目，
未迁入本仓库。

## SHC09 示意模型

`ui/assets/SHC09.glb` 来自 mengchaoheng/Hawkeye 的 `df` 分支（BSD-3-Clause）：

- <https://github.com/mengchaoheng/Hawkeye>
- <https://github.com/mengchaoheng/Hawkeye/blob/df/models/SHC09.glb>

模型是示意资产：舵面轴、比例、转子转速都不代表实机标定或气动效能。

## 几何来源

`assets/geometry_source.json` 由源项目的 `viz/geometry/export_geometry.m` 从
`ca_shc09_parameters` 生成，数值是示意显示选择（见该 JSON 的 `assumed` 字段），
不是机体图纸。WindTrace 运行时只读取 `.wtr` 内自带的几何，不读取该文件。

## pyFlightAnalysis

仅用于早期调研阅读，未被导入或拷贝进本仓库。MIT License, Copyright (c) 2018 LP。
MIT 全文见仓库 [LICENSE](LICENSE)。

<https://github.com/Marxlp/pyFlightAnalysis>

## viz-replay（私有源仓库）

`assets/geometry_source.json` 的上游 `core/geometry/shc09_geometry.json` 来自
**viz-replay @ viz-v0.2.1**（提交 `4288b1d570493dfd5e1d747ac8703f1af8e45c23`）。
上游未附独立 LICENSE 文件；本仓库的 MIT `LICENSE` 适用于合成作品，来源见上。

## Qt / PySide6、pyqtgraph、PyVista / VTK、NumPy、SciPy

运行依赖，按各自许可证从 PyPI 安装，未把二进制文件提交到本仓库。
打包后的 EXE 内含这些依赖的二进制，分发时遵守各自许可证。
