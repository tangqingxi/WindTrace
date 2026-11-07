# 风迹 WindTrace

WindTrace 是一个独立的**飞行仿真结果 Viewer**：打开一次飞行导出的 `.wtr` 记录，看三维姿态与轨迹、
时间轴回放、飞行数据曲线和记录里的参数。它不做仿真计算——不跑动力学、不跑控制器、不跑控制分配，
也不转换 MATLAB 原始日志。它只理解标准化的 `.wtr` 数据。

- 仓库：<https://github.com/tangqingxi/WindTrace>
- 平台：Windows 10/11 x64
- 许可：MIT，见 [LICENSE](LICENSE)；第三方与来源声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

## 功能

| 能力 | 说明 |
|---|---|
| 打开单飞行 | 一个窗口只打开一个 `.wtr`；要比较两种方法就再开一个窗口 |
| 三维回放 | 飞行器位姿、六舵面、参考轨迹、地面网格与机体坐标系 |
| 时间轴 | 播放／暂停、变速、拖动定位；按绝对经过时间推进，不随帧率漂移 |
| 数据曲线 | 按 topic.field 画曲线，保留日志原生时间轴，不插值、不做排名 |
| 参数查看 | 只读表：完整路径、生效值、单位、来源、父值与覆盖标记 |
| 相机 | 跟随／自由／追尾／环绕／总览／机体特写，三套内置运镜和可导入的运镜脚本 |
| 世界坐标系 | NED（默认）与 ENU 显示切换，只改画面不改数据 |
| 真实／估计状态 | 按日志中的真值或机载估计移动飞机，默认真值 |
| 截图 | 导出当前视图为 PNG |
| 最近记录 | 欢迎页列出最近 8 条日志，单击选中、双击打开 |

WindTrace 不知道产生数据的工程内部用什么控制器、模型或目录结构；只要文件符合
[WTR v1 契约](docs/windtrace_flight_v1.md) 就能打开。

## 使用 Windows EXE

解压/拷贝整个 `WindTrace` 目录后双击 `WindTrace.exe` 即可，不需要安装 Python 或 MATLAB：

```text
dist\WindTrace\WindTrace.exe            # 双击启动，停在欢迎页
dist\WindTrace\WindTrace.exe flight.wtr # 直接打开指定日志
```

- `WindTrace.exe` 与同级 `_internal` 目录必须放在一起，不要拆开或只拷 exe。
- 可以从任意工作目录启动；快捷方式目标指向 exe 即可。
- 命令行（用于批处理或验证）支持：

```powershell
WindTrace.exe --smoke flight.wtr                                  # 只校验容器并输出摘要，不开窗口
WindTrace.exe flight.wtr --screenshot shot.png --time 15.5        # 离屏截图
WindTrace.exe flight.wtr --screenshot orbit.png --time 20 --camera-mode orbit
WindTrace.exe flight.wtr --screenshot mix.png --time 20 --camera-preset showcase
WindTrace.exe flight.wtr --screenshot params.png --panel parameters --search indi
WindTrace.exe flight.wtr --screenshot enu.png --world-frame ENU
```

## 打开 WTR 文件

三种方式，效果相同：

1. 启动后在欢迎页点“打开”，或双击最近记录。
2. 窗口内按 `Ctrl+O` 打开文件对话框。
3. 命令行传路径：`WindTrace.exe "D:\data\flight.wtr"`。

打开失败时窗口会保留上一份飞行并给出错误原因（成员哈希不符、时间不递增、缺少核心 topic 等），
不会静默换一份文件。最近记录只写进本机设置，不写进 `.wtr`。

## Python 开发启动

需要 Python 3.13。在本目录建立独立环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py            # 从欢迎页启动
.\.venv\Scripts\python.exe app.py flight.wtr # 直接打开
.\.venv\Scripts\python.exe app.py --smoke flight.wtr
```

也可以用 `run_app.cmd`：它依次尝试环境变量 `WINDTRACE_PYTHON`、本目录 `.venv`、系统 `python`，
不写死开发机路径：

```powershell
.\run_app.cmd flight.wtr
```

常用命令行选项：`--smoke`（纯后台校验）、`--no-3d`、`--screenshot PATH`、`--time 秒`、
`--panel 3d|parameters|curves`、`--drawer`、`--search 关键字`、`--camera-mode`、`--camera-preset`、
`--camera-file`、`--world-frame NED|ENU`、`--body-frame`、`--settings-file 独立.ini`。
`--screenshot` 默认离屏渲染，不占用桌面。

快捷键：`空格` 播放／暂停，`Tab` 左侧抽屉，`C` 曲线抽屉，`Esc` 收起抽屉，
`Home` 回到 0 秒，`Ctrl+O` 打开文件。

## 运行测试

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
```

- 测试使用离屏 Qt（`QT_QPA_PLATFORM=offscreen`），不移动鼠标、不回写日志。
- 容器契约、参数、运镜、主题对比度和“夹具容器驱动”的界面回归不依赖外部数据；
  夹具由 `tests/wtr_builder.py` 现场生成，不需要 MATLAB。
