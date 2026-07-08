#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PreviewGLWidget —— 资产 FBX 三维预览(自写 OpenGL 视口)。

作为 widgets/previewWidget.PreviewWidget 的 drop-in 替换:选中资产时用纯 Python
解析其 FBX 几何/材质(utils/fbxMesh),在我们自己的 QOpenGLWidget 里渲染,支持鼠标
自由旋转/缩放/平移,**并显示漫反射贴图/固有色**。全程内存内完成,**不向用户的
Maya 场景添加任何东西**。

设计要点:
  * GLView: QOpenGLWidget 子类,独立 GL 上下文;按材质分子网格绘制(各自固有色/贴图),
    key+fill 双向光照(双面,避免反向缠绕发黑);LMB 旋转、滚轮缩放、MMB/Shift+LMB
    平移、双击重新框选。
  * 解析在后台线程(QThreadPool):worker 调 fbxMesh.read 得到几何 + 子网格(含贴图路径),
    并在 worker 线程加载贴图 QImage(已竖直翻转以匹配 GL);主线程回调里交给 GLView,
    VBO 与 GL 纹理在 paintGL 上传(此时 GL 上下文为当前)。按 (路径, mtime) 做小 LRU 缓存。
  * 三态显示:模型 / 加载中 / 回退图(无 FBX、解析失败、GL 不可用时显示 icon)。
  * 防抖 200ms + 去重。

