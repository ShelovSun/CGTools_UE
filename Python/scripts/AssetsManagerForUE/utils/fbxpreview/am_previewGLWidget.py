#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PreviewGLWidget —— 资产 FBX 三维预览(自写 OpenGL 视口)。

作为资产面板的 FBX 预览控件：选中资产时用纯 Python
解析其 FBX 几何/材质(utils/fbxMesh),在我们自己的 QOpenGLWidget 里渲染,支持鼠标
自由旋转/缩放/平移,**并显示漫反射贴图/固有色**。全程内存内完成,**不向用户的
UE 关卡添加任何东西**。

设计要点:
  * GLView: QOpenGLWidget 子类,独立 GL 上下文;按材质分子网格绘制(各自固有色/贴图),
    key+fill 双向光照(双面,避免反向缠绕发黑);LMB 旋转、滚轮缩放、MMB/Shift+LMB
    平移、双击或右键“居中显示”重新框选。
  * 根据模型包围盒生成有限 XZ 地面网格，静态 VBO 仅在模型变化时更新；普通线和
    每五格主线各一次 GL_LINES 绘制，模型通过深度测试自然遮挡网格。
  * 解析在后台线程(QThreadPool):worker 调 fbxMesh.read 得到几何 + 子网格(含贴图路径),
    并在 worker 线程加载贴图 QImage(已竖直翻转以匹配 GL);主线程回调里交给 GLView,
    VBO 与 GL 纹理在 paintGL 上传(此时 GL 上下文为当前)。按 (路径, mtime) 做小 LRU 缓存。
  * 右下角可切换 FBX 三维预览 / Icon 二维预览；无 FBX、解析失败或 GL 不可用时
    自动回退到 Icon。
  * 防抖 200ms + 去重。