- 真实历史 `.wtr` 的界面验收由环境变量提供，未提供时相关用例明确 skip：

```powershell
$env:WINDTRACE_TEST_FLIGHTS="D:\a.wtr;D:\b.wtr"
.\.venv\Scripts\python.exe -m pytest tests -q
```

## 重新打包 EXE

```powershell
.\build_app.ps1 -Force
```

默认使用本目录 `.venv`，输出到 `dist\WindTrace\WindTrace.exe`；构建过程隔离 `PATH`，
避免收进其他工具的同名 DLL。参数：`-PythonExecutable <python.exe>` 指定解释器，
`-OutputDirectory <目录>` 指定输出（只允许仓库内 `dist`），`-Force` 覆盖重建。
`dist`、`build`、`.venv` 都不进入 Git。

打包后建议自检：

```powershell
.\dist\WindTrace\WindTrace.exe --smoke D:\data\flight.wtr
.\dist\WindTrace\WindTrace.exe D:\data\flight.wtr --screenshot shot.png --time 12
```

## WTR v1 数据格式

`.wtr` 是一个 ZIP 容器，只允许四个根成员：

| 成员 | 内容 |
|---|---|
| `manifest.json` | schema、run_id、单 method、seed、scenario、duration_s、execution、audit、source、topics、members |
| `parameters.json` | 参数表：完整路径、类型、值或数组引用、单位、来源、父值与覆盖标记 |
| `flight.mat` | MATLAB v7 兼容的 `topics` 结构；`parameter_arrays` 存大数组原值 |
| `geometry.json` | FRD 坐标的示意几何与自包含网格、V1–V6 舵面编号 |

要点：时间相对任务起点、非负严格递增；姿态四元数为 Hamilton **wxyz**、FRD→NED、已归一化；
世界坐标 NED；大数组以 `array_ref` 引用；`Inf/NaN` 用 `{special_float: ...}` 显式表示。
完整字段、语义与校验规则见 **[WTR v1 契约](docs/windtrace_flight_v1.md)**，
运镜脚本格式见 **[windtrace.camera.v1](docs/windtrace_camera_v1.md)**,
示例脚本在 [assets/cameras](assets/cameras/README.md)。

## 界面约定

- **世界系**：日志与运镜脚本都按 NED 存储；显示层可切 ENU（x东、y北、z上），只改画面与 HUD。
- **机体系**：按手绘示意，x 红向右、y 绿向下、z 蓝穿入纸面；相对 FRD 为绕 z 转 90°，仅显示。
- **贴地**：按机体网格最低点做**显示用**抬升（当前示意模型约 +0.235 m），让脚架落在 z=0 网格上；
  日志位置、姿态与指标不变，也不写回 `.wtr`。
- **转子**：显示用自转（名义 2 转/秒，可在“场景”关闭）。日志没有 RPM 字段，不声称真实转速。
- **舵面**：按 `shc09_vanes` 的 ±40° 日志角度绕各自铰链轴旋转。
- **多窗口对比**：一个窗口一份飞行；相机与时间不在窗口间同步，这是刻意保留的只读边界。

相机模式一览：

| 模式 | 行为 |
|---|---|
| 跟随（默认） | 保持当前观察角度，只随机体平移 |
| 自由视角 | 相机完全手动，播放时不移动；拖动或滚轮也会切到这里 |
| 追尾 | 机体后上方固定偏移，随机体偏航转动 |
| 环绕 | 以机体为中心固定半径与仰角，可匀速扫过 |
| 总览 | 按整段航迹包围盒取景，固定机位 |
| 机体特写 | 三分之四视角特写，取景按真实网格包围盒 |
| 演示 · 发布镜头 / 对比 · 固定机位 / 特写 · 舵面 | 内置运镜预设 |
| 导入运镜 | 按任务时间执行 `windtrace.camera.v1` 脚本 |

## 目录结构

```text
app.py                 命令行入口与离屏截图流程
core/flight.py         .wtr 读取与校验
ui/                    主窗口、三维视图、相机语言、主题、示意模型解析
assets/                logo、运镜脚本、几何来源记录
tests/                 契约、界面、相机与主题测试；wtr_builder.py 为测试专用样本生成器
docs/                  WTR v1 与运镜 v1 契约、迁移来源记录
requirements.txt       运行依赖
requirements-dev.txt   测试与打包依赖
WindTrace.spec         PyInstaller 打包描述
build_app.ps1          Windows 构建脚本
run_app.cmd            开发启动快捷方式
```

## 来源与许可

WindTrace 从 `tangqingxi/Ducted-Fan-SHC09-matlab` 的 `apps/windtrace/` 独立出来，
只迁移 Viewer 需要的部分；MATLAB 日志转换器留在数据生产端。逐文件来源、提交与哈希见
[IMPORT_PROVENANCE.json](IMPORT_PROVENANCE.json) 与 [docs/migration_provenance.md](docs/migration_provenance.md)。
本仓库 MIT 许可；SHC09 示意模型来自 Hawkeye（BSD-3-Clause）；第三方声明见
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
