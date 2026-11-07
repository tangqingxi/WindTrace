# 运镜示例

这些 JSON 是 `windtrace.camera.v1` 的示例，可直接在“场景 → 导入运镜…”中打开。
应用内也内置了“演示 · 发布镜头 / 对比 · 固定机位 / 特写 · 舵面”三项，不导入也能用。
镜头按**任务时间**求值，与回放倍速无关；拖动时间轴会立即跳到该时刻的镜头。

| 文件 | 编排 |
|---|---|
| `showcase_55s.json` | 起飞环绕升降 → 偏航短追尾 → 扰动固定机位 → 恢复 → 收尾环绕 |
| `analysis_55s.json` | 宽幅爬升 → 扰动段固定高 3/4 机位（多窗口对比用） |
| `vane_closeup_55s.json` | 低角度舵面/涵道特写 |
| `orbit_55s.json` | 全程缓慢环绕 |
| `overview_closeup.json` | 总览 → 机体特写 → 总览 |

格式、字段与校验规则见 [`docs/windtrace_camera_v1.md`](../../docs/windtrace_camera_v1.md)。
