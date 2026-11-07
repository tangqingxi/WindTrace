# windtrace.camera.v1 · 运镜脚本格式

WindTrace 的相机脚本是**只读的旁路文件**：它只描述“在任务时间的哪一段用哪种相机”，不参与控制、估计、分配或评价，也不会写回 `.wtr`。一个脚本可以在多个日志之间复用；超出日志时长的镜头不会被播放，镜头内的时间按任务时间求值。

## 求值语义

- 时间统一使用 `.wtr` 的**任务时间**（0 到 `duration_s`），与回放倍速、帧率和拖动方式无关。
- 镜头区间是半开区间 `[start_s, end_s)`；空档保持上一镜的末帧；第一个镜头之前保持首帧；最后一个镜头之后保持末帧。
- 每个镜头内部按 `ease` 在起止参数之间插值；`transition_s` 表示镜头开头与**上一镜末帧**做平滑混合，默认 0（硬切）。
- 过渡使用三次 Hermite：位置、注视点同时匹配两端速度，FOV 线性混合，避免切换起止处的顿挫；手动切换相机模式也有约 0.65 秒缓动，鼠标拖动会立即取消。
- 脚本的相机状态完全由文件参数、当前位姿和整段航迹包围盒决定，不读取“当前鼠标视角”，因此同一时刻重复求值必然一致，适合作截图和回放复现。

## 顶层字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `schema` | string | 是 | 固定为 `windtrace.camera.v1` |
| `name` | string | 否 | 显示在“相机模式”下拉里的名字，默认“未命名运镜” |
| `description` | string | 否 | 一段说明，仅展示 |
| `shots` | array | 是 | 至少一个镜头，按 `start_s` 升序、不得重叠 |

## 镜头公共字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `start_s` / `end_s` | number | 镜头起止任务时间，`0 <= start_s < end_s` |
| `mode` | string | `fixed` / `track` / `orbit` / `chase` / `overview` / `closeup` |
| `ease` | string | `linear` / `smoothstep`（默认）/ `smootherstep` |
| `transition_s` | number | 与上一镜的混合时长，`0 <= transition_s <= 镜头时长`，默认 0 |
| `fov_deg` | number | 该镜头的相机垂直视场角，15–100，默认沿用当前相机（通常 30）；用于宽幅建立镜头与近景切换 |

未知字段会被拒绝并列出该模式允许的字段，避免拼写错误被静默忽略。

## 模式与参数

| 模式 | 必填 | 可选 | 行为 |
|---|---|---|---|
| `fixed` | `position_m`, `target_m` | `position_end_m`, `target_end_m` | 世界 NED 固定机位；可选起止两点做直线移动 |
| `track` | `position_m` | `position_end_m` | 机位固定，注视点跟随当前机体中心 |
| `orbit` | — | `radius_m`(4.5), `azimuth_deg`(35), `azimuth_end_deg`, `elevation_deg`(12), `elevation_end_deg` | 以机体中心为圆心，半径与仰角固定，方位角可扫过 |
| `chase` | `offset_m` | `offset_end_m`, `look_ahead_m`(0) | 机体偏航坐标系内的 `[前, 右, 上]` 偏移；相机随偏航转动 |
| `overview` | — | `pad`(1.05), `direction`(`isometric`/`front`/`side`/`top`) | 按整段航迹包围盒取景，固定机位 |
| `closeup` | — | `azimuth_deg`(35), `elevation_deg`(18), `distance_scale`(2.2) | 按模型包围盒取三分之四特写，随机体平移 |

坐标约定：`position_m`/`target_m` 为世界 **NED**（北、东、下），单位 m；地面为 `z=0`，空中为负（例如 10 m 高写成 `z=-10`）。`azimuth_deg` 从 +N 向 +E 计；`elevation_deg` 相对水平面，正值表示相机在机体上方；`chase.offset_m` 的第一分量沿机体水平前向、第二分量沿右向、第三分量沿世界向上（`-z`）。

## 最小示例

```json
{
  "schema": "windtrace.camera.v1",
  "name": "起飞三段式",
  "shots": [
    {"start_s": 0, "end_s": 12, "mode": "fixed",
     "position_m": [-9, 9, -6.5], "target_m": [0, 0, -2]},
    {"start_s": 12, "end_s": 27, "mode": "orbit",
     "radius_m": 5, "azimuth_deg": 35, "azimuth_end_deg": 95,
     "elevation_deg": 12, "transition_s": 0.8},
    {"start_s": 27, "end_s": 55, "mode": "chase",
     "offset_m": [-4.5, 0, 1.8], "transition_s": 0.8}
  ]
}
```

相机脚本的坐标**始终按 NED**（x北、y东、z下）解释，与 Viewer 当前显示的是 NED 还是 ENU 无关；切到 ENU 只是显示层转换。旧 ENU 脚本需先转成 NED（`NED=[ENU_y, ENU_x, -ENU_z]`）再导入。

可直接打开的完整示例见 [`assets/cameras/`](../assets/cameras/README.md)。应用内还内置三套预设：

| 预设 | 用途 |
|---|---|
| 演示 · 发布镜头 | 起飞环绕升降、偏航短追尾、扰动段固定机位、恢复与收尾 |
| 对比 · 固定机位 | 0–12 秒宽幅爬升、12–55 秒固定高 3/4；多窗口并排时两边用同一机位与时刻 |
| 特写 · 舵面 | 低角度跟随特写，观察涵道与六舵面动作 |

一个 WindTrace 窗口只打开一份 `.wtr`；比较不同方法时开多个窗口，各自选“对比 · 固定机位”，不在一窗口内叠加多方法，也不做跨窗口同步。

## 校验与错误

- 顶层不是 JSON 对象、`schema` 不匹配、`shots` 为空、镜头时间重叠、`end_s <= start_s`、模式未知、必填参数缺失、数值非有限、`transition_s` 超过镜头时长、未知字段，都会拒绝导入。
- 导入失败时保留当前相机，并在界面显示可读的错误原因和镜头序号；不静默回退到默认相机，也不改动当前日志。
- 相机设置只写入本机 QSettings（`camera/mode`、`camera/script`），不写 `.wtr`、不写仿真参数。

## 编排建议

以下只是经验值，不是校验门槛：

- 单镜头不短于约 2.5–3 秒；任意 15 秒内不超过 4–5 次镜头变化。
- 起飞、恢复等需要对照的段落用固定机位；滚转、偏航等姿态段落用环绕或追尾。
- 避免“拉远—推近—拉远”的往返；结尾回全景并停留约 0.8 秒。
- 每个镜头先回答“这一段要替观众看清什么”，答不上来就不切。
- 交互式回放中鼠标拖动会切到“自由视角”，脚本暂停；重新选择脚本从当前时间恢复。