drop-in 接口:clear() / setTitle() / setPreviewPixmap() / playerEnabled()。
由 am_main.AssetManagerPanel 实例化并放在主面板右侧;选中资产时根据其 Icon 路径推导
出同资产的 FBX(.../<asset>/Icon/<asset>.png -> .../<asset>/FBX/<asset>.fbx)并预览。
"""

import os
import math
import array
import threading

from PySide6 import QtGui
from PySide6 import QtCore
from PySide6 import QtWidgets
from PySide6 import QtOpenGL  # Qt6:QOpenGL* 着色器/缓冲/纹理类已从 QtGui 迁到此模块

from . import am_fbxMesh as fbxMesh

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
_GL_FLOAT = 0x1406

_STRIDE = 8 * 4  # pos3 + nrm3 + uv2,float32
_SKIN_STRIDE = 16 * 4  # pos3 + nrm3 + uv2 + boneIdx4 + boneWeight4,float32

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
            self.setAnimatedMesh(anim.interleaved, anim.submeshes, images, anim.palettes,
                                 anim.frame_count, anim.bone_count, anim.fps,
                                 anim.bbox_min, anim.bbox_max)
        elif md is not None:
            self.setMesh(md.interleaved, md.submeshes, images, md.bbox_min, md.bbox_max)
        # 否则(动画不支持且无静态回退)保持当前显示不变

    def _advanceFrame(self):
        if not self._is_animated or self._frame_count <= 1:
            return
        self._cur_frame = (self._cur_frame + 1) % self._frame_count
        self.update()

    def _fitTo(self, bbox_min, bbox_max):
        cx = (bbox_min[0] + bbox_max[0]) * 0.5
        cy = (bbox_min[1] + bbox_max[1]) * 0.5
        cz = (bbox_min[2] + bbox_max[2]) * 0.5
        self._target = QtGui.QVector3D(cx, cy, cz)
        dx = bbox_max[0] - bbox_min[0]
        dy = bbox_max[1] - bbox_min[1]
        dz = bbox_max[2] - bbox_min[2]
        r = 0.5 * math.sqrt(dx * dx + dy * dy + dz * dz)
        self._radius = r if r > 1e-6 else 1.0
        self._dist = self._radius / math.sin(math.radians(22.5)) * 1.2
        self._az = 35.0
        self._el = 18.0

    # ----------------------------------------------------------- GL 生命周期
    def initializeGL(self):
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

        # 蒙皮程序失败不影响静态:仅置 _skin_supported=False
        self._initSkinProgram()

        # 初始化完成,应用初始化前可能已到达的解析结果
        self._gl_inited = True
        self._applyResult()

    def _initSkinProgram(self):
        """构建蒙皮(动画)程序。每骨 3×vec4,按可用顶点 uniform 上限选 MAX_BONES,
        链接失败逐级回退;全失败置 _skin_supported=False(动画资产回退静态)。"""
        try:
            maxv = 0
            try:
                v = self._gl.glGetIntegerv(_GL_MAX_VERTEX_UNIFORM_VECTORS)
                maxv = int(v[0]) if isinstance(v, (list, tuple)) else int(v)
            except Exception:
                maxv = 0
            # 每骨 3 vec4,留 16 vec4 给 u_mvp 等
            budget = max(16, min(400, (maxv - 16) // 3)) if maxv > 0 else 128
            candidates = [budget, 256, 200, 128, 64]

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
        except Exception:
            self._skin_supported = False

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
        finally:
            self.doneCurrent()

    def resizeGL(self, w, h):
        if self._gl:
            self._gl.glViewport(0, 0, w, max(1, h))

    def paintGL(self):
        if self._init_failed or not self._gl or not self._program:
            return

        bg = 38.0 / 255.0
        self._gl.glClearColor(bg, bg, bg + 3.0 / 255.0, 1.0)
        self._gl.glClear(_GL_COLOR_BUFFER_BIT | _GL_DEPTH_BUFFER_BIT)
        self._gl.glEnable(_GL_DEPTH_TEST)

        if self._dirty:
            self._uploadPending()

        if self._is_animated:
            self._paintAnimated()
        else:
            self._paintStatic()

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
        near = max(self._dist - self._radius * 2.0, self._radius * 0.01, 0.001)
        far = self._dist + self._radius * 2.0 + 1.0
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
        self._last_pos = e.pos()
        self._last_btn = e.button()
        self.setFocus()

    def mouseMoveEvent(self, e):
        if self._last_pos is None:
            return
        dx = e.x() - self._last_pos.x()
        dy = e.y() - self._last_pos.y()
        self._last_pos = e.pos()

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
        self._dist = self._radius / math.sin(math.radians(22.5)) * 1.2
        self._az = 35.0
        self._el = 18.0
        self.update()


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
                if skin is not None:
                    with self._skin_lock:
                        self._skin_cache[self._rig] = (mtime, skin)
            if skin is None:
                self._signals.failed.emit(self._rig, self._action)
                return
            action = fbxMesh.read_action(self._action)
            if action is None:
                self._signals.failed.emit(self._rig, self._action)
                return
            anim = fbxMesh.combine(skin, action)
            images = _load_images(anim.submeshes)
            self._signals.done.emit(self._rig, self._action, anim, images)
        except Exception:
            self._signals.failed.emit(self._rig, self._action)


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
        self._name = None
        self._fallback_icon = ""
        self._fallback_pixmap = None
        self._current_fbx = None        # 当前绑定文件 rig(去重 + 防过期)
        self._current_action = None     # 当前播放的动作路径(None=静态)
        self._gl_failed = not _HAS_QOPENGL
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
        self._image_label = QtWidgets.QLabel()
        self._image_label.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignHCenter)
        self._image_label.setStyleSheet(self._GRADIENT_BG)
        self._stack.addWidget(self._image_label)            # index 0

        # page1: GL 视口(仅在 QOpenGLWidget 可用时)
        self._gl_view = None
        if _HAS_QOPENGL:
            self._gl_view = GLView(self)
            self._gl_view.initFailed.connect(self._onGLFailed)
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

        self.title_label = QtWidgets.QLabel(self)
        self.title_label.setStyleSheet(
            "color: rgb(150, 150, 150);background-color: rgb(29, 29, 29);")
        self.title_label.setFixedHeight(45)
        self.title_label.setFont(QtGui.QFont(u"Microsoft YaHei UI", 10))
        vLayout.addWidget(self.title_label)

    def resizeEvent(self, e):
        # 不再锁定高度为正方形(原 Maya 版的 setMaximumHeight 上限),
        # 让预览随所在面板自由拉伸;回退图按当前尺寸保持比例重绘即可。
        if self._stack.currentIndex() == self._PAGE_FALLBACK and self._fallback_pixmap:
            self._applyFallbackPixmap()
        super(PreviewGLWidget, self).resizeEvent(e)

    # ------------------------------------------------- 对外接口(drop-in)
    def setTitle(self, name, zh_name):
        self._name = str(name) if name is not None else None
        if zh_name is not None:
            self.title_label.setText(u"Name： " + str(name) + u"\n中文名： " + str(zh_name))
        else:
            self.title_label.setText(u"Name： " + str(name) + u"\n中文名： ")

    def setPreviewPixmap(self, path, _type=None):
        self._fallback_icon = path or ""
        fbx = self._deriveFbxPath(path, self._name)
        self._scheduleLoad(fbx, path)

    def playerEnabled(self, value):
        pass  # FBX 预览无序列播放器,空实现保持接口兼容

    def clear(self):
        self._load_timer.stop()
        self._pending_fbx = None
        self._pending_icon = None
        self._current_fbx = None
        self._current_action = None
        self.title_label.clear()
        self._image_label.clear()
        self._fallback_pixmap = None
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
            self._stack.setCurrentIndex(self._PAGE_GL)
            return

        self._stack.setCurrentIndex(self._PAGE_LOADING)
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
            self._stack.setCurrentIndex(self._PAGE_GL)
        else:
            self._stack.setCurrentIndex(self._PAGE_LOADING)
            self._pool.start(_ParseTask(rig, self._signals))

    def _onCombined(self, rig, action, anim, images):
        if rig != self._current_fbx or action != self._current_action:
            return  # 已切换,丢弃过期结果
        self._animCachePut(rig, action, anim, images)
        if self._gl_view is not None:
            self._gl_view.showResult(self._rigStaticMd(rig), anim, images)
            self._stack.setCurrentIndex(self._PAGE_GL)

    def _onCombineFailed(self, rig, action):
        if rig != self._current_fbx or action != self._current_action:
            return
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

        if self._gl_failed or self._gl_view is None or not norm or not os.path.isfile(norm):
            self._current_fbx = None
            self._showFallback(fallback_icon)
            return

        if norm == self._current_fbx:
            return  # 去重

        self._current_fbx = norm
        self._current_action = None     # 切换资产 -> 回到静态
        self._fallback_icon = fallback_icon or self._fallback_icon

        cached = self._cacheGet(norm)
        if cached is not None:
            md, anim, images = cached
            self._gl_view.showResult(md, anim, images)
            self._stack.setCurrentIndex(self._PAGE_GL)
            return

        self._stack.setCurrentIndex(self._PAGE_LOADING)
        self._pool.start(_ParseTask(norm, self._signals))

    def _onParsed(self, path, md, anim, images):
        if path != self._current_fbx:
            return  # 已切换,丢弃过期结果
        self._cachePut(path, md, anim, images)
        if self._gl_view is not None:
            self._gl_view.showResult(md, anim, images)
            self._stack.setCurrentIndex(self._PAGE_GL)

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
        if path and os.path.isfile(path):
            self._fallback_pixmap = QtGui.QPixmap(path)
            self._applyFallbackPixmap()
        else:
            self._fallback_pixmap = None
            self._image_label.clear()
        self._stack.setCurrentIndex(self._PAGE_FALLBACK)

    def _applyFallbackPixmap(self):
        if not self._fallback_pixmap or self._fallback_pixmap.isNull():
            return
        w = max(1, self._image_label.width())
        h = max(1, self._image_label.height())
        self._image_label.setPixmap(
            self._fallback_pixmap.scaled(
                w, h, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