drop-in 接口:clear() / setTitle() / setPreviewPixmap() / playerEnabled()。
由 assetTools.AssetToolsUI 实例化并放在主面板右侧；选中资产时根据其 Icon 路径推导
出同资产的 FBX(.../<asset>/Icon/<asset>.png -> .../<asset>/FBX/<asset>.fbx)并预览。
"""

import os
import math
import array
import threading

from PySide6 import QtGui
from PySide6 import QtCore
from PySide6 import QtWidgets
from PySide6 import QtOpenGL

from . import am_fbxMesh as fbxMesh
from .am_thumbnail_loader import ThumbnailLoader
from .am_surface_variants import SurfaceVariantLoader

try:
    # Qt6:QOpenGLWidget 从 QtWidgets 迁到独立的 QtOpenGLWidgets 模块
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
    _HAS_QOPENGL = True
except Exception:
    QOpenGLWidget = QtWidgets.QWidget  # 占位基类;无 QOpenGLWidget 时不会实例化 GLView
    _HAS_QOPENGL = False


# OpenGL 常量(PySide6 不直接暴露这些枚举,按值硬编码)
_GL_DEPTH_TEST = 0x0B71
_GL_COLOR_BUFFER_BIT = 0x00004000
_GL_DEPTH_BUFFER_BIT = 0x00000100
_GL_TRIANGLES = 0x0004
_GL_LINES = 0x0001
_GL_FLOAT = 0x1406

_STRIDE = 8 * 4  # pos3 + nrm3 + uv2,float32
_SKIN_STRIDE = 16 * 4  # pos3 + nrm3 + uv2 + boneIdx4 + boneWeight4,float32
_GRID_STRIDE = 3 * 4  # pos3,float32

_GL_MAX_VERTEX_UNIFORM_VECTORS = 0x8DFB

_VERT_SHADER = """
#version 120
attribute vec3 a_pos;
attribute vec3 a_nrm;
attribute vec2 a_uv;
uniform mat4 u_mvp;
varying vec3 v_nrm;
varying vec2 v_uv;
void main() {
    v_nrm = a_nrm;
    v_uv = a_uv;
    gl_Position = u_mvp * vec4(a_pos, 1.0);
}
"""

_FRAG_SHADER = """
#version 120
varying vec3 v_nrm;
varying vec2 v_uv;
uniform vec3 u_lightDir;     // key 光方向(相机前向)
uniform vec3 u_baseColor;    // 无贴图时的固有色
uniform int  u_useTex;
uniform sampler2D u_tex;
void main() {
    vec3 n = normalize(v_nrm);
    // 双面光照:abs 让反向缠绕的面也被照亮
    float d1 = abs(dot(n, normalize(-u_lightDir)));        // key(随相机)
    float d2 = abs(dot(n, normalize(vec3(-0.3, 0.6, 0.2)))); // fill(固定)
    float lit = 0.22 + 0.78 * d1 + 0.25 * d2;
    vec3 base = (u_useTex == 1) ? texture2D(u_tex, v_uv).rgb : u_baseColor;
    gl_FragColor = vec4(base * lit, 1.0);
}
"""

_GRID_VERT_SHADER = """
#version 120
attribute vec3 a_pos;
uniform mat4 u_mvp;
void main() {
    gl_Position = u_mvp * vec4(a_pos, 1.0);
}
"""

_GRID_FRAG_SHADER = """
#version 120
uniform vec3 u_color;
void main() {
    gl_FragColor = vec4(u_color, 1.0);
}
"""

# 蒙皮顶点着色器(%d 在 initializeGL 里按可用 uniform 上限填 MAX_BONES)。
# 每骨用 3×vec4 打包(4×3 仿射,省去恒为 [0,0,0,1] 的末行),比 mat4 省 1/4 uniform,
# 使 ~270 骨能塞进 1024 vec4 上限。混合 3 行与混合矩阵等价(均线性)。
# 与 _FRAG_SHADER 共用 v_nrm/v_uv;骨骼索引以 float 属性传入,GLSL 内 int() 取整。
_SKIN_VERT_SHADER = """
#version 120
attribute vec3 a_pos;
attribute vec3 a_nrm;
attribute vec2 a_uv;
attribute vec4 a_boneIdx;
attribute vec4 a_boneWeight;
uniform mat4 u_mvp;
uniform vec4 u_bones[%d];   // 每骨 3 个: 3*i+0/1/2 = 行0/1/2
varying vec3 v_nrm;
varying vec2 v_uv;
void blend(int i, float w, inout vec4 r0, inout vec4 r1, inout vec4 r2) {
    int b = 3 * i;
    r0 += w * u_bones[b];
    r1 += w * u_bones[b + 1];
    r2 += w * u_bones[b + 2];
}
void main() {
    vec4 r0 = vec4(0.0); vec4 r1 = vec4(0.0); vec4 r2 = vec4(0.0);
    blend(int(a_boneIdx.x), a_boneWeight.x, r0, r1, r2);
    blend(int(a_boneIdx.y), a_boneWeight.y, r0, r1, r2);
    blend(int(a_boneIdx.z), a_boneWeight.z, r0, r1, r2);
    blend(int(a_boneIdx.w), a_boneWeight.w, r0, r1, r2);
    vec4 p = vec4(a_pos, 1.0);
    vec3 sp = vec3(dot(r0, p), dot(r1, p), dot(r2, p));
    v_nrm = vec3(dot(r0.xyz, a_nrm), dot(r1.xyz, a_nrm), dot(r2.xyz, a_nrm));
    v_uv = a_uv;
    gl_Position = u_mvp * vec4(sp, 1.0);
}
"""


class GLView(QOpenGLWidget):
    """嵌入式 OpenGL 视口,按材质分子网格渲染一份静态网格,支持轨道相机交互。"""

    initFailed = QtCore.Signal()
    contextMenuRequested = QtCore.Signal(QtCore.QPoint)
    contextReady = QtCore.Signal()

    def __init__(self, parent=None):
        super(GLView, self).__init__(parent)

        fmt = QtGui.QSurfaceFormat()
        fmt.setDepthBufferSize(24)
        fmt.setSamples(4)  # MSAA(驱动不支持则忽略)
        self.setFormat(fmt)

        self._gl = None
        self._program = None
        self._vbo = None
        self._a_pos = self._a_nrm = self._a_uv = -1
        self._u_mvp = self._u_light = self._u_base = self._u_useTex = self._u_tex = -1
        self._init_failed = False

        # 地面网格：独立的极简 shader + 静态 VBO。每个模型只生成/上传一次，
        # paintGL 中仅增加两个 GL_LINES draw call（细线、主线各一次）。
        self._grid_program = None
        self._grid_vbo = None
        self._ga_pos = self._gu_mvp = self._gu_color = -1
        self._grid_bytes = None
        self._grid_minor_count = 0
        self._grid_major_first = 0
        self._grid_major_count = 0
        self._grid_dirty = False
        self._grid_signature = None

        # 蒙皮(动画)程序 —— 独立程序/VBO,与静态路径并存
        self._skin_program = None
        self._skin_vbo = None
        self._skin_supported = False
        self._max_bones = 0
        self._sa_pos = self._sa_nrm = self._sa_uv = self._sa_bidx = self._sa_bw = -1
        self._su_mvp = self._su_light = self._su_base = self._su_useTex = self._su_tex = -1
        self._su_bones0 = -1
        self._su_bone_locs = []      # u_bones[i] 的 location 列表(长度 3*max_bones)
        self._skin_array_ok = True   # 先试 setUniformValueArray,失败转 per-element

        # 待上传(在 paintGL 上传,确保 GL 上下文为当前)
        self._pending_bytes = None
        self._pending_count = 0
        self._pending_submeshes = []
        self._pending_images = {}
        self._dirty = False

        # 动画态
        self._is_animated = False
        self._pending_skin_bytes = None
        self._pending_palettes = None
        self._pending_frame_count = 0
        self._pending_bone_count = 0
        self._palettes = None
        self._frame_count = 0
        self._bone_count = 0
        self._fps = 30.0
        self._cur_frame = 0
        self._anim_timer = QtCore.QTimer(self)
        self._anim_timer.timeout.connect(self._advanceFrame)

        # 解析结果(md, anim, images)暂存:解析回调可能早于 initializeGL,
        # 那时 _skin_supported/_max_bones 还没就绪,需等初始化后再决策动画/静态。
        self._gl_inited = False
        self._pending_result = None

        self._count = 0
        self._submeshes = []
        self._textures = {}  # texture_path -> QOpenGLTexture

        # 轨道相机
        self._az = 35.0
        self._el = 18.0
        self._dist = 5.0
        self._radius = 1.0
        self._target = QtGui.QVector3D(0.0, 0.0, 0.0)
        self._bbox_min = None
        self._bbox_max = None
        self._last_pos = None
        self._last_btn = None

        self.setFocusPolicy(QtCore.Qt.WheelFocus)

    # ----------------------------------------------------------- 网格接口
    def setMesh(self, interleaved_bytes, submeshes, images, bbox_min, bbox_max):
        self._anim_timer.stop()
        self._is_animated = False
        self._pending_skin_bytes = None
        self._pending_palettes = None
        self._pending_bytes = interleaved_bytes
        self._pending_count = sum(s.count for s in submeshes) if submeshes else 0
        self._pending_submeshes = submeshes or []
        self._pending_images = images or {}
        self._dirty = True
        self._fitTo(bbox_min, bbox_max)
        self.update()

    def setAnimatedMesh(self, skin_bytes, submeshes, images, palettes,
                        frame_count, bone_count, fps, bbox_min, bbox_max):
        """设置带动画的蒙皮网格,自动循环播放(frame_count>1 时启动定时器)。"""
        self._is_animated = True
        self._pending_skin_bytes = skin_bytes
        self._pending_submeshes = submeshes or []
        self._pending_images = images or {}
        self._pending_palettes = palettes or []
        self._pending_frame_count = frame_count
        self._pending_bone_count = bone_count
        self._fps = fps if fps and fps > 0 else 30.0
        self._cur_frame = 0
        # 静态缓冲不再使用
        self._pending_bytes = None
        self._dirty = True
        self._fitTo(bbox_min, bbox_max)
        interval = int(round(1000.0 / max(1.0, min(120.0, self._fps))))
        self._anim_timer.stop()
        if frame_count and frame_count > 1:
            self._anim_timer.start(max(1, interval))
        self.update()

    def clearMesh(self):
        self._anim_timer.stop()
        self._is_animated = False
        self._pending_result = None
        self._pending_bytes = None
        self._pending_count = 0
        self._pending_submeshes = []
        self._pending_images = {}
        self._pending_skin_bytes = None
        self._pending_palettes = None
        self._bbox_min = None
        self._bbox_max = None
        self._clearGroundGrid()
        self._dirty = True
        self.update()

    def showResult(self, md, anim, images):
        """收到解析结果:有动画且蒙皮可用则播放动画,否则静态。初始化未完成时暂存,
        待 initializeGL 后决策(此时 _skin_supported/_max_bones 才就绪)。"""
        self._pending_result = (md, anim, images)
        self._applyResult()

    def _applyResult(self):
        if self._pending_result is None or not self._gl_inited:
            return
        md, anim, images = self._pending_result
        self._pending_result = None
        if (anim is not None and self._skin_supported
                and 0 < anim.bone_count <= self._max_bones):
            print("[PreviewGL] applyResult: animated mesh, frames=%d bones=%d"
                  % (anim.frame_count, anim.bone_count))
            self.setAnimatedMesh(anim.interleaved, anim.submeshes, images, anim.palettes,
                                 anim.frame_count, anim.bone_count, anim.fps,
                                 anim.bbox_min, anim.bbox_max)
        elif md is not None:
            print("[PreviewGL] applyResult: static mesh (anim=%s skin=%s bone_count=%d max_bones=%d)"
                  % (anim is not None, self._skin_supported,
                     getattr(anim, 'bone_count', 0), self._max_bones))
            self.setMesh(md.interleaved, md.submeshes, images, md.bbox_min, md.bbox_max)
        # 否则(动画不支持且无静态回退)保持当前显示不变

    def _advanceFrame(self):
        if not self._is_animated or self._frame_count <= 1:
            return
        self._cur_frame = (self._cur_frame + 1) % self._frame_count
        self.update()

    def _fitTo(self, bbox_min, bbox_max):
        """保存模型包围盒，并把轨道相机恢复到能完整显示模型的位置。"""
        try:
            bbox_min = tuple(float(v) for v in bbox_min)
            bbox_max = tuple(float(v) for v in bbox_max)
            valid = len(bbox_min) == 3 and len(bbox_max) == 3
            valid = valid and all(math.isfinite(v) for v in bbox_min + bbox_max)
            valid = valid and all(bbox_max[i] >= bbox_min[i] for i in range(3))
        except (TypeError, ValueError, OverflowError):
            valid = False

        if not valid:
            # 不让损坏 FBX 的 NaN/Inf 包围盒继续污染投影矩阵；这种文件仍可能无法显示，
            # 但视口和之后加载的正常资产不会一起变成空白。
            self._bbox_min = None
            self._bbox_max = None
            self._target = QtGui.QVector3D(0.0, 0.0, 0.0)
            self._radius = 1.0
            self._dist = self._fitDistance()
            self._az = 35.0
            self._el = 18.0
            self._clearGroundGrid()
            return False

        self._bbox_min = bbox_min
        self._bbox_max = bbox_max
        cx = (bbox_min[0] + bbox_max[0]) * 0.5
        cy = (bbox_min[1] + bbox_max[1]) * 0.5
        cz = (bbox_min[2] + bbox_max[2]) * 0.5
        self._target = QtGui.QVector3D(cx, cy, cz)
        dx = bbox_max[0] - bbox_min[0]
        dy = bbox_max[1] - bbox_min[1]
        dz = bbox_max[2] - bbox_min[2]
        r = 0.5 * math.sqrt(dx * dx + dy * dy + dz * dz)
        self._radius = r if r > 1e-6 else 1.0
        self._prepareGroundGrid(bbox_min, bbox_max)
        self._dist = self._fitDistance()
        self._az = 35.0
        self._el = 18.0
        return True

    def _fitDistance(self):
        """按当前宽高取较小视场角，避免窄预览区把模型裁到画面外。"""
        h = float(max(1, self.height()))
        aspect = max(1e-4, float(max(1, self.width())) / h)
        half_v = math.radians(22.5)
        half_h = math.atan(math.tan(half_v) * aspect)
        half_fov = max(math.radians(1.0), min(half_v, half_h))
        return self._radius / math.sin(half_fov) * 1.2

    def centerDisplay(self):
        """重新框选当前模型。供右键菜单和双击操作共用。"""
        if self._bbox_min is None or self._bbox_max is None:
            return False
        fitted = self._fitTo(self._bbox_min, self._bbox_max)
        self.update()
        return fitted

    def canCenterDisplay(self):
        return self._bbox_min is not None and self._bbox_max is not None

    # ----------------------------------------------------------- 地面网格
    def _clearGroundGrid(self):
        self._grid_bytes = None
        self._grid_minor_count = 0
        self._grid_major_first = 0
        self._grid_major_count = 0
        self._grid_signature = None
        self._grid_dirty = True

    def _prepareGroundGrid(self, bbox_min, bbox_max):
        """按模型包围盒生成 20×20 的有限 XZ 网格，CPU 数据只在模型变化时更新。"""
        signature = tuple(bbox_min) + tuple(bbox_max)
        if signature == self._grid_signature and self._grid_bytes:
            return

        cx = (bbox_min[0] + bbox_max[0]) * 0.5
        cz = (bbox_min[2] + bbox_max[2]) * 0.5
        half_extent = max(self._radius * 2.0, 1e-3)
        step = half_extent / 10.0
        # 稍低于包围盒底面，避免脚底或道具底面与网格发生深度闪烁。
        ground_y = bbox_min[1] - max(self._radius * 0.002, 1e-5)

        minor = []
        major = []
        for index in range(-10, 11):
            target = major if index % 5 == 0 else minor
            x = cx + index * step
            z = cz + index * step
            target.extend((x, ground_y, cz - half_extent,
                           x, ground_y, cz + half_extent))
            target.extend((cx - half_extent, ground_y, z,
                           cx + half_extent, ground_y, z))

        minor_count = len(minor) // 3
        values = array.array('f', minor + major)
        self._grid_bytes = values.tobytes()
        self._grid_minor_count = minor_count
        self._grid_major_first = minor_count
        self._grid_major_count = len(major) // 3
        self._grid_signature = signature
        self._grid_dirty = True

    # ----------------------------------------------------------- GL 生命周期
    def initializeGL(self):
        self._init_failed = False
        try:
            self._gl = self.context().functions()
            self._gl.initializeOpenGLFunctions()

            # 上下文销毁前(关面板/切项目/退出程序)在其仍为当前时释放 GL 资源,
            # 否则 QOpenGLBuffer/QOpenGLTexture 析构会无当前上下文 -> 告警 + GPU 泄漏。
            self.context().aboutToBeDestroyed.connect(
                self._cleanupGL, QtCore.Qt.DirectConnection)

            self._program = QtOpenGL.QOpenGLShaderProgram(self)
            # strip()：#version 必须是源码首行(部分驱动严格)
            ok = self._program.addShaderFromSourceCode(
                QtOpenGL.QOpenGLShader.Vertex, _VERT_SHADER.strip())
            ok = self._program.addShaderFromSourceCode(
                QtOpenGL.QOpenGLShader.Fragment, _FRAG_SHADER.strip()) and ok
            ok = self._program.link() and ok
            if not ok:
                raise RuntimeError("shader link failed: %s" % self._program.log())

            self._a_pos = self._program.attributeLocation("a_pos")
            self._a_nrm = self._program.attributeLocation("a_nrm")
            self._a_uv = self._program.attributeLocation("a_uv")
            self._u_mvp = self._program.uniformLocation("u_mvp")
            self._u_light = self._program.uniformLocation("u_lightDir")
            self._u_base = self._program.uniformLocation("u_baseColor")
            self._u_useTex = self._program.uniformLocation("u_useTex")
            self._u_tex = self._program.uniformLocation("u_tex")
        except Exception:
            self._init_failed = True
            self.initFailed.emit()
            return

        # 网格/蒙皮程序失败都不影响静态模型预览。
        self._initGridProgram()
        self._initSkinProgram()

        # 初始化完成,应用初始化前可能已到达的解析结果
        self._gl_inited = True
        self._applyResult()
        # QOpenGLWidget 在停靠/重排时可能重建上下文。通知容器从 CPU 缓存重新提交
        # 当前模型，因为旧上下文中的 VBO/纹理已经失效。
        self.contextReady.emit()

    def _initGridProgram(self):
        """创建地面网格的极简纯色 shader；失败时仅关闭网格，不影响 FBX。"""
        try:
            prog = QtOpenGL.QOpenGLShaderProgram(self)
            ok = prog.addShaderFromSourceCode(
                QtOpenGL.QOpenGLShader.Vertex, _GRID_VERT_SHADER.strip())
            ok = prog.addShaderFromSourceCode(
                QtOpenGL.QOpenGLShader.Fragment, _GRID_FRAG_SHADER.strip()) and ok
            ok = prog.link() and ok
            if not ok:
                raise RuntimeError("grid shader link failed: %s" % prog.log())
            self._grid_program = prog
            self._ga_pos = prog.attributeLocation("a_pos")
            self._gu_mvp = prog.uniformLocation("u_mvp")
            self._gu_color = prog.uniformLocation("u_color")
            self._grid_dirty = bool(self._grid_bytes)
        except Exception as e:
            self._grid_program = None
            print("[PreviewGL] ground grid disabled: %r" % (e,))

    def _initSkinProgram(self):
        """构建蒙皮(动画)程序。每骨 3×vec4,按可用顶点 uniform 上限选 MAX_BONES,
        链接失败逐级回退;全失败置 _skin_supported=False(动画资产回退静态)。"""
        try:
            maxv = 0
            try:
                # PySide2 下 glGetIntegerv 需要传 array 作为输出参数
                import array as _array
                v = _array.array('i', [0])
                self._gl.glGetIntegerv(_GL_MAX_VERTEX_UNIFORM_VECTORS, v)
                maxv = int(v[0])
            except Exception:
                maxv = 0
            # 每骨 3 vec4,留 16 vec4 给 u_mvp 等
            budget = max(16, min(400, (maxv - 16) // 3)) if maxv > 0 else 256
            # 从大到小尝试,确保优先使用 GPU 实际支持的最大值
            candidates = sorted([budget, 400, 336, 256, 200, 128, 64], reverse=True)

            prog = None
            chosen = 0
            for mb in candidates:
                if mb < 1:
                    continue
                p = QtOpenGL.QOpenGLShaderProgram(self)
                okv = p.addShaderFromSourceCode(
                    QtOpenGL.QOpenGLShader.Vertex, (_SKIN_VERT_SHADER % (3 * mb)).strip())
                okf = p.addShaderFromSourceCode(
                    QtOpenGL.QOpenGLShader.Fragment, _FRAG_SHADER.strip())
                if okv and okf and p.link():
                    prog = p
                    chosen = mb
                    break
            if prog is None:
                self._skin_supported = False
                return

            self._skin_program = prog
            self._max_bones = chosen
            self._sa_pos = prog.attributeLocation("a_pos")
            self._sa_nrm = prog.attributeLocation("a_nrm")
            self._sa_uv = prog.attributeLocation("a_uv")
            self._sa_bidx = prog.attributeLocation("a_boneIdx")
            self._sa_bw = prog.attributeLocation("a_boneWeight")
            self._su_mvp = prog.uniformLocation("u_mvp")
            self._su_light = prog.uniformLocation("u_lightDir")
            self._su_base = prog.uniformLocation("u_baseColor")
            self._su_useTex = prog.uniformLocation("u_useTex")
            self._su_tex = prog.uniformLocation("u_tex")
            # u_bones 是 vec4[3*MAX_BONES];逐元素 location(回退用)+ 数组基址
            self._su_bones0 = prog.uniformLocation("u_bones")
            self._su_bone_locs = [prog.uniformLocation("u_bones[%d]" % i)
                                  for i in range(3 * chosen)]
            self._skin_array_ok = True
            self._skin_supported = True
            print("[PreviewGL] skin program OK, max_bones=%d" % chosen)
        except Exception as e:
            self._skin_supported = False
            print("[PreviewGL] skin program failed: %r" % (e,))

    def _cleanupGL(self):
        """GL 上下文销毁前的清理:makeCurrent 后销毁 VBO/纹理,再 doneCurrent。
        由 context().aboutToBeDestroyed 触发(DirectConnection,同线程同步执行)。
        """
        if self._gl is None:
            return
        self._anim_timer.stop()
        self.makeCurrent()
        try:
            for t in self._textures.values():
                try:
                    t.destroy()
                except Exception:
                    pass
            self._textures = {}
            if self._vbo is not None:
                try:
                    self._vbo.destroy()
                except Exception:
                    pass
                self._vbo = None
            if self._skin_vbo is not None:
                try:
                    self._skin_vbo.destroy()
                except Exception:
                    pass
                self._skin_vbo = None
            if self._grid_vbo is not None:
                try:
                    self._grid_vbo.destroy()
                except Exception:
                    pass
                self._grid_vbo = None
        finally:
            self.doneCurrent()

        # 这些对象和状态都属于刚刚销毁的上下文，不能在下一次 initializeGL 后复用。
        # _pending_result 刻意保留：若解析结果在上下文重建期间到达，新上下文可直接应用。
        self._gl_inited = False
        self._gl = None
        self._program = None
        self._skin_program = None
        self._grid_program = None
        self._ga_pos = self._gu_mvp = self._gu_color = -1
        # 网格 CPU 数据极小，保留下来供新的 GL 上下文重新上传。
        self._grid_dirty = bool(self._grid_bytes)
        self._skin_supported = False
        self._max_bones = 0
        self._pending_bytes = None
        self._pending_skin_bytes = None
        self._pending_images = {}
        self._dirty = False
        self._is_animated = False
        self._count = 0
        self._submeshes = []
        self._palettes = None
        self._frame_count = 0
        self._bone_count = 0

    def resizeGL(self, w, h):
        if self._gl:
            self._gl.glViewport(0, 0, w, max(1, h))

    def paintGL(self):
        if self._init_failed or not self._program:
            return
        # PySide2 下 _gl(QOpenGLFunctions) 可能被提前释放,防御性检查
        try:
            self._gl.glGetError()
        except Exception:
            return
        if not self._gl:
            return

        bg = 38.0 / 255.0
        self._gl.glClearColor(bg, bg, bg + 3.0 / 255.0, 1.0)
        self._gl.glClear(_GL_COLOR_BUFFER_BIT | _GL_DEPTH_BUFFER_BIT)
        self._gl.glEnable(_GL_DEPTH_TEST)

        if self._dirty:
            self._uploadPending()
        if self._grid_dirty:
            self._uploadGroundGrid()

        # 先画地面再画模型；共用深度缓冲，模型会自然遮挡后方的网格线。
        self._paintGroundGrid()

        if self._is_animated:
            self._paintAnimated()
        else:
            self._paintStatic()

    def _paintGroundGrid(self):
        if (self._grid_program is None or self._grid_vbo is None
                or self._grid_major_count <= 0):
            return
        eye, _light = self._cameraVectors()
        prog = self._grid_program
        prog.bind()
        prog.setUniformValue(self._gu_mvp, self._mvp(eye))
        self._grid_vbo.bind()
        prog.enableAttributeArray(self._ga_pos)
        prog.setAttributeBuffer(self._ga_pos, _GL_FLOAT, 0, 3, _GRID_STRIDE)

        if self._grid_minor_count > 0:
            prog.setUniformValue(
                self._gu_color, QtGui.QVector3D(0.255, 0.265, 0.285))
            self._gl.glDrawArrays(_GL_LINES, 0, self._grid_minor_count)
        prog.setUniformValue(
            self._gu_color, QtGui.QVector3D(0.38, 0.395, 0.42))
        self._gl.glDrawArrays(
            _GL_LINES, self._grid_major_first, self._grid_major_count)

        prog.disableAttributeArray(self._ga_pos)
        self._grid_vbo.release()
        prog.release()

    def _paintStatic(self):
        if self._count <= 0 or self._vbo is None:
            return
        eye, light = self._cameraVectors()
        mvp = self._mvp(eye)
        prog = self._program
        prog.bind()
        prog.setUniformValue(self._u_mvp, mvp)
        prog.setUniformValue(self._u_light, light)
        prog.setUniformValue(self._u_tex, 0)

        self._vbo.bind()
        prog.enableAttributeArray(self._a_pos)
        prog.setAttributeBuffer(self._a_pos, _GL_FLOAT, 0, 3, _STRIDE)
        prog.enableAttributeArray(self._a_nrm)
        prog.setAttributeBuffer(self._a_nrm, _GL_FLOAT, 3 * 4, 3, _STRIDE)
        if self._a_uv >= 0:
            prog.enableAttributeArray(self._a_uv)
            prog.setAttributeBuffer(self._a_uv, _GL_FLOAT, 6 * 4, 2, _STRIDE)

        self._drawSubmeshes(prog, self._u_useTex, self._u_base)

        prog.disableAttributeArray(self._a_pos)
        prog.disableAttributeArray(self._a_nrm)
        if self._a_uv >= 0:
            prog.disableAttributeArray(self._a_uv)
        self._vbo.release()
        prog.release()

    def _paintAnimated(self):
        if (not self._skin_supported or self._skin_program is None
                or self._count <= 0 or self._skin_vbo is None
                or not self._palettes or self._bone_count <= 0):
            return
        eye, light = self._cameraVectors()
        mvp = self._mvp(eye)
        prog = self._skin_program
        prog.bind()
        prog.setUniformValue(self._su_mvp, mvp)
        prog.setUniformValue(self._su_light, light)
        prog.setUniformValue(self._su_tex, 0)
        self._setBonePalette()

        self._skin_vbo.bind()
        prog.enableAttributeArray(self._sa_pos)
        prog.setAttributeBuffer(self._sa_pos, _GL_FLOAT, 0, 3, _SKIN_STRIDE)
        prog.enableAttributeArray(self._sa_nrm)
        prog.setAttributeBuffer(self._sa_nrm, _GL_FLOAT, 3 * 4, 3, _SKIN_STRIDE)
        if self._sa_uv >= 0:
            prog.enableAttributeArray(self._sa_uv)
            prog.setAttributeBuffer(self._sa_uv, _GL_FLOAT, 6 * 4, 2, _SKIN_STRIDE)
        prog.enableAttributeArray(self._sa_bidx)
        prog.setAttributeBuffer(self._sa_bidx, _GL_FLOAT, 8 * 4, 4, _SKIN_STRIDE)
        prog.enableAttributeArray(self._sa_bw)
        prog.setAttributeBuffer(self._sa_bw, _GL_FLOAT, 12 * 4, 4, _SKIN_STRIDE)

        self._drawSubmeshes(prog, self._su_useTex, self._su_base)

        prog.disableAttributeArray(self._sa_pos)
        prog.disableAttributeArray(self._sa_nrm)
        if self._sa_uv >= 0:
            prog.disableAttributeArray(self._sa_uv)
        prog.disableAttributeArray(self._sa_bidx)
        prog.disableAttributeArray(self._sa_bw)
        self._skin_vbo.release()
        prog.release()

    def _setBonePalette(self):
        """把当前帧的骨骼调色板写入 u_bones[]。palette 为每骨 12 float(3 行,行主序),
        对应 3 个 vec4(u_bones[3*i+0/1/2]);着色器用 dot(row, vec4(pos,1)) 应用。"""
        frame = self._cur_frame
        if frame < 0 or frame >= len(self._palettes):
            frame = 0
        pal = array.array('f')
        pal.frombytes(self._palettes[frame])
        n = min(self._bone_count, self._max_bones)
        nvec = n * 3
        vecs = []
        for i in range(nvec):
            o = i * 4
            vecs.append(QtGui.QVector4D(pal[o], pal[o + 1], pal[o + 2], pal[o + 3]))
        prog = self._skin_program
        if self._skin_array_ok and self._su_bones0 >= 0:
            try:
                prog.setUniformValueArray(self._su_bones0, vecs)
                return
            except Exception:
                self._skin_array_ok = False
        for i in range(min(nvec, len(self._su_bone_locs))):
            prog.setUniformValue(self._su_bone_locs[i], vecs[i])

    def _drawSubmeshes(self, prog, u_useTex, u_base):
        for sm in self._submeshes:
            tex = self._textures.get(sm.texture) if sm.texture else None
            if tex is not None:
                prog.setUniformValue(u_useTex, 1)
                tex.bind(0)
            else:
                prog.setUniformValue(u_useTex, 0)
                c = sm.color or (0.78, 0.78, 0.80)
                prog.setUniformValue(u_base, QtGui.QVector3D(c[0], c[1], c[2]))
            self._gl.glDrawArrays(_GL_TRIANGLES, sm.first, sm.count)
            if tex is not None:
                tex.release(0)

    def _uploadPending(self):
        self._dirty = False

        # 销毁旧纹理(此处 GL 上下文为当前)
        for t in self._textures.values():
            try:
                t.destroy()
            except Exception:
                pass
        self._textures = {}

        if self._is_animated:
            self._uploadSkinPending()
        else:
            self._uploadStaticPending()

    def _uploadGroundGrid(self):
        """将每个模型只生成一次的微型网格数据提交到静态 VBO。"""
        self._grid_dirty = False
        if self._grid_program is None or not self._grid_bytes:
            return
        if self._grid_vbo is None:
            self._grid_vbo = QtOpenGL.QOpenGLBuffer(QtOpenGL.QOpenGLBuffer.VertexBuffer)
            self._grid_vbo.create()
        self._grid_vbo.bind()
        self._grid_vbo.allocate(self._grid_bytes, len(self._grid_bytes))
        self._grid_vbo.release()

    def _uploadTextures(self):
        """按 submesh 的贴图路径,从 _pending_images 创建 GL 纹理(GL 上下文须为当前)。"""
        for sm in self._submeshes:
            tp = sm.texture
            if tp and tp in self._pending_images and tp not in self._textures:
                try:
                    tex = QtOpenGL.QOpenGLTexture(self._pending_images[tp])
                    tex.setMinificationFilter(QtOpenGL.QOpenGLTexture.LinearMipMapLinear)
                    tex.setMagnificationFilter(QtOpenGL.QOpenGLTexture.Linear)
                    tex.setWrapMode(QtOpenGL.QOpenGLTexture.Repeat)
                    self._textures[tp] = tex
                except Exception:
                    pass
        self._pending_images = {}

    def _uploadStaticPending(self):
        if not self._pending_bytes or self._pending_count <= 0:
            self._count = 0
            self._submeshes = []
            return

        if self._vbo is None:
            self._vbo = QtOpenGL.QOpenGLBuffer(QtOpenGL.QOpenGLBuffer.VertexBuffer)
            self._vbo.create()
        self._vbo.bind()
        self._vbo.allocate(self._pending_bytes, len(self._pending_bytes))
        self._vbo.release()

        self._count = self._pending_count
        self._submeshes = self._pending_submeshes
        self._uploadTextures()
        self._pending_bytes = None  # 已传 GPU,释放内存副本

    def _uploadSkinPending(self):
        if not self._pending_skin_bytes:
            self._count = 0
            self._submeshes = []
            return

        if self._skin_vbo is None:
            self._skin_vbo = QtOpenGL.QOpenGLBuffer(QtOpenGL.QOpenGLBuffer.VertexBuffer)
            self._skin_vbo.create()
        self._skin_vbo.bind()
        self._skin_vbo.allocate(self._pending_skin_bytes, len(self._pending_skin_bytes))
        self._skin_vbo.release()

        self._submeshes = self._pending_submeshes
        self._count = sum(s.count for s in self._submeshes) if self._submeshes else 0
        self._palettes = self._pending_palettes
        self._frame_count = self._pending_frame_count
        self._bone_count = self._pending_bone_count
        if self._frame_count > 0:
            self._cur_frame = self._cur_frame % self._frame_count
        else:
            self._cur_frame = 0
        self._uploadTextures()
        self._pending_skin_bytes = None  # 已传 GPU,释放内存副本

    # ----------------------------------------------------------- 相机
    def _cameraVectors(self):
        ar = math.radians(self._az)
        er = math.radians(self._el)
        ce = math.cos(er)
        d = QtGui.QVector3D(ce * math.sin(ar), math.sin(er), ce * math.cos(ar))
        eye = self._target + d * self._dist
        light = (self._target - eye)
        if light.length() > 1e-6:
            light.normalize()
        return eye, light

    def _mvp(self, eye):
        w = float(self.width())
        h = float(max(1, self.height()))
        # 地面网格半径约为模型半径的 2 倍，裁剪范围需要覆盖前后角落。
        near = max(self._dist - self._radius * 4.0, self._radius * 0.01, 0.001)
        far = self._dist + self._radius * 4.0 + 1.0
        proj = QtGui.QMatrix4x4()
        proj.perspective(45.0, w / h, near, far)
        view = QtGui.QMatrix4x4()
        view.lookAt(eye, self._target, QtGui.QVector3D(0.0, 1.0, 0.0))
        return proj * view

    def _basis(self):
        ar = math.radians(self._az)
        er = math.radians(self._el)
        ce = math.cos(er)
        fwd = QtGui.QVector3D(-ce * math.sin(ar), -math.sin(er), -ce * math.cos(ar))
        right = QtGui.QVector3D.crossProduct(fwd, QtGui.QVector3D(0.0, 1.0, 0.0))
        if right.length() > 1e-6:
            right.normalize()
        up = QtGui.QVector3D.crossProduct(right, fwd)
        if up.length() > 1e-6:
            up.normalize()
        return right, up

    # ----------------------------------------------------------- 鼠标交互
    def mousePressEvent(self, e):
        self._last_pos = e.position().toPoint()
        self._last_btn = e.button()
        self.setFocus()

    def mouseMoveEvent(self, e):
        if self._last_pos is None:
            return
        dx = e.x() - self._last_pos.x()
        dy = e.y() - self._last_pos.y()
        self._last_pos = e.position().toPoint()

        mods = e.modifiers()
        pan = (self._last_btn == QtCore.Qt.MiddleButton) or \
              (self._last_btn == QtCore.Qt.LeftButton and (mods & QtCore.Qt.ShiftModifier))
        if pan:
            right, up = self._basis()
            scale = self._dist * 0.0015
            self._target = self._target - right * (dx * scale) + up * (dy * scale)
        elif self._last_btn == QtCore.Qt.LeftButton:
            self._az -= dx * 0.4
            self._el = max(-89.0, min(89.0, self._el + dy * 0.4))
        self.update()

    def mouseReleaseEvent(self, e):
        self._last_pos = None
        self._last_btn = None

    def wheelEvent(self, e):
        delta = e.angleDelta().y()
        if delta == 0:
            return
        factor = math.pow(0.9, delta / 120.0)
        self._dist = max(self._radius * 0.05, min(self._radius * 50.0, self._dist * factor))
        self.update()

    def mouseDoubleClickEvent(self, e):
        self.centerDisplay()
        e.accept()

    def contextMenuEvent(self, e):
        # 菜单由 PreviewGLWidget 统一创建，因为当前动作路径保存在容器层。
        self.contextMenuRequested.emit(e.globalPosition().toPoint())
        e.accept()


# --------------------------------------------------------------------------- 异步解析
class _ParseSignals(QtCore.QObject):
    done = QtCore.Signal(str, object, object, object)  # path, MeshData, AnimData|None, images
    failed = QtCore.Signal(str)


def _load_images(submeshes):
    """worker 线程加载贴图(QImage 非 GUI 对象可在子线程加载;竖直翻转以匹配 GL)。"""
    images = {}
    for sm in submeshes:
        tp = sm.texture
        if tp and tp not in images:
            img = QtGui.QImage(tp)
            if not img.isNull():
                images[tp] = img.mirrored(False, True)
    return images


class _ParseTask(QtCore.QRunnable):
    """缩略图静态预览:只读静态网格(want_anim=False,最快路径)。"""
    def __init__(self, path, signals):
        super(_ParseTask, self).__init__()
        self._path = path
        self._signals = signals

    def run(self):
        try:
            md, anim = fbxMesh.read(self._path, want_anim=False)
            axis = getattr(md, "axis_system", None)
            if axis is not None:
                print("[PreviewGL] FBX axis: %s -> %s" %
                      (self._path, axis.describe()))
            images = _load_images(md.submeshes)
            self._signals.done.emit(self._path, md, anim, images)
        except Exception:
            self._signals.failed.emit(self._path)


class _CombineSignals(QtCore.QObject):
    done = QtCore.Signal(str, str, object, object)  # rig, action, AnimData, images
    failed = QtCore.Signal(str, str)                # rig, action


class _CombineTask(QtCore.QRunnable):
    """动作预览:绑定文件蒙皮(可缓存) + 动作骨骼动画 -> 合成 AnimData。"""
    def __init__(self, rig_path, action_path, signals, skin_cache, skin_lock):
        super(_CombineTask, self).__init__()
        self._rig = rig_path
        self._action = action_path
        self._signals = signals
        self._skin_cache = skin_cache
        self._skin_lock = skin_lock

    def run(self):
        try:
            with self._skin_lock:
                entry = self._skin_cache.get(self._rig)
            try:
                mtime = os.path.getmtime(self._rig)
            except OSError:
                mtime = None
            skin = entry[1] if (entry and entry[0] == mtime) else None
            if skin is None:
                skin = fbxMesh.read_skin(self._rig)
                print("[PreviewGL] read_skin(%s) = %s" % (self._rig, skin is not None))
                if skin is not None:
                    with self._skin_lock:
                        self._skin_cache[self._rig] = (mtime, skin)
            if skin is None:
                self._signals.failed.emit(self._rig, self._action)
                return
            action = fbxMesh.read_action(self._action)
            print("[PreviewGL] read_action(%s) = %s" % (self._action, action is not None))
            if action is None:
                self._signals.failed.emit(self._rig, self._action)
                return

            rig_axis = getattr(skin, "axis_system", None)
            action_axis = getattr(action, "axis_system", None)
            print("[PreviewGL] FBX axes: rig=(%s) action=(%s)" % (
                rig_axis.describe() if rig_axis else "unknown",
                action_axis.describe() if action_axis else "unknown"))

            # ---- 诊断：比较绑定和动作的骨骼结构 ----
            rig_bones = set(skin.joint_name)
            act_bones = set(action.name_channels.keys())
            matched = rig_bones & act_bones
            unmatched_rig = rig_bones - act_bones
            unmatched_act = act_bones - rig_bones
            print("[PreviewGL] bone matching: rig=%d action=%d matched=%d"
                  % (len(rig_bones), len(act_bones), len(matched)))
            if unmatched_rig:
                print("[PreviewGL] unmatched rig bones: %s" % (list(sorted(unmatched_rig))[:20],))
            if unmatched_act:
                print("[PreviewGL] unmatched action bones: %s" % (list(sorted(unmatched_act))[:20],))

            diff_bones = []
            for nm in sorted(matched):
                j = skin.joint_name.index(nm)
                rig_comp = skin.joint_comp[j]
                act_node = action.name_node.get(nm)
                if act_node:
                    act_comp = fbxMesh._bone_components(act_node)
                    rig_pre = rig_comp.get("pre")
                    act_pre = act_comp.get("pre")
                    rig_order = rig_comp.get("order", 0)
                    act_order = act_comp.get("order", 0)
                    if rig_pre != act_pre or rig_order != act_order:
                        diff_bones.append((nm, rig_pre, act_pre, rig_order, act_order))
            if diff_bones:
                print("[PreviewGL] bone component diffs (name, rig_pre, act_pre, rig_order, act_order):")
                for db in diff_bones[:30]:
                    print("  %s" % (db,))
            # ---- 诊断结束 ----

            anim = fbxMesh.combine(skin, action)
            print("[PreviewGL] combine -> frames=%d bones=%d"
                  % (anim.frame_count, anim.bone_count))
            images = _load_images(anim.submeshes)
            self._signals.done.emit(self._rig, self._action, anim, images)
        except Exception as e:
            import traceback
            print("[PreviewGL] _CombineTask exception: %r" % (e,))
            traceback.print_exc()
            self._signals.failed.emit(self._rig, self._action)


# --------------------------------------------------------------------------- 2D Icon 交互预览
class _IconPreviewView(QtWidgets.QWidget):
    """保持比例显示 Icon，并支持滚轮缩放、中键平移。"""

    _MIN_ZOOM = 0.1
    _MAX_ZOOM = 20.0

    def __init__(self, parent=None):
        super(_IconPreviewView, self).__init__(parent)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self._pixmap = None
        self._pixmap_key = None
        self._zoom = 1.0
        self._offset = QtCore.QPointF(0.0, 0.0)
        self._pan_pos = None

    def setPixmap(self, pixmap):
        """新图片自动完整适配；重复提交同一图片时保留用户的缩放和平移。"""
        if pixmap is None or pixmap.isNull():
            self.clear()
            return
        key = pixmap.cacheKey()
        changed = key != self._pixmap_key
        self._pixmap = pixmap
        self._pixmap_key = key
        if changed:
            self.resetView()
        else:
            self.update()

    def clear(self):
        self._pixmap = None
        self._pixmap_key = None
        self.resetView()

    def resetView(self):
        self._zoom = 1.0
        self._offset = QtCore.QPointF(0.0, 0.0)
        self.update()

    def _displaySize(self, zoom=None):
        if self._pixmap is None or self._pixmap.isNull():
            return QtCore.QSizeF()
        source_w = float(max(1, self._pixmap.width()))
        source_h = float(max(1, self._pixmap.height()))
        fit = min(float(max(1, self.width())) / source_w,
                  float(max(1, self.height())) / source_h)
        value = self._zoom if zoom is None else zoom
        return QtCore.QSizeF(source_w * fit * value, source_h * fit * value)

    def paintEvent(self, event):
        super(_IconPreviewView, self).paintEvent(event)
        if self._pixmap is None or self._pixmap.isNull():
            return
        size = self._displaySize()
        center = QtCore.QPointF(self.width() * 0.5, self.height() * 0.5) + self._offset
        target = QtCore.QRectF(center.x() - size.width() * 0.5,
                              center.y() - size.height() * 0.5,
                              size.width(), size.height())
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(target, self._pixmap, QtCore.QRectF(self._pixmap.rect()))
        painter.end()

    def wheelEvent(self, event):
        if self._pixmap is None or self._pixmap.isNull():
            super(_IconPreviewView, self).wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if not delta:
            event.ignore()
            return

        old_zoom = self._zoom
        new_zoom = old_zoom * math.pow(1.15, float(delta) / 120.0)
        new_zoom = max(self._MIN_ZOOM, min(self._MAX_ZOOM, new_zoom))
        if abs(new_zoom - old_zoom) < 1e-8:
            event.accept()
            return

        # 缩放前后保持鼠标指向的图片位置不动，便于观察局部细节。
        anchor = QtCore.QPointF(event.position().toPoint())
        widget_center = QtCore.QPointF(self.width() * 0.5, self.height() * 0.5)
        old_center = widget_center + self._offset
        ratio = new_zoom / old_zoom
        new_center = anchor - (anchor - old_center) * ratio
        self._offset = new_center - widget_center
        self._zoom = new_zoom
        self.update()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton and self._pixmap is not None:
            self._pan_pos = event.position().toPoint()
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            event.accept()
            return
        super(_IconPreviewView, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_pos is not None and event.buttons() & QtCore.Qt.MiddleButton:
            delta = event.position().toPoint() - self._pan_pos
            self._offset += QtCore.QPointF(delta)
            self._pan_pos = event.position().toPoint()
            self.update()
            event.accept()
            return
        super(_IconPreviewView, self).mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton and self._pan_pos is not None:
            self._pan_pos = None
            self.unsetCursor()
            event.accept()
            return
        super(_IconPreviewView, self).mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and self._pixmap is not None:
            self.resetView()
            event.accept()
            return
        super(_IconPreviewView, self).mouseDoubleClickEvent(event)


# --------------------------------------------------------------------------- 容器控件
class PreviewGLWidget(QtWidgets.QWidget):
    """drop-in 替换 PreviewWidget 的 FBX 三维预览控件。"""

    _CACHE_CAP = 8
    _PAGE_FALLBACK = 0
    _PAGE_GL = 1
    _PAGE_LOADING = 2

    _GRADIENT_BG = (
        "background-color: qradialgradient(spread:pad, cx:0.5, cy:0.5, radius:0.5, "
        "fx:0.5, fy:0.5, stop:0 rgba(35, 36, 39, 100), stop:1 rgba(35, 36, 39, 255));"
    )

    def __init__(self, isPlayer=True):
        super(PreviewGLWidget, self).__init__()

        self.isPlayer = isPlayer
        self._preview_mode = "3d"       # 右下角按钮切换 3D FBX / 2D Icon
        self._name = None
        self._fallback_icon = ""
        self._fallback_pixmap = None
        self._fallback_pixmap_path = ""
        self._current_fbx = None        # 当前绑定文件 rig(去重 + 防过期)
        self._current_action = None     # 当前播放的动作路径(None=静态)
        self._selected_action = None    # 动作列表最后选中的路径(解析失败时也保留)
        self._base_name = None          # 数据库资产名；皮肤切换时用于组成完整显示名
        self._base_zh_name = None
        self._surface_variants = []     # [(surface, icon, fbx), ...]
        self._surface_index = -1
        self._surface_request_serial = 0
        self._surface_buttons = {}
        self._surface_loader = SurfaceVariantLoader.instance()
        self._thumbnail_loader = ThumbnailLoader.instance()
        self._thumbnail_protection_key = "PreviewGLSurface:%d" % id(self)
        protection_key = self._thumbnail_protection_key
        thumbnail_loader = self._thumbnail_loader
        self.destroyed.connect(
            lambda *_args: thumbnail_loader.clearProtectedPaths(protection_key))
        self._gl_failed = not _HAS_QOPENGL
        self._gl_generation = 0         # workspaceControl 重开时会替换失效的 GL 子控件
        self._cache = {}                # rig path -> (mtime, MeshData, AnimData|None, images)
        self._cache_order = []
        self._anim_cache = {}           # (rig, action) -> (AnimData, images)
        self._anim_order = []
        self._skin_cache = {}           # rig path -> (mtime, SkinData)  (worker 线程共享)
        self._skin_lock = threading.Lock()

        self._buildUI()

        self._pool = QtCore.QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._signals = _ParseSignals()
        self._signals.done.connect(self._onParsed)
        self._signals.failed.connect(self._onParseFailed)
        self._csignals = _CombineSignals()
        self._csignals.done.connect(self._onCombined)
        self._csignals.failed.connect(self._onCombineFailed)

        self._load_timer = QtCore.QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.setInterval(200)
        self._load_timer.timeout.connect(self._loadPending)
        self._pending_fbx = None
        self._pending_icon = None

    # ------------------------------------------------------------------ UI
    def _buildUI(self):
        vLayout = QtWidgets.QVBoxLayout(self)
        vLayout.setContentsMargins(0, 0, 0, 0)
        vLayout.setSpacing(0)

        self._stack = QtWidgets.QStackedWidget(self)

        # page0: 回退图片
        self._image_label = _IconPreviewView()
        self._image_label.setStyleSheet(self._GRADIENT_BG)
        self._stack.addWidget(self._image_label)            # index 0

        # page1: GL 视口(仅在 QOpenGLWidget 可用时)
        self._gl_view = None
        if _HAS_QOPENGL:
            self._gl_view = self._newGLView()
            self._stack.addWidget(self._gl_view)            # index 1
        else:
            self._stack.addWidget(QtWidgets.QWidget())      # 占位,保持索引一致

        # page2: 加载中
        self._loading_label = QtWidgets.QLabel(u"加载中…")
        self._loading_label.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignHCenter)
        self._loading_label.setStyleSheet(
            self._GRADIENT_BG + "color: rgb(180, 180, 180);")
        self._loading_label.setFont(QtGui.QFont(u"Microsoft YaHei UI", 11))
        self._stack.addWidget(self._loading_label)          # index 2

        vLayout.addWidget(self._stack)

        # 多皮肤切换条浮在预览画面底部，不再单独占一行高度。只有发现至少两套
        # Icon+FBX 配对时才显示；按钮图异步加载，不在主线程同步读取网络图片。
        self._surface_bar = QtWidgets.QWidget(self._stack)
        self._surface_bar.setFixedHeight(50)
        self._surface_bar.setStyleSheet("background: transparent; border: none;")
        self._surface_layout = QtWidgets.QHBoxLayout(self._surface_bar)
        self._surface_layout.setContentsMargins(0, 4, 0, 4)
        self._surface_layout.setSpacing(12)
        self._surface_layout.setAlignment(QtCore.Qt.AlignCenter)
        self._surface_bar.hide()

        self.title_label = QtWidgets.QLabel(self)
        self.title_label.setStyleSheet(
            "color: rgb(150, 150, 150);background-color: rgb(29, 29, 29);")
        self.title_label.setFixedHeight(45)
        self.title_label.setFont(QtGui.QFont(u"Microsoft YaHei UI", 10))
        vLayout.addWidget(self.title_label)

        # 左右箭头覆盖在 FBX 预览区两侧，不占用模型视口宽度。
        icon_dir = os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(__file__))), "icon")
        self._surface_prev_btn = self._makeSurfaceArrow(
            os.path.join(icon_dir, "arrowSingleLeft.png"), -1, u"上一个皮肤")
        self._surface_next_btn = self._makeSurfaceArrow(
            os.path.join(icon_dir, "arrowSingleRight.png"), 1, u"下一个皮肤")

        # 右下角 2D/3D 切换。图标表示当前视图，tooltip 说明点击后的目标。
        self._preview_mode_btn = QtWidgets.QToolButton(self._stack)
        self._preview_mode_btn.setFixedSize(38, 38)
        self._preview_mode_btn.setIconSize(QtCore.QSize(30, 30))
        self._preview_mode_btn.setAutoRaise(True)
        self._preview_mode_btn.setStyleSheet(
            "QToolButton { background: rgba(20,20,20,125); border: 1px solid "
            "rgba(105,105,105,135); border-radius: 4px; }"
            "QToolButton:hover { background: rgba(82,133,166,155);"
            " border-color: rgba(150,190,215,190); }")
        self._preview_mode_btn.clicked.connect(self._togglePreviewMode)
        self._preview_mode_icons = {
            "3d": os.path.join(icon_dir, "am_perview3D.png"),
            "2d": os.path.join(icon_dir, "am_perview2D.png"),
        }
        self._updatePreviewModeButton()

        # QStackedWidget 每次切换“加载中/GL/Icon”都会把新页面 raise 到最上层，
        # 覆盖掉它的直接子控件。切页完成后的下一轮事件再把所有悬浮控件提回来。
        self._stack.currentChanged.connect(self._schedulePreviewOverlayRefresh)

    def _makeSurfaceArrow(self, icon_path, step, tooltip):
        button = QtWidgets.QToolButton(self._stack)
        button.setFixedSize(19, 36)
        button.setIconSize(QtCore.QSize(15, 27))
        button.setIcon(QtGui.QIcon(icon_path))
        button.setToolTip(tooltip)
        button.setAutoRaise(True)
        button.setStyleSheet(
            "QToolButton { background: rgba(20,20,20,75); border: none;"
            " border-radius: 4px; }"
            "QToolButton:hover { background: rgba(82,133,166,125); }")
        button.clicked.connect(lambda _checked=False, amount=step: self._stepSurface(amount))
        button.hide()
        return button

    def _newGLView(self):
        """创建并接好一个全新的 GL 视口。CPU 侧 FBX 缓存由外层控件持有。"""
        view = GLView(self)
        view.initFailed.connect(self._onGLFailed)
        view.contextMenuRequested.connect(self._showPreviewContextMenu)
        view.contextReady.connect(self._restoreCurrentPreview)
        self._gl_generation += 1
        return view

    def recoverAfterWorkspaceRestore(self):
        """AssetManager 的 workspaceControl 关闭后重开时恢复三维预览。

        Maya 会复用原来的 AssetManager Qt 对象，但停靠面板被关闭时，其内部
        QOpenGLWidget 的原生绘图表面/上下文可能已经失效，而且重开后不一定再次
        调用 initializeGL。仅 update 或重新提交 VBO 无法修复这种半失效状态。

        外层控件保存着解析后的 FBX、动作和贴图 CPU 缓存，所以这里只替换很小的
        GLView 子控件。新控件会得到全新上下文；contextReady 后再从缓存提交当前模型。
        """
        if not _HAS_QOPENGL or self._stack is None:
            return False

        old_view = self._gl_view
        old_page = self._stack.currentIndex()
        if old_view is not None:
            self._stack.removeWidget(old_view)
            old_view.hide()
            old_view.setParent(None)
            old_view.deleteLater()

        self._gl_failed = False
        self._gl_view = self._newGLView()
        self._stack.insertWidget(self._PAGE_GL, self._gl_view)
        print("[PreviewGL] workspace restored: recreated GL view (generation=%d)" %
              self._gl_generation)

        # showResult 在 initializeGL 之前调用是安全的：GLView 会把结果留在
        # _pending_result，等新上下文 ready 后再创建 VBO/纹理。
        restored = self._restoreCurrentPreview()
        if self._preview_mode == "2d":
            self._showFallback(self._fallback_icon)
        elif restored:
            self._stack.setCurrentWidget(self._gl_view)
        elif old_page == self._PAGE_LOADING:
            self._stack.setCurrentIndex(self._PAGE_LOADING)
        else:
            self._stack.setCurrentIndex(self._PAGE_FALLBACK)
        self._gl_view.update()
        return True

    def resizeEvent(self, e):
        # 不再锁定高度为正方形(原 Maya 版的 setMaximumHeight 上限),
        # 让预览随所在面板自由拉伸;回退图按当前尺寸保持比例重绘即可。
        if self._stack.currentIndex() == self._PAGE_FALLBACK and self._fallback_pixmap:
            self._applyFallbackPixmap()
        super(PreviewGLWidget, self).resizeEvent(e)
        self._positionPreviewOverlays()

    def showEvent(self, e):
        super(PreviewGLWidget, self).showEvent(e)
        self._schedulePreviewOverlayRefresh()

    def _schedulePreviewOverlayRefresh(self, *_args):
        """等 stacked page 完成层级与布局更新后，再恢复全部悬浮控件。"""
        QtCore.QTimer.singleShot(0, self._positionPreviewOverlays)

    def _positionPreviewOverlays(self):
        if not hasattr(self, '_surface_prev_btn'):
            return
        stack_w = self._stack.width()
        stack_h = self._stack.height()
        y = max(0, (stack_h - self._surface_prev_btn.height()) // 2)
        self._surface_prev_btn.move(8, y)
        self._surface_next_btn.move(
            max(8, stack_w - self._surface_next_btn.width() - 8), y)

        mode_x = max(4, stack_w - self._preview_mode_btn.width() - 8)
        mode_y = max(4, stack_h - self._preview_mode_btn.height() - 8)
        self._preview_mode_btn.move(mode_x, mode_y)

        if self._surface_bar.isVisible():
            # 为右下角模式按钮留出空间；皮肤数量较多时允许切换条使用剩余宽度。
            hint_w = self._surface_bar.sizeHint().width()
            max_w = max(40, stack_w - self._preview_mode_btn.width() - 24)
            bar_w = min(hint_w, max_w)
            bar_h = self._surface_bar.height()
            bar_x = max(4, (stack_w - bar_w) // 2)
            # 与标题栏之间留出明显空隙，使 Icon 看起来悬浮在预览内容之上。
            bar_y = max(4, stack_h - bar_h - 12)
            self._surface_bar.setGeometry(bar_x, bar_y, bar_w, bar_h)
            self._surface_bar.raise_()

        self._surface_prev_btn.raise_()
        self._surface_next_btn.raise_()
        self._preview_mode_btn.raise_()

    def _updatePreviewModeButton(self):
        if self._preview_mode == "3d":
            self._preview_mode_btn.setIcon(QtGui.QIcon(self._preview_mode_icons["3d"]))
            self._preview_mode_btn.setToolTip(u"切换到 Icon 图片预览")
        else:
            self._preview_mode_btn.setIcon(QtGui.QIcon(self._preview_mode_icons["2d"]))
            self._preview_mode_btn.setToolTip(u"切换到 FBX 三维预览")

    def _togglePreviewMode(self):
        self._preview_mode = "2d" if self._preview_mode == "3d" else "3d"
        self._updatePreviewModeButton()
        if self._preview_mode == "2d":
            self._showFallback(self._fallback_icon)
        else:
            self._showCurrent3DState()
        self._schedulePreviewOverlayRefresh()

    def _showCurrent3DState(self):
        """切回三维模式时，按缓存/加载状态恢复当前 FBX 或动作。"""
        if self._gl_failed or self._gl_view is None or not self._current_fbx:
            self._showFallback(self._fallback_icon)
            return
        if self._restoreCurrentPreview():
            self._stack.setCurrentIndex(self._PAGE_GL)
        else:
            self._stack.setCurrentIndex(self._PAGE_LOADING)

    def _showPageForCurrentMode(self, page):
        """后台解析照常完成，但 2D 模式下不抢走用户正在看的 Icon 页面。"""
        if self._preview_mode == "2d":
            self._showFallback(self._fallback_icon)
        else:
            self._stack.setCurrentIndex(page)

    def _showPreviewContextMenu(self, global_pos):
        """显示三维预览菜单；动作文件存在时允许在资源管理器中定位它。"""
        menu = QtWidgets.QMenu(self)
        center_action = menu.addAction(u"居中显示")
        center_action.setEnabled(
            self._gl_view is not None and self._gl_view.canCenterDisplay())
        menu.addSeparator()
        folder_action = menu.addAction(u"打开文件夹")
        action_path = os.path.normpath(self._selected_action) if self._selected_action else ""
        folder_action.setEnabled(bool(action_path) and (
            os.path.isfile(action_path) or os.path.isdir(os.path.dirname(action_path))))

        chosen = menu.exec(global_pos)
        if chosen == center_action and self._gl_view is not None:
            # 除了恢复相机，也重新提交一次 CPU 缓存；可修复上下文/VBO 已丢失但
            # 视口仍停留在空白 GL 页的情况。
            self._restoreCurrentPreview()
            self._gl_view.centerDisplay()
        elif chosen == folder_action:
            self._openCurrentActionFolder()

    def _restoreCurrentPreview(self):
        """从 CPU 缓存重新提交当前模型，供 GL 上下文重建和手动恢复使用。"""
        if self._gl_view is None or not self._current_fbx:
            return False

        if self._current_action:
            animated = self._animCacheGet(self._current_fbx, self._current_action)
            static = self._cacheGet(self._current_fbx)
            if animated is not None and static is not None:
                anim, images = animated
                md = static[0]
                self._gl_view.showResult(md, anim, images)
                return True

        static = self._cacheGet(self._current_fbx)
        if static is None:
            return False
        md, _anim, images = static
        self._gl_view.showResult(md, None, images)
        return True

    def _openCurrentActionFolder(self):
        """打开当前动作目录；Windows 资源管理器可用时直接选中动作文件。"""
        if not self._selected_action:
            return
        action_path = os.path.normpath(self._selected_action)
        folder = os.path.dirname(action_path)

        if os.path.isfile(action_path):
            try:
                started = QtCore.QProcess.startDetached(
                    "explorer.exe", ["/select,", action_path])
                # PySide2 返回 bool；兼容某些绑定返回 (bool, pid)。
                if isinstance(started, tuple):
                    started = started[0]
                if started:
                    return
            except Exception:
                pass

        if os.path.isdir(folder):
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder))

    # ------------------------------------------------- 对外接口(drop-in)
    def setTitle(self, name, zh_name):
        self._name = str(name) if name is not None else None
        self._base_name = self._name
        self._base_zh_name = str(zh_name) if zh_name is not None else None
        self._setTitleText(self._base_name, self._base_zh_name)

    def _setTitleText(self, name, zh_name):
        name_text = "" if name is None else str(name)
        zh_text = "" if zh_name is None else str(zh_name)
        self.title_label.setText(u"Name： " + name_text + u"\n中文名： " + zh_text)

    def refreshThumbnail(self, path, image):
        """Refresh the current fallback image without reloading the FBX preview."""
        key = os.path.normcase(os.path.normpath(path or ""))
        current = os.path.normcase(os.path.normpath(self._fallback_icon or ""))
        if key != current or image is None or image.isNull():
            return
        self._fallback_pixmap = QtGui.QPixmap.fromImage(image)
        self._fallback_pixmap_path = (path or "").replace("\\", "/")
        if self._stack.currentIndex() == self._PAGE_FALLBACK:
            self._applyFallbackPixmap()

    def setPreviewPixmap(self, path, _type=None):
        self._fallback_icon = path or ""
        if self._preview_mode == "2d":
            self._showFallback(self._fallback_icon)
        fbx = self._deriveFbxPath(path, self._name)
        self._scheduleLoad(fbx, path)
        self._requestSurfaceVariants(path)

    def _requestSurfaceVariants(self, icon_path):
        """异步发现当前资产的逐皮 Icon+FBX；普通/场景资产保持原预览路径。"""
        self._surface_request_serial += 1
        serial = self._surface_request_serial
        path = (icon_path or "").replace("\\", "/")
        if not self._base_name or "/assets/" not in path.lower():
            self._clearSurfaceControls()
            return
        self._surface_loader.request(
            path, self._base_name,
            lambda variants, token=serial: self._onSurfaceVariants(token, variants))

    def _onSurfaceVariants(self, serial, variants):
        if serial != self._surface_request_serial:
            return
        if len(variants) < 2:
            self._clearSurfaceControls()
            return

        self._surface_variants = list(variants)
        self._surface_index = -1
        self._thumbnail_loader.setProtectedPaths(
            self._thumbnail_protection_key,
            [variant[1] for variant in self._surface_variants])
        self._rebuildSurfaceButtons()
        self._surface_bar.show()
        self._surface_prev_btn.show()
        self._surface_next_btn.show()
        self._surface_prev_btn.raise_()
        self._surface_next_btn.raise_()
        self._positionPreviewOverlays()
        self._schedulePreviewOverlayRefresh()

        # 多皮肤资产不显示主/总 FBX，默认使用自然排序后的首套皮肤。
        self._selectSurface(0)

    def _clearSurfaceControls(self):
        self._thumbnail_loader.clearProtectedPaths(self._thumbnail_protection_key)
        self._surface_variants = []
        self._surface_index = -1
        self._surface_buttons = {}
        if not hasattr(self, '_surface_layout'):
            return
        while self._surface_layout.count():
            item = self._surface_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._surface_bar.hide()
        self._surface_prev_btn.hide()
        self._surface_next_btn.hide()

    def _rebuildSurfaceButtons(self):
        while self._surface_layout.count():
            item = self._surface_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._surface_buttons = {}

        count = max(1, len(self._surface_variants))
        available = max(180, self.width() - 16)
        spacing = max(0, self._surface_layout.spacing())
        button_size = max(
            26, min(42, (available - (count - 1) * spacing) // count))
        for index, (surface, icon_path, _fbx_path) in enumerate(self._surface_variants):
            button = QtWidgets.QToolButton(self._surface_bar)
            button.setFixedSize(button_size, button_size)
            button.setIconSize(QtCore.QSize(button_size - 4, button_size - 4))
            button.setToolTip("%s_%s" % (self._base_name, surface))
            button.clicked.connect(
                lambda _checked=False, value=index: self._selectSurface(value))
            self._surface_layout.addWidget(button)
            self._surface_buttons.setdefault(icon_path, []).append(button)

            cached = self._thumbnail_loader.getCachedPixmap(icon_path)
            if cached is not None:
                button.setIcon(QtGui.QIcon(cached))
            else:
                self._thumbnail_loader.loadThumbnail(
                    icon_path, 128, self._onSurfaceButtonThumbnail)
        self._updateSurfaceButtonState()

    def _onSurfaceButtonThumbnail(self, path, pixmap):
        for button in self._surface_buttons.get(path, []):
            try:
                button.setIcon(QtGui.QIcon(pixmap))
            except RuntimeError:
                pass

    def _updateSurfaceButtonState(self):
        selected_style = (
            "QToolButton { border: 2px solid rgb(82,133,166);"
            " background: transparent; border-radius: 3px; padding: 0px; }")
        normal_style = (
            "QToolButton { border: 2px solid transparent;"
            " background: transparent; border-radius: 3px; padding: 0px; }"
            "QToolButton:hover { border-color: rgba(130,165,187,175); }")
        for index, (_surface, icon_path, _fbx_path) in enumerate(self._surface_variants):
            for button in self._surface_buttons.get(icon_path, []):
                button.setStyleSheet(selected_style if index == self._surface_index
                                     else normal_style)

    def _stepSurface(self, amount):
        if len(self._surface_variants) < 2:
            return
        start = self._surface_index if self._surface_index >= 0 else 0
        self._selectSurface((start + amount) % len(self._surface_variants))

    def _selectSurface(self, index):
        """切换当前绑定 FBX；已有动作会立即在新皮肤的同套骨骼上重播。"""
        if not 0 <= index < len(self._surface_variants):
            return
        action_to_resume = self._selected_action or self._current_action
        self._surface_index = index
        self._updateSurfaceButtonState()
        surface, icon_path, fbx_path = self._surface_variants[index]
        self._setTitleText("%s_%s" % (self._base_name, surface), self._base_zh_name)

        # 取消尚未触发的主 <asset>.fbx 防抖加载，避免它晚于皮肤选择并覆盖当前模型。
        self._load_timer.stop()
        self._pending_fbx = None
        self._pending_icon = None
        self.loadFbx(fbx_path, icon_path)
        if action_to_resume and os.path.isfile(action_to_resume):
            self.playAction(action_to_resume)

    def playerEnabled(self, value):
        pass  # FBX 预览无序列播放器,空实现保持接口兼容

    def clear(self):
        self._load_timer.stop()
        self._surface_request_serial += 1
        self._pending_fbx = None
        self._pending_icon = None
        self._current_fbx = None
        self._current_action = None
        self._selected_action = None
        self._name = None
        self._base_name = None
        self._base_zh_name = None
        self._clearSurfaceControls()
        self.title_label.clear()
        self._image_label.clear()
        self._fallback_pixmap = None
        self._fallback_pixmap_path = ""
        self._fallback_icon = ""
        if self._gl_view is not None:
            self._gl_view.clearMesh()
        self._stack.setCurrentIndex(self._PAGE_FALLBACK)

    def deriveFbxPath(self, icon_path):
        """供 am_main 取当前资产的绑定文件路径(.../FBX/<name>.fbx)。"""
        return self._deriveFbxPath(icon_path, self._name)

    # ----------------------------------------------------------- 动作(骨骼动画套用)
    def playAction(self, action_path):
        """把动作文件的骨骼动画套用到当前绑定文件上循环播放。
        action_path 为空/无效 -> 回到绑定文件静态预览。"""
        norm = action_path.replace("\\", "/") if action_path else ""
        self._selected_action = norm or None
        rig = self._current_fbx
        if not norm or rig is None or self._gl_failed or self._gl_view is None \
                or not os.path.isfile(norm):
            self._current_action = None
            self._showRigStatic()
            return
        if norm == self._current_action:
            return
        self._current_action = norm

        cached = self._animCacheGet(rig, norm)
        if cached is not None:
            anim, images = cached
            self._gl_view.showResult(self._rigStaticMd(rig), anim, images)
            self._showPageForCurrentMode(self._PAGE_GL)
            return

        self._showPageForCurrentMode(self._PAGE_LOADING)
        self._pool.start(_CombineTask(rig, norm, self._csignals,
                                      self._skin_cache, self._skin_lock))

    def _rigStaticMd(self, rig):
        """从静态缓存取 rig 的 MeshData(作动画不支持时的回退);无则 None。"""
        c = self._cacheGet(rig)
        return c[0] if c is not None else None

    def _showRigStatic(self):
        """回到当前绑定文件的静态预览(优先用缓存,避免重新解析)。"""
        rig = self._current_fbx
        if rig is None or self._gl_view is None:
            return
        cached = self._cacheGet(rig)
        if cached is not None:
            md, anim, images = cached
            self._gl_view.showResult(md, None, images)
            self._showPageForCurrentMode(self._PAGE_GL)
        else:
            self._showPageForCurrentMode(self._PAGE_LOADING)
            self._pool.start(_ParseTask(rig, self._signals))

    def _onCombined(self, rig, action, anim, images):
        if rig != self._current_fbx or action != self._current_action:
            print("[PreviewGL] _onCombined: stale result, ignored")
            return  # 已切换,丢弃过期结果
        print("[PreviewGL] _onCombined: cache and show animation")
        self._animCachePut(rig, action, anim, images)
        if self._gl_view is not None:
            self._gl_view.showResult(self._rigStaticMd(rig), anim, images)
            self._showPageForCurrentMode(self._PAGE_GL)

    def _onCombineFailed(self, rig, action):
        if rig != self._current_fbx or action != self._current_action:
            print("[PreviewGL] _onCombineFailed: stale result, ignored")
            return
        print("[PreviewGL] _onCombineFailed: fall back to static")
        self._current_action = None
        self._showRigStatic()

    # ----------------------------------------------------------- 加载调度
    def _deriveFbxPath(self, icon_path, name):
        """icon 路径 + 资产名 → FBX 路径(同 detailPath 约定)。
        例 .../X/Icon/X.png → .../X/FBX/X.fbx

        以带分隔符的 "/Icon/" 为锚点(并用 rsplit 取最后一次出现)定位 Icon 目录,
        避免资产名/类型名本身含 "Icon" 子串(如 RoadIcon)时被 split("Icon") 误切。
        """
        if not icon_path or not name:
            return ""
        ip = icon_path.replace("\\", "/")
        if "/Icon/" in ip:
            root = ip.rsplit("/Icon/", 1)[0] + "/"
        else:
            # 回退:取 icon 文件的上一级目录(.../<asset>/Icon/<asset>.png → .../<asset>/)
            root = os.path.dirname(os.path.dirname(ip))
            if root and not root.endswith("/"):
                root += "/"
        return "%sFBX/%s.fbx" % (root, name)

    def _scheduleLoad(self, fbx, icon):
        self._pending_fbx = fbx
        self._pending_icon = icon
        self._load_timer.start()

    def _loadPending(self):
        self.loadFbx(self._pending_fbx, self._pending_icon)

    def loadFbx(self, fbx_path, fallback_icon=None):
        norm = fbx_path.replace("\\", "/") if fbx_path else ""
        self._fallback_icon = fallback_icon or self._fallback_icon

        if self._gl_failed or self._gl_view is None or not norm or not os.path.isfile(norm):
            self._current_fbx = None
            self._selected_action = None
            self._showFallback(self._fallback_icon)
            return

        if norm == self._current_fbx:
            if self._preview_mode == "2d":
                self._showFallback(self._fallback_icon)
            return  # 去重

        self._current_fbx = norm
        self._current_action = None     # 切换资产 -> 回到静态
        self._selected_action = None

        cached = self._cacheGet(norm)
        if cached is not None:
            md, anim, images = cached
            self._gl_view.showResult(md, anim, images)
            self._showPageForCurrentMode(self._PAGE_GL)
            return

        self._showPageForCurrentMode(self._PAGE_LOADING)
        self._pool.start(_ParseTask(norm, self._signals))

    def _onParsed(self, path, md, anim, images):
        if path != self._current_fbx:
            return  # 已切换,丢弃过期结果
        self._cachePut(path, md, anim, images)
        # 用户可能在皮肤 FBX 仍解析时就点击了动作。此时只补齐静态缓存，不让较晚
        # 返回的静态结果覆盖已经开始/完成的动作合成结果。
        if self._current_action:
            return
        if self._gl_view is not None:
            self._gl_view.showResult(md, anim, images)
            self._showPageForCurrentMode(self._PAGE_GL)

    def _onParseFailed(self, path):
        if path != self._current_fbx:
            return
        self._current_fbx = None
        self._showFallback(self._fallback_icon)

    def _onGLFailed(self):
        self._gl_failed = True
        self._showFallback(self._fallback_icon)

    # ----------------------------------------------------------- 缓存(小 LRU)
    def _cacheGet(self, path):
        rec = self._cache.get(path)
        if not rec:
            return None
        mtime, md, anim, images = rec
        try:
            if os.path.getmtime(path) != mtime:
                return None
        except OSError:
            return None
        try:
            self._cache_order.remove(path)
        except ValueError:
            pass
        self._cache_order.append(path)
        return md, anim, images

    def _cachePut(self, path, md, anim, images):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        self._cache[path] = (mtime, md, anim, images)
        if path in self._cache_order:
            self._cache_order.remove(path)
        self._cache_order.append(path)
        while len(self._cache_order) > self._CACHE_CAP:
            old = self._cache_order.pop(0)
            self._cache.pop(old, None)

    def _animCacheGet(self, rig, action):
        rec = self._anim_cache.get((rig, action))
        if not rec:
            return None
        try:
            self._anim_order.remove((rig, action))
        except ValueError:
            pass
        self._anim_order.append((rig, action))
        return rec

    def _animCachePut(self, rig, action, anim, images):
        key = (rig, action)
        self._anim_cache[key] = (anim, images)
        if key in self._anim_order:
            self._anim_order.remove(key)
        self._anim_order.append(key)
        while len(self._anim_order) > self._CACHE_CAP:
            old = self._anim_order.pop(0)
            self._anim_cache.pop(old, None)

    # ----------------------------------------------------------- 回退图片
    def _showFallback(self, icon_path):
        path = (icon_path or "").replace("\\", "/")
        self._fallback_icon = path
        if path and os.path.isfile(path):
            if (path != self._fallback_pixmap_path or self._fallback_pixmap is None
                    or self._fallback_pixmap.isNull()):
                self._fallback_pixmap = QtGui.QPixmap(path)
                self._fallback_pixmap_path = (
                    path if not self._fallback_pixmap.isNull() else "")
            if self._fallback_pixmap is not None and not self._fallback_pixmap.isNull():
                self._applyFallbackPixmap()
            else:
                self._image_label.clear()
        else:
            self._fallback_pixmap = None
            self._fallback_pixmap_path = ""
            self._image_label.clear()
        self._stack.setCurrentIndex(self._PAGE_FALLBACK)

    def _applyFallbackPixmap(self):
        if not self._fallback_pixmap or self._fallback_pixmap.isNull():
            return
        # 交给 _IconPreviewView 在绘制时按窗口尺寸适配。保留原始分辨率，放大查看
        # 细节时不会被预先缩小的中间图限制；重复提交同一 QPixmap 也不会重置视图。
        self._image_label.setPixmap(self._fallback_pixmap)
