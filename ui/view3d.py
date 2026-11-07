"""只消费.wtr中已转换的FRD网格和姿态，不再执行SHC09坐标变换。

v1.1：按几何底点把示意模型抬到地面；相机模式与导入运镜统一由 ui.camera 求值；
转子只做显示用自转（日志没有 RPM），舵面仍按日志角度旋转；地面投影与参考误差线只服务阅读。
"""
import os
import time

import numpy as np
from PySide6 import QtCore, QtWidgets
from scipy.spatial.transform import Rotation

from ui import camera as camera_language
from ui import theme

WORLD_UP = np.array([0., 0., -1.])          # NED 的“上”是 -z
NED_TO_ENU = np.array([[0., 1., 0.], [1., 0., 0.], [0., 0., -1.]])
ROTOR_REV_PER_S = 2.0


class ReplayView3D(QtWidgets.QWidget):
    """三维回放视图；相机只读日志位姿，不参与控制或评价。"""

    cameraInteracted = QtCore.Signal()

    def __init__(self, disabled=False):
        super().__init__()
        self.plotter = None
        self.error = ""
        self.flight = None
        self.actors = []
        self.world_frame = 'NED'
        self.display_rotation = np.eye(3)
        self.body_frame_visible = False
        self.body_frame_actors = []
        self.grid_visible = True
        self.reference_visible = False
        self.ground_projection_visible = True
        self.reference_error_visible = True
        self.grid_actors = []
        self.reference_actors = []
        self.camera_mode = "follow"
        self.camera_script = None
        self.ground_lift_m = 0.0
        self.model_radius_m = 0.35
        self.model_center_m = np.zeros(3)
        self.path_center = np.zeros(3)
        self.path_radius_m = 8.0
        self.vane_centers = []
        self.vane_label_actors = []
        self.vane_label_actor = None
        self._label_time = -np.inf
        self.rotor_actor = None
        self.rotor_center = np.zeros(3)
        self.rotor_spinning = True
        self.ground_line_actor = None
        self.ground_ring_actor = None
        self.reference_marker_actor = None
        self.reference_line_actor = None
        self.reference_line = None
        self.heading_smoothed = None
        self.ref_time = None
        self.ref_position = None
        self._last_position = None
        self._current_time = 0.0
        self._pose_index = 0
        self._att_index = 0
        self._builtin_cache = {}
        self._tween = None
        self.offscreen = os.environ.get("QT_QPA_PLATFORM") == "offscreen"
        self.badge = QtWidgets.QLabel(self)
        self.badge.setObjectName('viewOverlay')
        self.badge.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.badge.hide()
        self.badge_margin = 48
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self._tween_timer = QtCore.QTimer(self)
        self._tween_timer.setInterval(16)
        self._tween_timer.timeout.connect(self._tick_tween)
        if disabled:
            self.layout.addWidget(QtWidgets.QLabel("3D已禁用；参数与曲线仍可读取。"))
            return
        try:
            import pyvista as pv
            self.pv = pv
            if self.offscreen:
                self.plotter = pv.Plotter(off_screen=True, window_size=(1400, 760))
                self.surface = self
                self.layout.addWidget(QtWidgets.QLabel("后台离屏三维渲染"))
            else:
                from pyvistaqt import QtInteractor
                self.plotter = QtInteractor(self, multi_samples=0, auto_update=False)
                self.surface = self.plotter.interactor
                self.layout.addWidget(self.surface)
            self.plotter.set_background(theme.SCENE['background_bottom'], top=theme.SCENE['background_top'])
            # 网格不参与机体取景边界，交互器不能仅按机体边界收缩裁剪面。
            style = self.plotter.iren.style
            style.AutoAdjustCameraClippingRangeOff()
            self._interaction_observer = style.AddObserver('InteractionEvent', self.update_clipping_range)
            # 用户鼠标一旦介入就退出自动相机，避免脚本和鼠标抢镜头。
            self._manual_observer = style.AddObserver('StartInteractionEvent', self._on_manual_interaction)
        except Exception as problem:
            self.error = str(problem)
            self.layout.addWidget(QtWidgets.QLabel("3D不可用：" + self.error))

    # ------------------------------------------------------------------ 场景
    def _rebuild_axes(self):
        if self.plotter is None:
            return
        try:
            self.plotter.hide_axes()
        except Exception:
            pass
        labels = ("E", "N", "U") if self.world_frame == "ENU" else ("N", "E", "D")
        self.plotter.add_axes(xlabel=labels[0], ylabel=labels[1], zlabel=labels[2],
                              color=theme.SCENE['axis_label'],
                              x_color=theme.SCENE['axis_x'], y_color=theme.SCENE['axis_y'], z_color=theme.SCENE['axis_z'],
                              label_size=(0.30, 0.12), line_width=3)

    def _to_display(self, vector):
        return self.display_rotation @ np.asarray(vector, dtype=float)

    def _to_display_state(self, state):
        if state is None:
            return None
        T = self.display_rotation
        return camera_language.CameraState(position=T @ state.position,
                                           focal_point=T @ state.focal_point,
                                           up=T @ state.up,
                                           fov_deg=state.fov_deg)

    def set_world_frame(self, frame):
        frame = str(frame).upper()
        if frame not in ("NED", "ENU") or frame == self.world_frame:
            return
        old = self.display_rotation
        self.world_frame = frame
        self.display_rotation = np.eye(3) if frame == "NED" else NED_TO_ENU.copy()
        self._rebuild_axes()
        if self.plotter is None or self.flight is None:
            return
        self._stop_tween()
        convert = self.display_rotation @ old.T
        state = self._camera_state()
        state = camera_language.CameraState(position=convert @ state.position,
                                            focal_point=convert @ state.focal_point,
                                            up=convert @ state.up,
                                            fov_deg=state.fov_deg)
        self._apply_state(state)
        if self._last_position is not None:
            self._last_position = convert @ self._last_position
        self.set_time(self._current_time)
        self.plotter.render()

    def _build_body_frame(self):
        if self.plotter is None:
            return
        self.body_frame_actors = []
        for direction, color in [((1., 0., 0.), '#DC2626'), ((0., 1., 0.), '#16A34A'), ((0., 0., 1.), '#2563EB')]:
            arrow = self.pv.Arrow(start=(0., 0., 0.), direction=direction, scale=0.38,
                                  tip_length=0.22, tip_radius=0.050, shaft_radius=0.014)
            actor = self.plotter.add_mesh(arrow, color=color, lighting=False)
            actor.SetUseBounds(False)
            actor.SetVisibility(False)
            self.body_frame_actors.append(actor)

    def set_body_frame_visible(self, visible):
        self.body_frame_visible = bool(visible)
        for actor in self.body_frame_actors:
            actor.SetVisibility(self.body_frame_visible)
        if self.flight is not None:
            self._update_body_frame()
        if self.plotter:
            self.plotter.render()

    def _update_vane_labels(self, pos, R, time_value):
        if self.plotter is None or not self.vane_centers:
            return
        if self.vane_label_actor is not None and abs(time_value - self._label_time) < 0.2:
            return
        if self.vane_label_actor is not None:
            self.plotter.remove_actor(self.vane_label_actor)
            self.vane_label_actor = None
        points = []
        for center in self.vane_centers:
            radial = np.array([center[0], center[1], 0.0])
            norm = np.linalg.norm(radial[:2])
            offset = radial * (0.07 / norm) if norm > 1e-9 else np.zeros(3)
            points.append(pos + R @ (center + offset))
        points = np.asarray(points, dtype=float)
        labels = [str(i + 1) for i in range(len(points))]
        self.vane_label_actor = self.plotter.add_point_labels(
            points, labels, font_size=18, shape=None, always_visible=True,
            show_points=False, text_color="#f0c040", name="vane_numbers")
        self.vane_label_actor.SetUseBounds(False)
        self._label_time = time_value

    def _update_body_frame(self):
        if not self.body_frame_actors or self.flight is None:
            return
        k = min(self._pose_index, len(self.position) - 1)
        pos = self._to_display(self.position[k])
        R = self.display_rotation @ self.rotations[self._att_index]
        matrix = np.eye(4)
        # 真实 b 系：b1 右、b2 下、b3 穿入纸面（FRD z 下）。
        # 即 FRD 绕 z 转 90°：b1=+y_FRD，b2=-x_FRD，b3=+z_FRD，右手系。
        matrix[:3, 0] = R[:, 1]       # b1：右（FRD +y）
        matrix[:3, 1] = -R[:, 0]      # b2：下（FRD -x）
        matrix[:3, 2] = R[:, 2]       # b3：入纸/下（FRD +z）
        matrix[:3, 3] = pos + R @ (self.model_center_m + np.array([0.0, 0.0, -0.10]))
        for actor in self.body_frame_actors:
            actor.user_matrix = matrix
            actor.SetVisibility(self.body_frame_visible)

    def set_flight(self, flight, domain):
        self.flight = flight
        self.domain = domain
        if self.plotter is None:
            return
        self._stop_tween()
        p = self.plotter
        p.clear()
        self.actors = []
        self.body_frame_actors = []
        self._last_position = None
        self._builtin_cache = {}
        self.grid_actors = []
        self.reference_actors = []
        self.vane_centers = []
        self.vane_label_actors = []
        self.vane_label_actor = None
        self._label_time = -np.inf
        self.rotor_actor = None
        self.ground_line_actor = None
        self.ground_ring_actor = None
        self.reference_marker_actor = None
        self.reference_line_actor = None
        self.reference_line = None
        p.set_background(theme.SCENE['background_bottom'], top=theme.SCENE['background_top'])
        self._rebuild_axes()
        position_topic = "trajectory_setpoint" if domain == "reference" else "vehicle_local_position" + ("_groundtruth" if domain == "truth" else "")
        self.pose_time = flight.time(position_topic)
        self.position = flight.position(position_topic)
        att = "vehicle_attitude_reference" if domain == "reference" else "vehicle_attitude" + ("_groundtruth" if domain == "truth" else "")
        self.att_time = flight.time(att)
        q = flight.field(att, "q")
        self.rotations = Rotation.from_quat(q[:, [1, 2, 3, 0]]).as_matrix()
        self._smooth_heading()
        self.ref_time = flight.time("trajectory_setpoint")
        self.ref_position = flight.position("trajectory_setpoint")
        self.add_ground_grid()
        # 三维只保留可选的规划参考，不绘制真实或估计轨迹。
        for topic, color, label in [("trajectory_setpoint", theme.COLORS['reference'], "参考轨迹")]:
            points = flight.position(topic)
            stride = max(1, len(points) // 4000)
            points = points[::stride]
            if np.linalg.norm(np.ptp(points, axis=0)) > 1e-9:
                actor = p.add_mesh(self.pv.lines_from_points(points), color=color, line_width=1.5, label=label)
            else:
                actor = p.add_points(points[:1], color=color, point_size=6, label=label, render_points_as_spheres=True)
            actor.SetVisibility(self.reference_visible)
            actor.SetUseBounds(False)
            self.reference_actors.append(actor)
        meshes = flight.geometry["meshes"]
        points = np.asarray(meshes["body"]["points"], dtype=float).copy()
        # 示意模型的局部 +z 朝下；最低点（脚架）相对原点的偏移就是贴地抬升量。
        self.ground_lift_m = float(np.max(points[:, 2])) if len(points) else 0.0
        points[:, 2] -= self.ground_lift_m
        span = np.ptp(points, axis=0) if len(points) else np.zeros(3)
        self.model_radius_m = max(0.05, 0.5 * float(np.linalg.norm(span)))
        if len(points):
            zmin, zmax = float(points[:, 2].min()), float(points[:, 2].max())
            self.model_center_m = np.array([0.0, 0.0, (zmin + zmax) / 2.0])
        else:
            self.model_center_m = np.zeros(3)
        body = self.pv.PolyData(points, np.asarray(meshes["body"]["faces"]))
        codes = np.asarray(meshes["body"].get("part", []))
        if len(codes) == body.n_points:
            # 网格分类编号沿用原解析器：0涵道、1机身、2转子、3脚架；不能按名称直觉反转。
            body.compute_normals(cell_normals=False, point_normals=True, auto_orient_normals=True, inplace=True)
            light = np.array([-.40, -.35, -.85])
            light /= np.linalg.norm(light)
            dot = np.clip(np.asarray(body.point_data.active_normals) @ light, 0, 1)
            shade = np.where(codes == 0, .62 + .38 * dot, .55 + .45 * dot)
            palette = np.array([list(bytes.fromhex(theme.MODEL_COLORS[key].lstrip('#'))) for key in ['duct', 'body', 'rotor', 'leg']], dtype=float)
            body.point_data['rgb'] = np.clip(np.rint(palette[codes.astype(int)] * shade[:, None]), 0, 255).astype(np.uint8)
            # 转子拆成独立actor，才能绕自身轴自转；日志没有RPM，这只是显示转速。
            triangles = np.asarray(body.faces).reshape(-1, 4)[:, 1:]
            rotor_cells = np.where(np.all(codes[triangles] == 2, axis=1))[0]
            if len(rotor_cells):
                rotor_mesh = body.extract_cells(rotor_cells).extract_surface(algorithm="dataset_surface")
                keep = np.setdiff1d(np.arange(body.n_cells), rotor_cells)
                body = body.extract_cells(keep).extract_surface(algorithm="dataset_surface")
                rotor_points = np.asarray(rotor_mesh.points, dtype=float).copy()
                self.rotor_center = rotor_points.mean(axis=0)
                rotor_mesh.points = rotor_points - self.rotor_center
                rotor_mesh.compute_normals(cell_normals=False, point_normals=True, auto_orient_normals=True, inplace=True)
                rotor_mesh.set_active_scalars(None)
                self.rotor_actor = p.add_mesh(rotor_mesh, color=theme.MODEL_COLORS['rotor'],
                                              smooth_shading=True, lighting=False)
                self.rotor_actor.SetUseBounds(False)
            actor = p.add_mesh(body, scalars="rgb", rgb=True, smooth_shading=True, lighting=False, show_scalar_bar=False)
        else:
            body.compute_normals(cell_normals=False, point_normals=True, auto_orient_normals=True, inplace=True)
            actor = p.add_mesh(body, color=theme.MODEL_COLORS['body'], lighting=False)
        self.actors.append(actor)
        for part in meshes["vanes"]:
            mesh = self.pv.PolyData(np.asarray(part["points"]), np.asarray(part["faces"]))
            self.actors.append(p.add_mesh(mesh, color=theme.MODEL_COLORS['vane'], smooth_shading=True,
                                          show_edges=True, edge_color=theme.MODEL_COLORS['vane_edge'],
                                          line_width=.7, lighting=False))
            center = np.asarray(part["center"], dtype=float).copy()
            center[2] -= self.ground_lift_m
            self.vane_centers.append(center)
        # 整段航迹包围盒用于总览取景；模型的抬升已计入几何，不再重复。
        lo, hi = self.position.min(axis=0), self.position.max(axis=0)
        self.path_center = (lo + hi) / 2.0
        self.path_radius_m = max(1.0, 0.5 * float(np.linalg.norm(hi - lo)) + self.model_radius_m)
        self._add_analysis_overlays()
        self._build_body_frame()
        self.set_time(0.0)
        if self.camera_mode in ("chase", "orbit", "overview", "closeup"):
            self.apply_camera(0.0)
        elif self.camera_mode == "script" and self.camera_script is not None:
            self.apply_camera(0.0)
        else:
            self.frame_vehicle()
        p.render()
        # QtInteractor没有公开的off_screen属性，使用本视图选定的渲染模式。
        if self.offscreen:
            p.show(auto_close=False, interactive=False)

    def _smooth_heading(self):
        forward = self.rotations[:, :, 0]
        theta = np.unwrap(np.arctan2(forward[:, 1], forward[:, 0]))
        if len(theta) < 2:
            self.heading_smoothed = theta
            return
        dt = np.diff(self.att_time)
        dt = np.maximum(dt, 1e-6)
        alpha = dt / (0.35 + dt)
        out = np.empty_like(theta)
        out[0] = theta[0]
        for index in range(1, len(theta)):
            out[index] = out[index - 1] + alpha[index - 1] * (theta[index] - out[index - 1])
        self.heading_smoothed = out

    def _add_analysis_overlays(self):
        p = self.plotter
        line = self.pv.Line((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        self.ground_line_actor = p.add_mesh(line, color=theme.COLORS['muted'], line_width=0.8, lighting=False)
        self.ground_line_actor.prop.opacity = 0.45
        self.ground_line_actor.SetUseBounds(False)
        angles = np.linspace(0.0, 2.0 * np.pi, 49)
        ring_points = np.column_stack([0.32 * np.cos(angles), 0.32 * np.sin(angles), np.full_like(angles, 0.0)])
        ring = self.pv.lines_from_points(ring_points, close=True)
        self.ground_ring_actor = p.add_mesh(ring, color=theme.COLORS['muted'], line_width=0.9, lighting=False)
        self.ground_ring_actor.prop.opacity = 0.6
        self.ground_ring_actor.SetUseBounds(False)
        self.reference_marker_actor = p.add_mesh(self.pv.Sphere(radius=0.06), color="#B45309", lighting=False)
        self.reference_marker_actor.SetUseBounds(False)
        self.reference_line = self.pv.Line((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        self.reference_line_actor = p.add_mesh(self.reference_line, color="#B45309", line_width=0.9, lighting=False)
        self.reference_line_actor.SetUseBounds(False)
        self.set_ground_projection(self.ground_projection_visible)
        self.set_reference_error(self.reference_error_visible)

    def add_ground_grid(self):
        # 地面退到背景层：细线、低透明度、较近处淡出，避免抢无人机的视觉中心。
        for step, half, color, width in [(1., 70., theme.COLORS['grid_minor'], .7), (5., 100., theme.COLORS['grid_major'], .9)]:
            segments = []
            for value in np.arange(-half, half + .5, step):
                if step == 1 and abs(value / 5 - round(value / 5)) < 1e-9:
                    continue
                segments.extend([[(value, -half, 0), (value, half, 0)], [(-half, value, 0), (half, value, 0)]])
            points = np.asarray(segments).reshape(-1, 3)
            cells = np.column_stack([np.full(len(segments), 2), np.arange(0, len(points), 2), np.arange(1, len(points), 2)]).ravel()
            mesh = self.pv.PolyData(points, lines=cells)
            rgba = np.empty((len(points), 4), dtype=np.uint8)
            rgba[:, :3] = list(bytes.fromhex(color.lstrip('#')))
            fade = 1 - np.clip((np.hypot(points[:, 0], points[:, 1]) - 20) / 60, 0, 1)
            rgba[:, 3] = np.rint((0.40 + 0.25 * fade) * 255).astype(np.uint8)
            mesh.point_data['grid_rgba'] = rgba
            actor = self.plotter.add_mesh(mesh, scalars='grid_rgba', rgb=True, line_width=width,
                                          show_scalar_bar=False, lighting=False)
            actor.SetVisibility(self.grid_visible)
            actor.SetUseBounds(False)
            self.grid_actors.append(actor)

    # ------------------------------------------------------------------ 相机
    def set_camera_mode(self, mode, script=None, animate=True):
        previous = self.camera_mode
        self.camera_mode = str(mode)
        if self.camera_mode == "script":
            self.camera_script = script
        if self.plotter is None or self.flight is None:
            return
        self._tween_timer.stop()
        self._tween = None
        if self.camera_mode == "follow":
            # 从当前画面开始跟随，避免切换瞬间按旧增量跳动。
            self._last_position = self._to_display(self.position[self._pose_index])
        elif self.camera_mode in ("chase", "orbit", "overview", "closeup", "script"):
            self._last_position = None
            if animate and previous != self.camera_mode:
                self._start_tween()
            else:
                self.apply_camera(self._current_time)
        self.update_clipping_range()
        self.plotter.render()

    def _camera_state(self):
        camera = self.plotter.camera
        return camera_language.CameraState(position=np.asarray(camera.position, dtype=float).copy(),
                                           focal_point=np.asarray(camera.focal_point, dtype=float).copy(),
                                           up=np.asarray(camera.up, dtype=float).copy(),
                                           fov_deg=float(camera.view_angle))

    def _start_tween(self):
        self._tween = {'start': time.monotonic(), 'duration': 0.65, 'from': self._camera_state()}
        self._tween_timer.start()

    def _tick_tween(self):
        if self._tween is None or self.flight is None:
            self._tween_timer.stop()
            self._tween = None
            return
        elapsed = (time.monotonic() - self._tween['start']) / self._tween['duration']
        target = self._evaluate_current(self._current_time)
        if target is None:
            self._tween_timer.stop()
            self._tween = None
            return
        progress = min(1.0, max(0.0, elapsed))
        eased = progress * progress * (3.0 - 2.0 * progress)
        state = camera_language._blend_states(self._tween['from'], target, eased)
        self._apply_state(state)
        self.update_clipping_range()
        self.plotter.render()
        if progress >= 1.0:
            self._tween_timer.stop()
            self._tween = None

    def set_camera_follow(self, enabled):
        """兼容旧调用：True=跟随，False=自由。"""
        self.set_camera_mode("follow" if enabled else "free")

    def _builtin(self):
        mode = self.camera_mode
        if mode not in self._builtin_cache:
            duration = float(self.flight.manifest["duration_s"]) if self.flight is not None else 60.0
            self._builtin_cache[mode] = camera_language.builtin_script(mode, duration)
        return self._builtin_cache[mode]

    def _pose(self):
        if self.heading_smoothed is not None and len(self.heading_smoothed):
            heading = float(self.heading_smoothed[self._att_index])
            forward = np.array([np.cos(heading), np.sin(heading), 0.0])
        else:
            forward = np.array([1.0, 0.0, 0.0])
        forward /= max(float(np.linalg.norm(forward)), 1e-9)
        right = np.cross(forward, WORLD_UP)
        right /= max(float(np.linalg.norm(right)), 1e-9)
        return camera_language.Pose(
            position=self.position[self._pose_index].copy(),
            forward=forward, right=right,
            fov_deg=float(self.plotter.camera.view_angle),
            model_radius_m=self.model_radius_m,
            model_center_m=self.model_center_m,
            path_center=self.path_center, path_radius_m=self.path_radius_m,
        )

    def _evaluate_current(self, time_value):
        if self.camera_mode == "script":
            script = self.camera_script
            if script is None:
                return None
        elif self.camera_mode in ("chase", "orbit", "overview", "closeup"):
            script = self._builtin()
        else:
            return None
        return self._to_display_state(camera_language.evaluate(script, float(time_value), self._pose()))

    def _apply_state(self, state):
        camera = self.plotter.camera
        camera.position = state.position
        camera.focal_point = state.focal_point
        camera.up = state.up
        camera.view_angle = max(10.0, min(100.0, float(state.fov_deg)))

    def apply_camera(self, time_value):
        state = self._evaluate_current(time_value)
        if state is not None:
            self._apply_state(state)

    def frame_vehicle(self):
        if self.plotter is None or self.flight is None:
            return
        self._stop_tween()
        self._pose_index = max(0, min(len(self.pose_time) - 1, self._pose_index))
        self._att_index = max(0, min(len(self.att_time) - 1, self._att_index))
        state = self._to_display_state(camera_language.evaluate(camera_language.builtin_script("closeup", 1.0), self._current_time, self._pose()))
        self._apply_state(state)
        self.update_clipping_range()
        self.plotter.render()

    def frame_overview(self):
        if self.plotter is None or self.flight is None:
            return
        self._stop_tween()
        self._pose_index = max(0, min(len(self.pose_time) - 1, self._pose_index))
        self._att_index = max(0, min(len(self.att_time) - 1, self._att_index))
        state = self._to_display_state(camera_language.evaluate(camera_language.builtin_script("overview", 1.0), self._current_time, self._pose()))
        self._apply_state(state)
        self.update_clipping_range()
        self.plotter.render()

    def _stop_tween(self):
        self._tween_timer.stop()
        self._tween = None

    def _on_manual_interaction(self, *_):
        self._stop_tween()
        self.cameraInteracted.emit()

    def update_clipping_range(self, *_):
        if self.plotter is None:
            return
        # 覆盖原点附近的完整地面网格；拉远相机时同步增加远裁剪距离。
        far = max(500., float(np.linalg.norm(self.plotter.camera.position)) + 200.)
        self.plotter.camera.SetClippingRange(.05, far)

    # ------------------------------------------------------------------ 状态
    def set_grid_visible(self, visible):
        self.grid_visible = bool(visible)
        for actor in self.grid_actors:
            actor.SetVisibility(self.grid_visible)
        if self.plotter:
            self.plotter.render()

    def set_reference_visible(self, visible):
        self.reference_visible = bool(visible)
        for actor in self.reference_actors:
            actor.SetVisibility(self.reference_visible)
        if self.plotter:
            self.plotter.render()

    def set_ground_projection(self, visible):
        self.ground_projection_visible = bool(visible)
        for actor in (self.ground_line_actor, self.ground_ring_actor):
            if actor is not None:
                actor.SetVisibility(self.ground_projection_visible)
        if self.plotter:
            self.plotter.render()

    def set_reference_error(self, visible):
        self.reference_error_visible = bool(visible)
        for actor in (self.reference_marker_actor, self.reference_line_actor):
            if actor is not None:
                actor.SetVisibility(self.reference_error_visible)
        if self.plotter:
            self.plotter.render()

    def set_badge_margin(self, margin):
        self.badge_margin = int(margin)
        if self.badge.isVisible():
            self.badge.move(self.badge_margin, 12)

    def set_rotor_spinning(self, enabled):
        self.rotor_spinning = bool(enabled)
        if self.flight is not None:
            self.set_time(self._current_time)

    def set_time(self, time_value):
        if self.plotter is None or self.flight is None:
            return
        k = max(0, min(len(self.pose_time) - 1, int(np.searchsorted(self.pose_time, time_value, side="right") - 1)))
        j = max(0, min(len(self.att_time) - 1, int(np.searchsorted(self.att_time, time_value, side="right") - 1)))
        self._pose_index = k
        self._att_index = j
        self._current_time = float(time_value)
        R = self.display_rotation @ self.rotations[j]
        pos = self._to_display(self.position[k])
        matrix = np.eye(4)
        matrix[:3, :3] = R
        matrix[:3, 3] = pos
        self.actors[0].user_matrix = matrix
        if self.rotor_actor is not None:
            angle = 2.0 * np.pi * ROTOR_REV_PER_S * self._current_time if self.rotor_spinning else 0.0
            rotor_matrix = np.eye(4)
            rotor_matrix[:3, :3] = Rotation.from_rotvec([0.0, 0.0, angle]).as_matrix()
            rotor_matrix[:3, 3] = self.rotor_center
            self.rotor_actor.user_matrix = matrix @ rotor_matrix
        f = self.flight
        topic = "shc09_vanes"
        vtime = f.time(topic)
        n = max(0, min(len(vtime) - 1, int(np.searchsorted(vtime, time_value, side="right") - 1)))
        values = f.field(topic, "actual" if self.domain == "truth" else "estimated")[n]
        for i, part in enumerate(f.geometry["meshes"]["vanes"]):
            self.actors[i + 1].visibility = self.domain != "reference"
            matrix = np.eye(4)
            matrix[:3, :3] = R @ Rotation.from_rotvec(np.asarray(part["axis"]) * values[i]).as_matrix()
            matrix[:3, 3] = pos + R @ self.vane_centers[i]
            self.actors[i + 1].user_matrix = matrix
            if i < len(self.vane_label_actors):
                label, label_center = self.vane_label_actors[i]
                label.SetPosition(*(pos + R @ label_center))
        self._update_vane_labels(pos, R, time_value)
        self._update_body_frame()
        self._update_overlays(pos, R)
        self._update_badge(pos, time_value)
        if self.camera_mode == "follow":
            # 仅跟随平移，保留观察角度；不随飞机偏航旋转，也不改变飞行状态。
            if self._last_position is not None:
                delta = pos - self._last_position
                camera = self.plotter.camera
                camera.position = np.asarray(camera.position) + delta
                camera.focal_point = np.asarray(camera.focal_point) + delta
            self._last_position = pos.copy()
        elif self.camera_mode in ("chase", "orbit", "overview", "closeup", "script"):
            if self._tween is None:
                self.apply_camera(time_value)
        # 更新相机位置时VTK会根据尚未移动的旧网格重算裁剪面；完成位姿更新后统一恢复。
        self.update_clipping_range()
        self.plotter.render()

    def _reference_at(self, time_value):
        if self.ref_time is None or self.ref_position is None or not len(self.ref_time):
            return None
        index = max(0, min(len(self.ref_time) - 1, int(np.searchsorted(self.ref_time, time_value, side="right") - 1)))
        return self.ref_position[index]

    def _update_overlays(self, pos, R):
        if self.ground_line_actor is not None:
            height = max(abs(float(pos[2])), 1e-3)
            matrix = np.eye(4)
            matrix[2, 2] = -float(pos[2])
            matrix[:3, 3] = pos
            self.ground_line_actor.user_matrix = matrix
            ring = np.eye(4)
            ring[:3, 3] = [pos[0], pos[1], -0.01 if self.world_frame == 'NED' else 0.01]
            self.ground_ring_actor.user_matrix = ring
        reference = self._reference_at(self._current_time)
        if reference is not None:
            reference = self._to_display(reference)
        if reference is None:
            for actor in (self.reference_marker_actor, self.reference_line_actor):
                if actor is not None:
                    actor.SetVisibility(False)
            return
        marker = np.eye(4)
        marker[:3, 3] = reference
        self.reference_marker_actor.user_matrix = marker
        center = pos + R @ self.model_center_m
        if self.reference_line is not None:
            self.reference_line.points = np.array([center, reference])
            self.reference_line.Modified()
        self.reference_marker_actor.SetVisibility(self.reference_error_visible)
        self.reference_line_actor.SetVisibility(self.reference_error_visible)

    def _update_badge(self, pos, time_value):
        label = {'truth': '真实状态', 'estimate': '估计状态', 'reference': '规划参考'}[self.domain]
        reference = self._reference_at(time_value)
        if reference is not None:
            reference = self._to_display(reference)
        if reference is None:
            delta_text = "Δx —&nbsp;&nbsp;Δy —&nbsp;&nbsp;Δz —"
        else:
            dx, dy, dz = (float(pos[i] - reference[i]) for i in range(3))
            delta_text = f"Δx {dx:+.2f}&nbsp;&nbsp;Δy {dy:+.2f}&nbsp;&nbsp;Δz {dz:+.2f}"
        color = theme.method_color(self.flight.manifest['method'])
        self.badge.setText(
            f"<span style='color:{color}'>&#9679;</span>&nbsp;"
            f"<span style='font-weight:600'>{self.flight.manifest['method']}</span>&nbsp;&nbsp;{label}&nbsp;&nbsp;"
            f"<span style='font-family:Consolas'>{time_value:.3f} s</span><br>"
            f"<span style='color:{theme.COLORS['muted']};font-size:8.5pt'>{self.world_frame}&nbsp;&nbsp;z {pos[2]:.2f} m&nbsp;&nbsp;{delta_text} m</span>"
        )
        self.badge.adjustSize()
        self.badge.move(self.badge_margin, 12)
        self.badge.show()
        self.badge.raise_()

    def closeEvent(self, event):
        self._stop_tween()
        if self.plotter:
            self.plotter.close()
        super().closeEvent(event)
