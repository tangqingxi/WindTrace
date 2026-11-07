# WindTrace单飞行契约 v1

本契约对应 `windtrace.flight.v1`，扩展名严格为 `.wtr`。一个ZIP容器代表一次飞行；不包含方法数组，不要求固定五种分配器，也不是ULog。

## 容器

容器只允许四个根成员，禁止重复、额外路径和外部依赖：

| 成员 | 内容 |
|---|---|
| manifest.json | schema、run_id、单method、seed、scenario、duration_s、execution、audit、source、exporter、topics与members |
| parameters.json | windtrace.parameters.v1，完整路径、类型、值／数组引用、单位、来源、父值和覆盖标志 |
| flight.mat | MATLAB v7兼容的topics结构；parameter_arrays保存大数组原值 |
| geometry.json | windtrace.geometry.v1；FRD坐标几何与自包含网格、V1–V6编号、来源哈希和显示假设 |

members覆盖其余三个成员的SHA256和字节数，不自引用manifest。源日志SHA、历史引擎指纹、输入签名及覆盖范围、保存的来源记录／旁证文件哈希、导出器源码哈希独立保留。run_id由方法、种子、源日志SHA前缀组成；同一飞行重新导出仍是同一身份，不以文件名或方法作为唯一键。

执行完成和审计通过是两件事：execution.status基于记录时长与保存cfg.duration_s；audit.original保留原status.csv匹配行，缺少则unknown；saved_checks只表示日志中原有检查，不能替代独立审计。独立审计报告另存，不更新原status或门禁。

## topic与语义

每个topic保存原始 `time_s` 与uint64 `timestamp=round(time_s*1e6)`，相对任务起点，不是绝对UTC。JSON中每个字段声明宽度、单位、来源和数据域；topic声明坐标系。时间必须非负、有限、严格递增且不超记录时长。数值不得Inf；仅lambda允许NaN表示没有对应缩放量。

| topic／字段 | 语义／单位／时钟 |
|---|---|
| vehicle_local_position.x/y/z/vx/vy/vz | EKF任务坐标，m、m/s，NED，保存状态时钟 |
| vehicle_local_position_groundtruth.* | 对象真值，独立于估计 |
| vehicle_attitude.q／vehicle_attitude_groundtruth.q | Hamilton wxyz，FRD到NED，归一化 |
| vehicle_angular_velocity.xyz | 日志中的估计偏置校正速率，rad/s，当前FRD；不是无误差真值 |
| vehicle_angular_velocity_groundtruth.xyz | 物理角速度，rad/s，真值FRD |
| trajectory_setpoint.position/velocity/acceleration | 规划轨迹，NED，m／m/s／m/s² |
| vehicle_attitude_reference.q | 规划姿态；与闭环attitude_setpoint分开 |
| vehicle_rates_reference.xyz | 规划参考机体FRD角速度；与当前估计机体系的setpoint区分 |
| vehicle_angular_acceleration_reference.xyz | 源日志有记录时导出，参考FRD，rad/s² |
| vehicle_attitude_setpoint.q／vehicle_rates_setpoint.xyz | 闭环内环设定值，仅真实400Hz控制更新点 |
| shc09_indi.v_h/v_c/gamma_sp/gamma_ff/gamma_hat | 当前估计FRD，rad/s²，保留拆分及测量来源 |
| shc09_allocation.lambda/mode | 原算法输出，400Hz；mode1中lambda不能按mode0解释 |
| actuator_servos.control/control_unclipped/command_rad | ±1归一化显示值／原归一化值／原始rad命令；400Hz |
| actuator_servos_pwm.command_rad | 实际锁存PWM命令，使用独立pwm_time，333Hz |
| shc09_vanes.actual/estimated | 六舵面物理／估计值，rad，各自来源分开 |
| shc09_raw_navigation.x/y/z | 源数据具备时导出，任务原点绑定前的EKF导航位置，NED |

原日志没有记录的原始加计、磁计、气压、GNSS观测明确列为missing_topics，不从真值合成。状态日志800Hz记录中保持的控制量通过control_updated抽取400Hz，PWM不插值；后续新日志有不同源时钟须保留实际源时钟，不能把表观记录频率当成观测更新率。

从SHC09到FRD的变换在导出层执行一次：`C=[0,1,0;-1,0,0;0,0,1]`，向量乘C，`R_FRD→NED=R_SHC→NED*C'`。几何网格也转换为FRD后打包。Viewer默认按NED显示（x北、y东、z下），相机up取−z；显示层可切ENU（仅旋转与轴名变化，不写回文件），不再做持久化的NED到ENU转换，也不得再次做SHC09到FRD。四元数相邻符号可能变化，表示的旋转保持相同；Viewer按原采样时刻选择记录，不插值伪造状态。v1.0 起 Viewer 还按机体网格最低点做**显示用**贴地抬升（当前示意模型约 0.235 m），只影响画面，不改变坐标系、日志位置或指标，该量也不写入 `.wtr`。

## 参数

生效参数取保存的cfg/model/ref/plan/spec和部分recorded_runtime，不能读取查看时的磁盘protocol。controller.*优先表达仿真实际读取的plan.controller；cfg.filter_h*仍保留原值并标来源，不冒充生效INDI设置。父值只在已保存spec.parent_controller存在时填写，否则未知，不从当前默认值补齐。

超过128元素的数组原值放在flight.mat.parameter_arrays，JSON用array_ref给出key／形状／类型；Viewer可展开完整值。Inf／NaN参数用 `{special_float: "+Inf"/"-Inf"/"NaN"}` 显式表示，不能转0或null。SciPy无法读出的MATLAB对象标unknown_matlab_object；完整交接推荐MATLAB标准化入口，unknown字段需明确披露。

未知单位保留unknown；不把项目参数改名为虚假的PX4固件参数。在线控制器可见接口与离线交付的真实对象参数是不同边界，导出不会把这些值传回控制器。

## 读写边界

WindTrace 只读：读取不向磁盘解压、不加载外部几何或当前协议，也不写回任何数值。当前单成员上限512MiB。schema、成员、哈希、形状、时间、四元数和核心topic校验失败应报错，不提供猜测的默认曲线。

容器由数据生产端生成（本项目之外）。WindTrace 不包含 MATLAB 日志转换器，也不判断文件来自哪个仿真工程：只要满足本契约就是合法输入。旧 `.wtr.mat` 和 `windtrace.study.v1` 不作为兼容入口。
