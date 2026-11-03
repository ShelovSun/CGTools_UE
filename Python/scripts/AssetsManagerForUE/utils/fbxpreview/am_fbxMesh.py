#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fbxMesh —— 纯 Python 解析 FBX(二进制 7.x)几何 + 材质,供自写 OpenGL 预览使用。

只用标准库(os/struct/zlib/array/math)，**不依赖** PySide2 / numpy / Autodesk FBX SDK，
全程在内存里解析，**不向 Maya 场景添加任何东西**。这是 AssetsManager「资产 FBX 三维
预览」的取数层(见同目录 am_previewGLWidget.py)。

read(path) -> (MeshData, AnimData|None)：
  - 抽取所有 Mesh 几何的顶点/法线/UV，按其所属 Model 的局部变换(Lcl TRS + Geometric*)
    经 Connections 放置，三角化后**按材质分组**为若干子网格(submesh)，每个子网格带固有色
    (DiffuseColor)与可选漫反射贴图路径。合并为一份交错缓冲(pos3+nrm3+uv2, float32)。
  - 若检测到动画(AnimationCurve 驱动 Model 的 Lcl TRS),额外返回 AnimData:几何局部的蒙皮
    顶点缓冲(pos3+nrm3+uv2+boneIdx4+boneW4)+ 每采样帧的骨骼矩阵调色板。把"刚体变换动画"
    当成"单骨骼蒙皮",与骨骼蒙皮动画统一。无动画/解析失败则该项为 None,上层回退静态显示。
  - 贴图路径在此解析(候选:FBX 内记录路径 / fbx 同目录 / {资产根}/Texture|Textures|Images/)。
    本模块保持 Qt-free，只回传**文件路径**;QImage 由上层在 worker 线程加载、GUI 线程上传。
  - 解析失败 / 不支持(ASCII FBX、NURBS 等)抛 FbxParseError；上层据此回退显示 icon。

已知简化：
  - 只读二进制 FBX(Maya FBXExport 默认即二进制)；ASCII FBX 不支持。
  - 会读取 GlobalSettings 的 Up/Front/Coord Axis 与 UnitScaleFactor，并统一转换为
    Maya 常用的 Y-up / +Z front / +X coord / cm 内部坐标系。
  - 静态和动画变换会处理 RotationOrder、Pre/PostRotation 与旋转/缩放轴心。
  - 非索引(每三角形 3 个角点)输出 —— 解析快、避免逐角点字典去重的开销(大网格友好)。
  - 假设小端(Windows/Mac x64/ARM 均小端)。
"""

import os
import sys
import struct
import zlib
import array
import math


_DEBUG = bool(os.environ.get("AM_FBX_DEBUG"))


def _dbg(msg):
    if _DEBUG:
        sys.stderr.write("[fbxMesh] %s\n" % msg)


class FbxParseError(Exception):
    pass


# --------------------------------------------------------------------------- 节点树
class _Node(object):
    __slots__ = ("name", "props", "children")

    def __init__(self, name):
        self.name = name
        self.props = []
        self.children = []

    def first(self, name):
        for c in self.children:
            if c.name == name:
                return c
        return None


_HEADER = b"Kaydara FBX Binary  \x00"


def _read_property(data, pos):
    tc = chr(data[pos])
    pos += 1
    if tc == 'Y':
        return struct.unpack_from("<h", data, pos)[0], pos + 2
    if tc == 'C':
        return (data[pos] != 0), pos + 1
    if tc == 'I':
        return struct.unpack_from("<i", data, pos)[0], pos + 4
    if tc == 'F':
        return struct.unpack_from("<f", data, pos)[0], pos + 4
    if tc == 'D':
        return struct.unpack_from("<d", data, pos)[0], pos + 8
    if tc == 'L':
        return struct.unpack_from("<q", data, pos)[0], pos + 8
    if tc in ('f', 'd', 'l', 'i', 'b'):
        _array_len, encoding, comp_len = struct.unpack_from("<III", data, pos)
        pos += 12
        raw = data[pos:pos + comp_len]
        pos += comp_len
        if encoding == 1:
            raw = zlib.decompress(raw)
        fmt = {'f': 'f', 'd': 'd', 'l': 'q', 'i': 'i', 'b': 'b'}[tc]
        arr = array.array(fmt)
        arr.frombytes(raw)
        return arr, pos
    if tc == 'S' or tc == 'R':
        length = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        v = data[pos:pos + length]
        pos += length
        if tc == 'S':
            v = v.decode("utf-8", "replace")
        return v, pos
    raise FbxParseError("unknown property type %r at %d" % (tc, pos - 1))


def _read_node(data, pos, use64):
    if use64:
        end_offset, num_props, _plen = struct.unpack_from("<QQQ", data, pos)
        pos += 24
    else:
        end_offset, num_props, _plen = struct.unpack_from("<III", data, pos)
        pos += 12
    name_len = data[pos]
    pos += 1
    if end_offset == 0:
        return None, pos  # 空记录(列表结束哨兵)
    name = data[pos:pos + name_len].decode("utf-8", "replace")
    pos += name_len
    node = _Node(name)
    for _ in range(num_props):
        val, pos = _read_property(data, pos)
        node.props.append(val)
    while pos < end_offset:
        child, pos = _read_node(data, pos, use64)
        if child is None:
            break
        node.children.append(child)
    return node, end_offset


def _parse_tree(data):
    if data[:len(_HEADER)] != _HEADER:
        raise FbxParseError("not a binary FBX (header mismatch)")
    version = struct.unpack_from("<I", data, 23)[0]
    use64 = version >= 7500
    pos = 27
    root = _Node("__root__")
    n = len(data)
    while pos < n:
        node, pos = _read_node(data, pos, use64)
        if node is None:
            break
        root.children.append(node)
    return root


# --------------------------------------------------------------------------- 矩阵(行主序 16)
def _identity():
    return [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def _matmul(a, b):
    r = [0.0] * 16
    for i in range(4):
        ai0, ai1, ai2, ai3 = a[i * 4], a[i * 4 + 1], a[i * 4 + 2], a[i * 4 + 3]
        for j in range(4):
            r[i * 4 + j] = ai0 * b[j] + ai1 * b[4 + j] + ai2 * b[8 + j] + ai3 * b[12 + j]
    return r


def _translation(t):
    m = _identity()
    m[3], m[7], m[11] = t[0], t[1], t[2]
    return m


def _scale(s):
    return [s[0], 0, 0, 0, 0, s[1], 0, 0, 0, 0, s[2], 0, 0, 0, 0, 1.0]


def _rotx(d):
    a = math.radians(d); c = math.cos(a); s = math.sin(a)
    return [1.0, 0, 0, 0, 0, c, -s, 0, 0, s, c, 0, 0, 0, 0, 1.0]


def _roty(d):
    a = math.radians(d); c = math.cos(a); s = math.sin(a)
    return [c, 0, s, 0, 0, 1.0, 0, 0, -s, 0, c, 0, 0, 0, 0, 1.0]


def _rotz(d):
    a = math.radians(d); c = math.cos(a); s = math.sin(a)
    return [c, -s, 0, 0, s, c, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def _euler_xyz(r):
    # Maya 默认旋转顺序 XYZ：列向量约定下合成矩阵 = Rz * Ry * Rx
    return _matmul(_rotz(r[2]), _matmul(_roty(r[1]), _rotx(r[0])))


def _local_matrix(t, r, s):
    return _matmul(_translation(t), _matmul(_euler_xyz(r), _scale(s)))


def _xform_point(m, x, y, z):
    return (m[0] * x + m[1] * y + m[2] * z + m[3],
            m[4] * x + m[5] * y + m[6] * z + m[7],
            m[8] * x + m[9] * y + m[10] * z + m[11])


def _xform_dir(m, x, y, z):
    return (m[0] * x + m[1] * y + m[2] * z,
            m[4] * x + m[5] * y + m[6] * z,
            m[8] * x + m[9] * y + m[10] * z)


def _transpose(m):
    return [m[0], m[4], m[8], m[12],
            m[1], m[5], m[9], m[13],
            m[2], m[6], m[10], m[14],
            m[3], m[7], m[11], m[15]]


def _mat_from_fbx(arr16):
    """FBX 序列化的 4x4(行向量/行主序,平移在 12/13/14) -> 本模块的列向量/行主序
    (平移在 3/7/11,_xform_point 算 M·v)。即一次转置。长度不足回退单位阵。"""
    if arr16 is None or len(arr16) < 16:
        return _identity()
    a = [float(x) for x in arr16[:16]]
    return _transpose(a)


def _inverse(m):
    """通用 4x4 求逆(高斯-约当,带部分主元),奇异返回单位阵。
    m 为本模块约定(行主序存储 / 列向量约定);cluster 矩阵可能含缩放,不能假设正交。"""
    a = [[m[0], m[1], m[2], m[3]],
         [m[4], m[5], m[6], m[7]],
         [m[8], m[9], m[10], m[11]],
         [m[12], m[13], m[14], m[15]]]
    inv = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
    for col in range(4):
        piv = col
        best = abs(a[col][col])
        for r in range(col + 1, 4):
            if abs(a[r][col]) > best:
                best = abs(a[r][col]); piv = r
        if best < 1e-12:
            return _identity()
        if piv != col:
            a[col], a[piv] = a[piv], a[col]
            inv[col], inv[piv] = inv[piv], inv[col]
        invpiv = 1.0 / a[col][col]
        for j in range(4):
            a[col][j] *= invpiv
            inv[col][j] *= invpiv
        for r in range(4):
            if r == col:
                continue
            f = a[r][col]
            if f == 0.0:
                continue
            for j in range(4):
                a[r][j] -= f * a[col][j]
                inv[r][j] -= f * inv[col][j]
    return [inv[0][0], inv[0][1], inv[0][2], inv[0][3],
            inv[1][0], inv[1][1], inv[1][2], inv[1][3],
            inv[2][0], inv[2][1], inv[2][2], inv[2][3],
            inv[3][0], inv[3][1], inv[3][2], inv[3][3]]


# --------------------------------------------------------------------------- Properties70
def _p70(node, name):
    """从某节点的 Properties70 取某属性的数值尾部(如 Lcl Translation -> [x,y,z])。"""
    p = node.first("Properties70")
    if not p:
        return None
    for c in p.children:
        if c.name == "P" and c.props and c.props[0] == name:
            nums = [x for x in c.props[1:]
                    if isinstance(x, (int, float)) and not isinstance(x, bool)]
            return nums if nums else None
    return None


# --------------------------------------------------------------------------- FBX 全局轴系
class AxisSystem(object):
    """FBX GlobalSettings 轴系，以及转换到本预览器内部坐标系的矩阵。

    FBX 用三个互不重复的轴索引(0=X/1=Y/2=Z)和符号描述 Up、Front、Coord。
    本预览器固定使用 Maya 常用的 Up=+Y、Front=+Z、Coord=+X；matrix 把源文件
    坐标转换到这个内部坐标系，并同时把 UnitScaleFactor 归一到厘米。
    """

    __slots__ = ("up_axis", "up_sign", "front_axis", "front_sign",
                 "coord_axis", "coord_sign", "unit_scale", "matrix", "valid")

    def __init__(self, up_axis, up_sign, front_axis, front_sign,
                 coord_axis, coord_sign, unit_scale, matrix, valid=True):
        self.up_axis = up_axis
        self.up_sign = up_sign
        self.front_axis = front_axis
        self.front_sign = front_sign
        self.coord_axis = coord_axis
        self.coord_sign = coord_sign
        self.unit_scale = unit_scale
        self.matrix = matrix
        self.valid = valid

    def describe(self):
        names = "XYZ"

        def axis_text(axis, sign):
            return ("+" if sign > 0 else "-") + names[axis]

        return "Up=%s Front=%s Coord=%s Unit=%.6gcm%s" % (
            axis_text(self.up_axis, self.up_sign),
            axis_text(self.front_axis, self.front_sign),
            axis_text(self.coord_axis, self.coord_sign),
            self.unit_scale,
            "" if self.valid else " (fallback)",
        )


def _axis_system(root):
    """读取 FBX GlobalSettings，返回到内部 Y-up 坐标系的转换信息。

    缺少或损坏轴信息时按 Maya FBX 常见默认值处理，因此 Maya 导出的 Y-up 文件
    得到单位矩阵；例如 Maya/FBX 的 Z-up 文件会得到 (x, y, z)->(x, z, -y)。
    """
    gs = root.first("GlobalSettings") if root else None

    def int_prop(name, default):
        value = _p70(gs, name) if gs else None
        try:
            return int(value[0]) if value else default
        except (TypeError, ValueError, IndexError):
            return default

    def float_prop(name, default):
        value = _p70(gs, name) if gs else None
        try:
            return float(value[0]) if value else default
        except (TypeError, ValueError, IndexError):
            return default

    up_axis = int_prop("UpAxis", 1)
    up_sign = int_prop("UpAxisSign", 1)
    front_axis = int_prop("FrontAxis", 2)
    front_sign = int_prop("FrontAxisSign", 1)
    coord_axis = int_prop("CoordAxis", 0)
    coord_sign = int_prop("CoordAxisSign", 1)
    unit_scale = float_prop("UnitScaleFactor", 1.0)

    axes_valid = {up_axis, front_axis, coord_axis} == {0, 1, 2}
    signs_valid = all(s in (-1, 1) for s in (up_sign, front_sign, coord_sign))
    unit_valid = math.isfinite(unit_scale) and unit_scale > 0.0
    valid = axes_valid and signs_valid and unit_valid
    if not valid:
        up_axis, up_sign = 1, 1
        front_axis, front_sign = 2, 1
        coord_axis, coord_sign = 0, 1
        unit_scale = 1.0

    # C * (source_sign * source_axis) = target_role_axis。
    # target Coord/Up/Front 分别固定为 +X/+Y/+Z。
    matrix = [0.0] * 16
    matrix[15] = 1.0
    for source_axis, source_sign, target_axis in (
            (coord_axis, coord_sign, 0),
            (up_axis, up_sign, 1),
            (front_axis, front_sign, 2)):
        matrix[target_axis * 4 + source_axis] = float(source_sign) * unit_scale

    return AxisSystem(up_axis, up_sign, front_axis, front_sign,
                      coord_axis, coord_sign, unit_scale, matrix, valid)


# --------------------------------------------------------------------------- 变换装配
def _model_local(model):
    # 函数定义在文件后部，但模块加载完成后调用时已经可用。统一走完整 FBX 局部
    # 变换，尤其要保留 UE/Maya 导出器常写在根节点上的 PreRotation。
    return _full_local(_bone_components(model), *_rest_trs(model))


def _geometric(model):
    t = _p70(model, "GeometricTranslation") or [0.0, 0.0, 0.0]
    r = _p70(model, "GeometricRotation") or [0.0, 0.0, 0.0]
    s = _p70(model, "GeometricScaling") or [1.0, 1.0, 1.0]
    if t[:3] == [0, 0, 0] and r[:3] == [0, 0, 0] and s[:3] == [1, 1, 1]:
        return None
    return _local_matrix(t[:3], (r + [0, 0, 0])[:3], (s + [1, 1, 1])[:3])


def _scene_ids(root):
    """收集 Objects 里各类对象 id,以及 Connections 的 OO 关系。"""
    objects = root.first("Objects")
    connections = root.first("Connections")
    models, geom_ids, mat_ids = {}, set(), set()
    if objects:
        for c in objects.children:
            if not c.props or not isinstance(c.props[0], int):
                continue
            oid = c.props[0]
            if c.name == "Model":
                models[oid] = c
            elif c.name == "Geometry":
                geom_ids.add(oid)
            elif c.name == "Material":
                mat_ids.add(oid)
    oo = []  # (child, parent)
    if connections:
        for c in connections.children:
            if c.name == "C" and len(c.props) >= 3 and c.props[0] == "OO":
                oo.append((c.props[1], c.props[2]))
    return models, geom_ids, mat_ids, oo


def _op_connections(root):
    """Connections 里的 OP(对象->属性)关系: [(child, parent, prop_str), ...]。
    动画用: AnimCurve--OP(d|X/Y/Z)-->AnimCurveNode--OP(Lcl *)-->Model。"""
    connections = root.first("Connections")
    out = []
    if connections:
        for c in connections.children:
            if c.name == "C" and len(c.props) >= 4 and c.props[0] == "OP":
                out.append((c.props[1], c.props[2], str(c.props[3])))
    return out


def _build_transforms(root, axis_system=None):
    """geometryId -> 归一到内部轴系的世界矩阵(含 Geometric)。"""
    models, geom_ids, _mat_ids, oo = _scene_ids(root)
    axis_system = axis_system or _axis_system(root)
    if not models or not oo:
        return {gid: axis_system.matrix for gid in geom_ids}

    geom_to_model, model_parent = {}, {}
    for child, parent in oo:
        if child in geom_ids and parent in models:
            geom_to_model[child] = parent
        elif child in models and parent in models:
            model_parent[child] = parent

    local_cache, world_cache = {}, {}

    def model_world(mid, stack):
        if mid in world_cache:
            return world_cache[mid]
        if mid in stack:
            return _identity()
        stack.add(mid)
        loc = local_cache.get(mid)
        if loc is None:
            loc = local_cache[mid] = _model_local(models[mid])
        pid = model_parent.get(mid)
        w = _matmul(model_world(pid, stack), loc) if pid in models else loc
        stack.discard(mid)
        world_cache[mid] = w
        return w

    out = {}
    for gid, mid in geom_to_model.items():
        try:
            w = model_world(mid, set())
            geo = _geometric(models[mid])
            w = _matmul(w, geo) if geo else w
            out[gid] = _matmul(axis_system.matrix, w)
        except Exception:
            out[gid] = axis_system.matrix
    return out


# --------------------------------------------------------------------------- 材质 / 贴图
def _texture_filenames(tex_node):
    out = []
    for key in ("RelativeFilename", "FileName", "Filename"):
        n = tex_node.first(key)
        if n and n.props and isinstance(n.props[0], str) and n.props[0]:
            out.append(n.props[0])
    return out


def _resolve_texture(stored_list, fbx_path):
    if not stored_list:
        return None
    fbx_dir = os.path.dirname(fbx_path)
    root = os.path.dirname(fbx_dir)  # 资产根(fbx 在 .../<asset>/FBX/)
    cands = []
    for stored in stored_list:
        s = stored.replace("\\", "/")
        base = os.path.basename(s)
        cands += [s,
                  os.path.join(fbx_dir, s),
                  os.path.join(fbx_dir, base),
                  os.path.join(root, "Texture", base),
                  os.path.join(root, "Textures", base),
                  os.path.join(root, "Images", base)]
    for c in cands:
        try:
            if c and os.path.isfile(c):
                return c.replace("\\", "/")
        except Exception:
            pass
    return None


def _material_color(mat_node):
    c = _p70(mat_node, "DiffuseColor") or _p70(mat_node, "Diffuse")
    if c and len(c) >= 3:
        return (float(c[0]), float(c[1]), float(c[2]))
    return None


def _parse_materials(root, fbx_path):
    """{materialId: {'color':(r,g,b)|None, 'texture':path|None}}。"""
    objects = root.first("Objects")
    connections = root.first("Connections")
    if not objects:
        return {}
    textures, mats = {}, {}
    for c in objects.children:
        if not c.props or not isinstance(c.props[0], int):
            continue
        oid = c.props[0]
        if c.name == "Material":
            mats[oid] = c
        elif c.name == "Texture":
            fns = _texture_filenames(c)
            if fns:
                textures[oid] = fns
    mat_tex = {}  # materialId -> [filenames]
    if connections:
        for c in connections.children:
            if c.name != "C" or len(c.props) < 3 or c.props[0] != "OP":
                continue
            child_id, parent_id = c.props[1], c.props[2]
            prop = str(c.props[3]) if len(c.props) > 3 else ""
            if child_id in textures and parent_id in mats and "Diffuse" in prop:
                mat_tex[parent_id] = textures[child_id]
    out = {}
    for mid, node in mats.items():
        out[mid] = {
            "color": _material_color(node),
            "texture": _resolve_texture(mat_tex.get(mid), fbx_path),
        }
    return out


def _geom_material_lists(root):
    """{geomId: [materialId,...]}(连接顺序;LayerElementMaterial 的索引指向它)。"""
    models, geom_ids, mat_ids, oo = _scene_ids(root)
    if not mat_ids or not oo:
        return {}
    model_mats, geom_to_model = {}, {}
    for child, parent in oo:
        if child in mat_ids and parent in models:
            model_mats.setdefault(parent, []).append(child)
        elif child in geom_ids and parent in models:
            geom_to_model[child] = parent
    out = {}
    for gid, mid in geom_to_model.items():
        out[gid] = model_mats.get(mid, [])
    return out


# --------------------------------------------------------------------------- 每角点索引器
def _layer_indexer(geom, layer_name, data_name, idx_name, comp, default_ref):
    layer = geom.first(layer_name)
    if not layer:
        return None
    darr = layer.first(data_name)
    if not darr or not darr.props:
        return None
    data = darr.props[0]
    mit = layer.first("MappingInformationType")
    rit = layer.first("ReferenceInformationType")
    mapping = mit.props[0] if (mit and mit.props) else "ByPolygonVertex"
    ref = rit.props[0] if (rit and rit.props) else default_ref
    didx = None
    if not ref.startswith("Direct"):
        ii = layer.first(idx_name)
        didx = ii.props[0] if (ii and ii.props) else None
    by_vertex = mapping.startswith("ByVert") or mapping.startswith("ByControl")

    def index(cpi, pvc):
        key = cpi if by_vertex else pvc
        if didx is not None:
            if key < 0 or key >= len(didx):
                return None
            key = didx[key]
        base = key * comp
        if base < 0 or base + comp - 1 >= len(data):
            return None
        return base

    return data, index


def _normal_indexer(geom):
    return _layer_indexer(geom, "LayerElementNormal", "Normals", "NormalsIndex", 3, "Direct")


def _uv_indexer(geom):
    return _layer_indexer(geom, "LayerElementUV", "UV", "UVIndex", 2, "IndexToDirect")


def _material_layer(geom):
    """返回 (mapping, materials_int_array) 或 None。"""
    layer = geom.first("LayerElementMaterial")
    if not layer:
        return None
    marr = layer.first("Materials")
    mit = layer.first("MappingInformationType")
    mapping = mit.props[0] if (mit and mit.props) else "AllSame"
    arr = marr.props[0] if (marr and marr.props) else None
    return mapping, arr


# --------------------------------------------------------------------------- MeshData
_DEFAULT_COLOR = (0.78, 0.78, 0.80)
_FPV = 8  # floats per vertex: pos3 + nrm3 + uv2


class Submesh(object):
    __slots__ = ("first", "count", "color", "texture")

    def __init__(self, first, count, color, texture):
        self.first = first      # 起始角点索引(用于 glDrawArrays first)
        self.count = count      # 角点数(用于 glDrawArrays count)
        self.color = color      # (r,g,b) 固有色
        self.texture = texture  # 漫反射贴图文件路径 或 None


class MeshData(object):
    __slots__ = ("interleaved", "submeshes", "bbox_min", "bbox_max", "vertex_count",
                 "axis_system")

    def __init__(self, interleaved, submeshes, bbox_min, bbox_max, vertex_count,
                 axis_system=None):
        self.interleaved = interleaved   # bytes: [px,py,pz,nx,ny,nz,u,v] * vertex_count (float32)
        self.submeshes = submeshes       # list[Submesh]
        self.bbox_min = bbox_min
        self.bbox_max = bbox_max
        self.vertex_count = vertex_count
        self.axis_system = axis_system

    def center_radius(self):
        cx = (self.bbox_min[0] + self.bbox_max[0]) * 0.5
        cy = (self.bbox_min[1] + self.bbox_max[1]) * 0.5
        cz = (self.bbox_min[2] + self.bbox_max[2]) * 0.5
        dx = self.bbox_max[0] - self.bbox_min[0]
        dy = self.bbox_max[1] - self.bbox_min[1]
        dz = self.bbox_max[2] - self.bbox_min[2]
        radius = 0.5 * math.sqrt(dx * dx + dy * dy + dz * dz)
        return (cx, cy, cz), (radius if radius > 1e-6 else 1.0)


def _normalize(x, y, z):
    n = math.sqrt(x * x + y * y + z * z)
    if n < 1e-12:
        return 0.0, 0.0, 1.0
    return x / n, y / n, z / n


# =========================================================================== 动画
# 设计:把"刚体变换动画"视为"单骨骼蒙皮",与"骨骼蒙皮动画"统一到一条 GPU 蒙皮路径。
# 解析阶段预烘焙每采样帧的骨骼矩阵调色板(palette),播放时只切帧上传 uniform。
# 详见同目录 am_previewGLWidget.py 与计划文件。

_FBX_TIME_UNIT = 46186158000  # FBX 时间刻度: 每秒 ticks

_AFPV = 16  # 蒙皮顶点 floats: pos3 + nrm3 + uv2 + boneIdx4 + boneWeight4

# TimeMode 枚举 -> fps(缺省/越界 -> 30;14=eCustom 另读 CustomFrameRate)
_TIMEMODE_FPS = {
    0: 30.0, 1: 120.0, 2: 100.0, 3: 60.0, 4: 50.0, 5: 48.0, 6: 30.0, 7: 30.0,
    8: 29.97, 9: 29.97, 10: 25.0, 11: 24.0, 12: 1000.0, 13: 23.976,
    15: 96.0, 16: 72.0, 17: 59.94,
}


class AnimData(object):
    """动画预览数据:蒙皮顶点缓冲 + 每帧骨骼调色板。坐标为几何局部(原始控制点),
    由 palette 里的 SkinMat 变换到世界。"""
    __slots__ = ("interleaved", "submeshes", "palettes", "frame_count",
                 "bone_count", "fps", "bbox_min", "bbox_max")

    def __init__(self, interleaved, submeshes, palettes, frame_count,
                 bone_count, fps, bbox_min, bbox_max):
        self.interleaved = interleaved   # bytes: [pos3,nrm3,uv2,boneIdx4,boneW4]*N (float32)
        self.submeshes = submeshes       # list[Submesh](first/count 为顶点序号)
        self.palettes = palettes         # list[bytes]: 每帧 bone_count*12 float32(每骨3行/4×3仿射)
        self.frame_count = frame_count
        self.bone_count = bone_count
        self.fps = fps
        self.bbox_min = bbox_min
        self.bbox_max = bbox_max


def _iter_triangles(pvi):
    """遍历 PolygonVertexIndex,产出 (poly_index, a, b, c),角点为 (cpi, pvc)。
    与 read() 静态循环同样的扇形三角化,但抽出来给蒙皮装配复用。"""
    poly = []
    poly_index = 0
    for pvc in range(len(pvi)):
        idx = pvi[pvc]
        if idx < 0:
            poly.append((~idx, pvc))
            for k in range(1, len(poly) - 1):
                yield poly_index, poly[0], poly[k], poly[k + 1]
            poly = []
            poly_index += 1
        else:
            poly.append((idx, pvc))


def _parse_anim_curves(objects):
    """{curveId: (KeyTime[int64 array], KeyValueFloat[float array])}。"""
    curves = {}
    for c in objects.children:
        if c.name != "AnimationCurve" or not c.props or not isinstance(c.props[0], int):
            continue
        kt = c.first("KeyTime")
        kv = c.first("KeyValueFloat")
        if not kt or not kt.props or not kv or not kv.props:
            continue
        curves[c.props[0]] = (kt.props[0], kv.props[0])
    return curves


def _parse_curve_nodes(objects, op):
    """{curveNodeId: {'X':curveId|None,'Y':..,'Z':.., 'dx':默认|None,'dy':..,'dz':..}}。"""
    nodes = {}
    for c in objects.children:
        if c.name != "AnimationCurveNode" or not c.props or not isinstance(c.props[0], int):
            continue
        dx = _p70(c, "d|X"); dy = _p70(c, "d|Y"); dz = _p70(c, "d|Z")
        nodes[c.props[0]] = {
            "X": None, "Y": None, "Z": None,
            "dx": (dx[0] if dx else None),
            "dy": (dy[0] if dy else None),
            "dz": (dz[0] if dz else None),
        }
    for child, parent, prop in op:  # AnimCurve(child) --OP(d|X/Y/Z)--> AnimCurveNode(parent)
        nd = nodes.get(parent)
        if nd is None:
            continue
        if prop == "d|X":
            nd["X"] = child
        elif prop == "d|Y":
            nd["Y"] = child
        elif prop == "d|Z":
            nd["Z"] = child
    return nodes


def _map_channels_to_models(op, curve_nodes):
    """{modelId: {'T':curveNodeId,'R':..,'S':..}}。"""
    out = {}
    _key = {"Lcl Translation": "T", "Lcl Rotation": "R", "Lcl Scaling": "S"}
    for child, parent, prop in op:  # AnimCurveNode(child) --OP(Lcl *)--> Model(parent)
        if child not in curve_nodes:
            continue
        k = _key.get(prop)
        if k:
            out.setdefault(parent, {})[k] = child
    return out


def _sample_value(kt, kv, t):
    """单条曲线在时刻 t(FBX ticks)的线性插值;端点钳制,空/单键取常量。"""
    n = len(kt)
    if n == 0:
        return 0.0
    if n == 1 or t <= kt[0]:
        return kv[0]
    if t >= kt[n - 1]:
        return kv[n - 1]
    lo, hi = 0, n - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if kt[mid] <= t:
            lo = mid
        else:
            hi = mid
    t0, t1 = kt[lo], kt[hi]
    if t1 == t0:
        return kv[lo]
    f = (t - t0) / float(t1 - t0)
    return kv[lo] + (kv[hi] - kv[lo]) * f


def _eval_channel(model, nid, curve_nodes, curves, t, p70name, default):
    """求某 Model 的 T/R/S 三分量在时刻 t 的值:有曲线用采样,否则 curveNode 默认,
    再否则 Properties70 静止值,最后给定默认。"""
    cn = curve_nodes.get(nid) if nid is not None else None
    if cn is None:
        v = _p70(model, p70name)
        if v and len(v) >= 3:
            return [float(v[0]), float(v[1]), float(v[2])]
        return list(default)
    out = []
    for axis, dkey, dval in (("X", "dx", default[0]),
                             ("Y", "dy", default[1]),
                             ("Z", "dz", default[2])):
        cid = cn.get(axis)
        if cid is not None and cid in curves:
            kt, kv = curves[cid]
            out.append(_sample_value(kt, kv, t))
        else:
            dv = cn.get(dkey)
            out.append(float(dv) if dv is not None else dval)
    return out


def _norm_bone_name(s):
    """对象名规范化:去 '\x00\x01<类名>' 后缀,再去命名空间 'ns:' 前缀。
    用于跨文件(绑定/动作)按骨骼名匹配:动作骨名常带 'BaSiTeV4_hi_rig:' 前缀。"""
    s = str(s)
    if "\x00\x01" in s:
        s = s.split("\x00\x01", 1)[0]
    elif "::" in s:
        s = s.split("::")[-1]
    if ":" in s:
        s = s.rsplit(":", 1)[-1]
    return s


def _v3(p, d):
    if p and len(p) >= 3:
        return [float(p[0]), float(p[1]), float(p[2])]
    return [float(d[0]), float(d[1]), float(d[2])]


def _euler(order, r):
    """按 RotationOrder(0=XYZ,1=XZY,2=YZX(?)...) 合成欧拉旋转(列向量约定)。
    顺序枚举遵循 FBX/Maya: 0 eXYZ,1 eXZY,2 eYZX,3 eYXZ,4 eZXY,5 eZYX(以旋转应用先后)。"""
    rx, ry, rz = _rotx(r[0]), _roty(r[1]), _rotz(r[2])
    # 列向量约定: 先应用的在右。eXYZ => Rz*Ry*Rx。
    seq = {
        0: (rz, ry, rx),  # XYZ
        1: (ry, rz, rx),  # XZY
        2: (rz, rx, ry),  # YZX
        3: (ry, rx, rz),  # YXZ
        4: (rx, rz, ry),  # ZXY
        5: (rx, ry, rz),  # ZYX
    }.get(order, (rz, ry, rx))
    return _matmul(seq[0], _matmul(seq[1], seq[2]))


def _bone_components(node):
    """从 Model 节点抽出完整局部变换的固定分量(PreRotation/轴心/偏移/旋转顺序)。
    动画时只替换 t/r/s,这些分量恒定。"""
    order = _p70(node, "RotationOrder")
    return {
        "pre": _p70(node, "PreRotation"),
        "post": _p70(node, "PostRotation"),
        "roff": _p70(node, "RotationOffset"),
        "rpiv": _p70(node, "RotationPivot"),
        "soff": _p70(node, "ScalingOffset"),
        "spiv": _p70(node, "ScalingPivot"),
        "order": int(order[0]) if order else 0,
    }


def _full_local(comp, t, r, s):
    """完整 Maya/FBX 局部变换(列向量约定):
        T · Roff · Rp · Rpre · R · Rpost⁻¹ · Rp⁻¹ · Soff · Sp · S · Sp⁻¹
    comp 为 _bone_components 固定分量;t/r/s 为(可被动画替换的) Lcl 平移/旋转/缩放。
    PreRotation(jointOrient) 固定 XYZ;R 按 RotationOrder。多数骨轴心为 0 → 退化为 T·Rpre·R·S。"""
    M = _translation(t)
    roff = comp.get("roff"); rpiv = comp.get("rpiv")
    soff = comp.get("soff"); spiv = comp.get("spiv")
    pre = comp.get("pre"); post = comp.get("post")
    order = comp.get("order", 0)
    if roff:
        M = _matmul(M, _translation(_v3(roff, (0, 0, 0))))
    if rpiv:
        M = _matmul(M, _translation(_v3(rpiv, (0, 0, 0))))
    if pre:
        M = _matmul(M, _euler(0, _v3(pre, (0, 0, 0))))
    M = _matmul(M, _euler(order, r))
    if post:
        M = _matmul(M, _inverse(_euler(0, _v3(post, (0, 0, 0)))))
    if rpiv:
        rp = _v3(rpiv, (0, 0, 0)); M = _matmul(M, _translation([-rp[0], -rp[1], -rp[2]]))
    if soff:
        M = _matmul(M, _translation(_v3(soff, (0, 0, 0))))
    if spiv:
        M = _matmul(M, _translation(_v3(spiv, (0, 0, 0))))
    M = _matmul(M, _scale(s))
    if spiv:
        sp = _v3(spiv, (0, 0, 0)); M = _matmul(M, _translation([-sp[0], -sp[1], -sp[2]]))
    return M


def _rest_trs(node):
    """Model 的静止 Lcl T/R/S(Properties70)。"""
    return (_v3(_p70(node, "Lcl Translation"), (0, 0, 0)),
            _v3(_p70(node, "Lcl Rotation"), (0, 0, 0)),
            _v3(_p70(node, "Lcl Scaling"), (1, 1, 1)))


def _time_range_and_fps(root, objects, curves):
    """-> (t0, t1, fps) FBX ticks;无可用区间返回 None。"""
    gs = root.first("GlobalSettings")
    fps = 30.0
    if gs:
        tm = _p70(gs, "TimeMode")
        mode = int(tm[0]) if tm else 0
        if mode == 14:
            cfr = _p70(gs, "CustomFrameRate")
            fps = float(cfr[0]) if (cfr and cfr[0] > 0) else 30.0
        elif mode != 0:
            fps = _TIMEMODE_FPS.get(mode, 30.0)
    t0 = t1 = None
    for c in objects.children:
        if c.name == "AnimationStack":
            ls = _p70(c, "LocalStart"); le = _p70(c, "LocalStop")
            if ls and le:
                t0, t1 = int(ls[0]), int(le[0])
                break
    if t0 is None or t1 is None or t1 <= t0:
        lo = hi = None
        for kt, kv in curves.values():
            if len(kt) == 0:
                continue
            a, b = kt[0], kt[len(kt) - 1]
            lo = a if lo is None else min(lo, a)
            hi = b if hi is None else max(hi, b)
        if lo is None or hi is None or hi <= lo:
            return None
        t0, t1 = lo, hi
    return t0, t1, fps


def _parse_deformers(objects):
    """-> (skins{id:node}, clusters{id:node})。Skin/Cluster 节点名都是 Deformer,
    靠 props[2] 区分。"""
    skins, clusters = {}, {}
    for c in objects.children:
        if c.name != "Deformer" or not c.props or not isinstance(c.props[0], int):
            continue
        cls = str(c.props[2]) if len(c.props) > 2 else ""
        if cls == "Skin":
            skins[c.props[0]] = c
        elif cls == "Cluster":
            clusters[c.props[0]] = c
    return skins, clusters


def _cluster_data(node):
    """-> (indexes, weights)。Cluster 只取每控制点索引与权重;bind 改用骨骼自身的
    rest 世界(经完整局部公式),不用 cluster 的 Transform/TransformLink(它们处于
    FBX 内部轴系,与控制点不在同一空间)。"""
    idx_n = node.first("Indexes")
    w_n = node.first("Weights")
    indexes = idx_n.props[0] if (idx_n and idx_n.props) else None
    weights = w_n.props[0] if (w_n and w_n.props) else None
    return indexes, weights


def _finalize_influences(inf, default_slot):
    """inf: [(slot, weight),...] -> ((i0,i1,i2,i3),(w0,w1,w2,w3)) 取前4归一化。
    无有效权重则回退该几何的 default_slot(权重1)。"""
    inf = [iw for iw in inf if iw[1] > 0.0]
    inf.sort(key=lambda iw: iw[1], reverse=True)
    inf = inf[:4]
    tot = 0.0
    for _, w in inf:
        tot += w
    if tot <= 1e-8:
        return (default_slot, 0, 0, 0), (1.0, 0.0, 0.0, 0.0)
    idxs, wts = [], []
    for s, w in inf:
        idxs.append(s); wts.append(w / tot)
    while len(idxs) < 4:
        idxs.append(0); wts.append(0.0)
    return (idxs[0], idxs[1], idxs[2], idxs[3]), (wts[0], wts[1], wts[2], wts[3])


class SkinData(object):
    """绑定文件的蒙皮数据(与具体动作无关,可缓存):世界烘焙的蒙皮顶点缓冲 +
    完整关节层级(用于套用动作骨骼) + 每调色板骨的 invBind(=inverse(骨 rest 世界))。
    顶点用与静态 read() 相同的网格世界烘焙 -> 静止姿势严格等于静态预览。"""
    __slots__ = ("interleaved", "submeshes", "bbox_min", "bbox_max",
                 "joint_parent", "joint_name", "joint_comp", "joint_trs",
                 "joint_rest_local", "joint_order",
                 "bone_count", "bone_joint", "bone_invbind", "axis_system")

    def __init__(self, interleaved, submeshes, bbox_min, bbox_max,
                 joint_parent, joint_name, joint_comp, joint_trs,
                 joint_rest_local, joint_order, bone_count, bone_joint, bone_invbind,
                 axis_system=None):
        self.interleaved = interleaved
        self.submeshes = submeshes
        self.bbox_min = bbox_min
        self.bbox_max = bbox_max
        self.joint_parent = joint_parent          # list[int] 父关节序号/-1
        self.joint_name = joint_name              # list[str] 规范化名
        self.joint_comp = joint_comp              # list[dict] 固定局部分量
        self.joint_trs = joint_trs                # list[(t,r,s)] 静止 Lcl
        self.joint_rest_local = joint_rest_local  # list[16f] 静止局部矩阵(缓存)
        self.joint_order = joint_order            # list[int] 父先于子
        self.bone_count = bone_count
        self.bone_joint = bone_joint              # list[int] 调色板骨->关节序号
        self.bone_invbind = bone_invbind          # list[16f] inverse(骨 rest 世界)
        self.axis_system = axis_system


def _topo_order(parent):
    """parent: list[int](-1 为根) -> 父先于子的遍历序(成环兜底补末尾)。"""
    n = len(parent)
    children = [[] for _ in range(n)]
    roots = []
    for i, p in enumerate(parent):
        if 0 <= p < n and p != i:
            children[p].append(i)
        else:
            roots.append(i)
    order, seen = [], [False] * n
    stack = list(reversed(roots))
    while stack:
        j = stack.pop()
        if seen[j]:
            continue
        seen[j] = True
        order.append(j)
        for c in reversed(children[j]):
            if not seen[c]:
                stack.append(c)
    for i in range(n):
        if not seen[i]:
            order.append(i)
    return order


def build_skin(root, objects, path):
    """构建 SkinData(蒙皮网格 + 关节层级)。无 skin 返回 None。"""
    axis_system = _axis_system(root)
    models, geom_ids, mat_ids, oo = _scene_ids(root)
    if not models:
        return None
    skins, clusters = _parse_deformers(objects)
    if not skins or not clusters:
        return None

    model_parent, geom_to_model = {}, {}
    skin_to_geom, cluster_to_skin, cluster_to_bone = {}, {}, {}
    for child, parent in oo:
        if child in models and parent in models:
            model_parent[child] = parent
        elif child in geom_ids and parent in models:
            geom_to_model[child] = parent
        elif child in skins and parent in geom_ids:
            skin_to_geom[child] = parent
        elif child in clusters and parent in skins:
            cluster_to_skin[child] = parent
        elif child in models and parent in clusters:   # 骨是 child,Cluster 是 parent
            cluster_to_bone[parent] = child
    geom_clusters = {}
    for cid, sid in cluster_to_skin.items():
        gid = skin_to_geom.get(sid)
        if gid is not None:
            geom_clusters.setdefault(gid, []).append(cid)
    if not geom_clusters:
        return None

    # 关节表 = 所有 Model
    model_ids = list(models.keys())
    jidx = {mid: i for i, mid in enumerate(model_ids)}
    joint_parent, joint_name, joint_comp, joint_trs = [], [], [], []
    for mid in model_ids:
        node = models[mid]
        pid = model_parent.get(mid)
        joint_parent.append(jidx.get(pid, -1) if pid is not None else -1)
        joint_name.append(_norm_bone_name(node.props[1] if len(node.props) > 1 else mid))
        joint_comp.append(_bone_components(node))
        joint_trs.append(_rest_trs(node))
    joint_order = _topo_order(joint_parent)
    joint_rest_local = [_full_local(joint_comp[j], *joint_trs[j])
                        for j in range(len(model_ids))]
    rest_world = [None] * len(model_ids)
    for j in joint_order:
        p = joint_parent[j]
        rest_world[j] = (_matmul(axis_system.matrix, joint_rest_local[j]) if p < 0
                         else _matmul(rest_world[p], joint_rest_local[j]))

    xforms = _build_transforms(root, axis_system)
    geom_mats = _geom_material_lists(root)
    try:
        mat_info = _parse_materials(root, path)
    except Exception:
        mat_info = {}

    bone_joint, joint_to_bone = [], {}

    def palette_for(joint_index):
        p = joint_to_bone.get(joint_index)
        if p is None:
            p = len(bone_joint)
            joint_to_bone[joint_index] = p
            bone_joint.append(joint_index)
        return p

    buckets, bucket_order = {}, []

    def bucket_for(matid):
        info = mat_info.get(matid) if matid is not None else None
        color = (info.get("color") if info else None) or _DEFAULT_COLOR
        texture = info.get("texture") if info else None
        key = (color, texture)
        b = buckets.get(key)
        if b is None:
            b = buckets[key] = array.array('f')
            bucket_order.append(key)
        return b

    inf_ = float("inf")
    min_x = min_y = min_z = inf_
    max_x = max_y = max_z = -inf_
    placed = 0

    for geom in objects.children:
        if geom.name != "Geometry":
            continue
        vnode = geom.first("Vertices")
        pnode = geom.first("PolygonVertexIndex")
        if not vnode or not vnode.props or not pnode or not pnode.props:
            continue
        verts = vnode.props[0]
        pvi = pnode.props[0]
        if len(verts) < 9 or len(pvi) < 3:
            continue
        gid = geom.props[0] if geom.props and isinstance(geom.props[0], int) else None
        Wmesh = xforms.get(gid) or _identity()   # 与静态 read() 一致 -> 静止==静态

        # 顶点影响(引用调色板骨序号)
        infl = {}
        default_bone = None
        for cid in geom_clusters.get(gid, []):
            bone_mid = cluster_to_bone.get(cid)
            if bone_mid is None or bone_mid not in jidx:
                continue
            indexes, weights = _cluster_data(clusters[cid])
            if indexes is None or weights is None:
                continue
            bp = palette_for(jidx[bone_mid])
            if default_bone is None:
                default_bone = bp
            m = min(len(indexes), len(weights))
            for k in range(m):
                w = weights[k]
                if w != 0.0:
                    infl.setdefault(indexes[k], []).append((bp, float(w)))

        if default_bone is None:
            # 无蒙皮几何 -> 单骨骼 = 所属模型(权重 1)
            mm = geom_to_model.get(gid)
            if mm is None or mm not in jidx:
                _dbg("geom %r unskinned & no owning model -> skipped" % (gid,))
                continue
            default_bone = palette_for(jidx[mm])

        nrm = _normal_indexer(geom)
        normals, nindex = (nrm[0], nrm[1]) if nrm else (None, None)
        uvl = _uv_indexer(geom)
        uvs, uindex = (uvl[0], uvl[1]) if uvl else (None, None)
        mat_list = geom_mats.get(gid, [])
        matlayer = _material_layer(geom)

        def mat_for_poly(pi):
            if not mat_list:
                return None
            if matlayer is None:
                return mat_list[0]
            mapping, arr = matlayer
            if mapping.startswith("AllSame") or not arr:
                idx = arr[0] if arr else 0
            else:
                idx = arr[pi] if pi < len(arr) else 0
            if idx < 0 or idx >= len(mat_list):
                idx = 0
            return mat_list[idx]

        fin_cache = {}

        def bones_for(cpi):
            r = fin_cache.get(cpi)
            if r is None:
                il = infl.get(cpi)
                if il:
                    r = _finalize_influences(list(il), default_bone)
                else:
                    r = ((default_bone, 0, 0, 0), (1.0, 0.0, 0.0, 0.0))
                fin_cache[cpi] = r
            return r

        def cnrm(cpi, pvc):
            if normals is None:
                return None
            base = nindex(cpi, pvc)
            if base is None:
                return None
            nx, ny, nz = _xform_dir(Wmesh, normals[base], normals[base + 1], normals[base + 2])
            return _normalize(nx, ny, nz)

        def cuv(cpi, pvc):
            if uvs is None:
                return (0.0, 0.0)
            base = uindex(cpi, pvc)
            if base is None:
                return (0.0, 0.0)
            return (uvs[base], uvs[base + 1])

        for poly_index, a, b_, c in _iter_triangles(pvi):
            bucket = bucket_for(mat_for_poly(poly_index))
            tri = (a, b_, c)
            wp = []
            for cpi, pvc in tri:
                bb = cpi * 3
                wp.append(_xform_point(Wmesh, verts[bb], verts[bb + 1], verts[bb + 2]))
            n0 = cnrm(a[0], a[1]); n1 = cnrm(b_[0], b_[1]); n2 = cnrm(c[0], c[1])
            if n0 is None or n1 is None or n2 is None:
                p0, p1, p2 = wp
                ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
                vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
                n0 = n1 = n2 = _normalize(uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
            ns = (n0, n1, n2)
            uvw = (cuv(a[0], a[1]), cuv(b_[0], b_[1]), cuv(c[0], c[1]))
            for ci in range(3):
                cpi = tri[ci][0]
                px, py, pz = wp[ci]
                nx, ny, nz = ns[ci]
                tu, tv = uvw[ci]
                (i0, i1, i2, i3), (w0, w1, w2, w3) = bones_for(cpi)
                bucket.append(px); bucket.append(py); bucket.append(pz)
                bucket.append(nx); bucket.append(ny); bucket.append(nz)
                bucket.append(tu); bucket.append(tv)
                bucket.append(float(i0)); bucket.append(float(i1))
                bucket.append(float(i2)); bucket.append(float(i3))
                bucket.append(w0); bucket.append(w1); bucket.append(w2); bucket.append(w3)
                if px < min_x: min_x = px
                if py < min_y: min_y = py
                if pz < min_z: min_z = pz
                if px > max_x: max_x = px
                if py > max_y: max_y = py
                if pz > max_z: max_z = pz
        placed += 1

    if not bucket_order or not bone_joint or placed == 0:
        _dbg("build_skin: nothing assembled")
        return None

    out = array.array('f')
    submeshes = []
    for key in bucket_order:
        b = buckets[key]
        nverts = len(b) // _AFPV
        if nverts == 0:
            continue
        first = len(out) // _AFPV
        out.extend(b)
        color, texture = key
        submeshes.append(Submesh(first, nverts, color, texture))
    if not submeshes:
        return None

    bone_invbind = [_inverse(rest_world[bj]) for bj in bone_joint]
    _dbg("build_skin: geoms=%d joints=%d bones=%d verts=%d"
         % (placed, len(model_ids), len(bone_joint), len(out) // _AFPV))
    return SkinData(out.tobytes(), submeshes, (min_x, min_y, min_z), (max_x, max_y, max_z),
                    joint_parent, joint_name, joint_comp, joint_trs,
                    joint_rest_local, joint_order, len(bone_joint), bone_joint, bone_invbind,
                    axis_system)


class ActionData(object):
    """动作文件的骨骼动画(与具体绑定无关):按规范化骨名取动画 Lcl T/R/S。"""
    __slots__ = ("t0", "t1", "fps", "curves", "curve_nodes", "name_channels",
                 "name_node", "axis_system")

    def __init__(self, t0, t1, fps, curves, curve_nodes, name_channels, name_node,
                 axis_system=None):
        self.t0 = t0; self.t1 = t1; self.fps = fps
        self.curves = curves
        self.curve_nodes = curve_nodes
        self.name_channels = name_channels   # norm_name -> {'T':nid,'R':nid,'S':nid}
        self.name_node = name_node            # norm_name -> 动作 Model 节点(取 P70 默认)
        self.axis_system = axis_system


def build_action(root, objects):
    """构建 ActionData。无动画/无时间区间返回 None。"""
    models, geom_ids, mat_ids, oo = _scene_ids(root)
    if not models:
        return None
    curves = _parse_anim_curves(objects)
    if not curves:
        return None
    op = _op_connections(root)
    curve_nodes = _parse_curve_nodes(objects, op)
    channels = _map_channels_to_models(op, curve_nodes)
    if not channels:
        return None
    tr = _time_range_and_fps(root, objects, curves)
    if tr is None:
        return None
    name_channels, name_node = {}, {}
    for mid, ch in channels.items():
        node = models.get(mid)
        if node is None:
            continue
        nm = _norm_bone_name(node.props[1] if len(node.props) > 1 else mid)
        if nm not in name_channels:
            name_channels[nm] = ch
            name_node[nm] = node
    if not name_channels:
        return None
    return ActionData(tr[0], tr[1], tr[2], curves, curve_nodes, name_channels, name_node,
                      _axis_system(root))


def _action_trs(action, name, t):
    ch = action.name_channels[name]
    node = action.name_node[name]
    tt = _eval_channel(node, ch.get("T"), action.curve_nodes, action.curves, t,
                       "Lcl Translation", (0.0, 0.0, 0.0))
    rr = _eval_channel(node, ch.get("R"), action.curve_nodes, action.curves, t,
                       "Lcl Rotation", (0.0, 0.0, 0.0))
    ss = _eval_channel(node, ch.get("S"), action.curve_nodes, action.curves, t,
                       "Lcl Scaling", (1.0, 1.0, 1.0))
    return tt, rr, ss


def combine(skin, action):
    """把动作骨骼动画套用到绑定蒙皮上,逐采样帧烘焙骨骼调色板(每骨 12 float = 3 行)。
    动画世界 = rig 关节层级 + 动作 Lcl T/R/S(按规范化名匹配),未匹配关节用 rig 静止局部。"""
    J = len(skin.joint_parent)
    dur = (action.t1 - action.t0) / float(_FBX_TIME_UNIT)
    play_fps = action.fps if action.fps > 0 else 30.0
    n_frames = max(2, min(int(round(dur * play_fps)) + 1, 600))
    bc = skin.bone_count
    if bc * n_frames > 200000:
        n_frames = max(2, 200000 // bc)

    name_ch = action.name_channels
    # 动画骨骼优先使用动作文件中的 _bone_components(PreRotation/RotationOrder 等),
    # 以适配 UE/Maya 跨工具导出时骨骼固定分量可能不同的情况。
    action_comps = {}
    for nm in name_ch:
        act_node = action.name_node.get(nm)
        if act_node:
            action_comps[nm] = _bone_components(act_node)

    palettes = []
    action_axis = action.axis_system.matrix if action.axis_system else _identity()
    for f in range(n_frames):
        t = action.t0 + (action.t1 - action.t0) * (f / float(n_frames - 1))
        world = [None] * J
        for j in skin.joint_order:
            nm = skin.joint_name[j]
            if nm in name_ch:
                tt, rr, ss = _action_trs(action, nm, t)
                comp = action_comps.get(nm, skin.joint_comp[j])
                loc = _full_local(comp, tt, rr, ss)
            else:
                loc = skin.joint_rest_local[j]
            p = skin.joint_parent[j]
            # FBX 轴系是场景根级变换：只在层级根部应用一次，子节点自然继承。
            world[j] = (_matmul(action_axis, loc) if p < 0
                        else _matmul(world[p], loc))
        pal = array.array('f')
        for bp in range(bc):
            m = _matmul(world[skin.bone_joint[bp]], skin.bone_invbind[bp])
            pal.extend(m[0:12])   # 3 行(每行 4):列向量约定行主序,着色器用 dot 应用
        palettes.append(pal.tobytes())
    _dbg("combine: frames=%d bones=%d fps=%.3f verts=%d"
         % (n_frames, bc, play_fps, len(skin.interleaved) // (_AFPV * 4)))
    return AnimData(skin.interleaved, skin.submeshes, palettes, n_frames, bc,
                    play_fps, skin.bbox_min, skin.bbox_max)


def _build_anim(root, objects, path, static_bbox):
    """单文件自带动画(绑定+动作在同一文件):build_skin + build_action + combine。
    绑定文件无自带动画(如本项目的纯蒙皮 rig)则返回 None,上层走静态。"""
    skin = build_skin(root, objects, path)
    if skin is None:
        return None
    action = build_action(root, objects)
    if action is None:
        return None
    try:
        return combine(skin, action)
    except Exception as e:
        _dbg("combine failed -> static: %r" % (e,))
        return None


def read(path, want_anim=True):
    """解析 FBX，返回 (MeshData, AnimData|None)。失败抛 FbxParseError。
    want_anim=False 时只产出静态网格(缩略图最快路径,跳过自带动画解析)。"""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except (IOError, OSError) as e:
        raise FbxParseError("cannot read file: %s" % e)
    if not data:
        raise FbxParseError("empty file")

    root = _parse_tree(data)
    objects = root.first("Objects")
    if not objects:
        raise FbxParseError("no Objects section")

    axis_system = _axis_system(root)
    xforms = _build_transforms(root, axis_system)
    try:
        geom_mats = _geom_material_lists(root)
        mat_info = _parse_materials(root, path)
    except Exception:
        geom_mats, mat_info = {}, {}

    # 按材质(固有色+贴图)分桶,保持出现顺序
    buckets = {}
    bucket_order = []

    def bucket_for(matid):
        info = mat_info.get(matid) if matid is not None else None
        color = (info.get("color") if info else None) or _DEFAULT_COLOR
        texture = info.get("texture") if info else None
        key = (color, texture)
        b = buckets.get(key)
        if b is None:
            b = buckets[key] = array.array('f')
            bucket_order.append(key)
        return b

    inf = float("inf")
    min_x = min_y = min_z = inf
    max_x = max_y = max_z = -inf

    for geom in objects.children:
        if geom.name != "Geometry":
            continue
        vnode = geom.first("Vertices")
        pnode = geom.first("PolygonVertexIndex")
        if not vnode or not vnode.props or not pnode or not pnode.props:
            continue
        verts = vnode.props[0]
        pvi = pnode.props[0]
        if len(verts) < 9 or len(pvi) < 3:
            continue

        gid = geom.props[0] if geom.props and isinstance(geom.props[0], int) else None
        M = xforms.get(gid)

        nrm = _normal_indexer(geom)
        normals, nindex = (nrm[0], nrm[1]) if nrm else (None, None)
        uvl = _uv_indexer(geom)
        uvs, uindex = (uvl[0], uvl[1]) if uvl else (None, None)

        mat_list = geom_mats.get(gid, [])
        matlayer = _material_layer(geom)

        def mat_for_poly(p):
            if not mat_list:
                return None
            if matlayer is None:
                return mat_list[0]
            mapping, arr = matlayer
            if mapping.startswith("AllSame") or not arr:
                idx = arr[0] if arr else 0
            else:
                idx = arr[p] if p < len(arr) else 0
            if idx < 0 or idx >= len(mat_list):
                idx = 0
            return mat_list[idx]

        pcache = {}

        def world_pos(cpi):
            p = pcache.get(cpi)
            if p is None:
                b = cpi * 3
                x, y, z = verts[b], verts[b + 1], verts[b + 2]
                p = _xform_point(M, x, y, z) if M else (x, y, z)
                pcache[cpi] = p
            return p

        def corner_normal(cpi, pvc):
            if normals is None:
                return None
            base = nindex(cpi, pvc)
            if base is None:
                return None
            nx, ny, nz = normals[base], normals[base + 1], normals[base + 2]
            if M:
                nx, ny, nz = _xform_dir(M, nx, ny, nz)
            return _normalize(nx, ny, nz)

        def corner_uv(cpi, pvc):
            if uvs is None:
                return (0.0, 0.0)
            base = uindex(cpi, pvc)
            if base is None:
                return (0.0, 0.0)
            return (uvs[base], uvs[base + 1])

        poly = []
        poly_index = 0
        for pvc in range(len(pvi)):
            idx = pvi[pvc]
            if idx < 0:
                poly.append((~idx, pvc))
                bucket = bucket_for(mat_for_poly(poly_index))
                for k in range(1, len(poly) - 1):
                    a, b_, c = poly[0], poly[k], poly[k + 1]
                    p0 = world_pos(a[0]); p1 = world_pos(b_[0]); p2 = world_pos(c[0])
                    n0 = corner_normal(a[0], a[1])
                    n1 = corner_normal(b_[0], b_[1])
                    n2 = corner_normal(c[0], c[1])
                    if n0 is None or n1 is None or n2 is None:
                        ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
                        vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
                        n0 = n1 = n2 = _normalize(uy * vz - uz * vy,
                                                  uz * vx - ux * vz,
                                                  ux * vy - uy * vx)
                    t0 = corner_uv(a[0], a[1])
                    t1 = corner_uv(b_[0], b_[1])
                    t2 = corner_uv(c[0], c[1])
                    for (px, py, pz), (nx, ny, nz), (tu, tv) in (
                            (p0, n0, t0), (p1, n1, t1), (p2, n2, t2)):
                        bucket.append(px); bucket.append(py); bucket.append(pz)
                        bucket.append(nx); bucket.append(ny); bucket.append(nz)
                        bucket.append(tu); bucket.append(tv)
                        if px < min_x: min_x = px
                        if py < min_y: min_y = py
                        if pz < min_z: min_z = pz
                        if px > max_x: max_x = px
                        if py > max_y: max_y = py
                        if pz > max_z: max_z = pz
                poly = []
                poly_index += 1
            else:
                poly.append((idx, pvc))

    if not bucket_order:
        raise FbxParseError("no triangles extracted")

    out = array.array('f')
    submeshes = []
    for key in bucket_order:
        b = buckets[key]
        nverts = len(b) // _FPV
        if nverts == 0:
            continue
        first = len(out) // _FPV
        out.extend(b)
        color, texture = key
        submeshes.append(Submesh(first, nverts, color, texture))

    if not submeshes:
        raise FbxParseError("no triangles extracted")

    total = len(out) // _FPV
    bbox_min = (min_x, min_y, min_z)
    bbox_max = (max_x, max_y, max_z)
    md = MeshData(out.tobytes(), submeshes, bbox_min, bbox_max, total, axis_system)

    # 尝试动画解析(单文件自带动画):任何异常都吞掉,回退静态(md, None)。
    anim = None
    if want_anim:
        try:
            anim = _build_anim(root, objects, path, (bbox_min, bbox_max))
        except Exception as e:
            _dbg("anim build failed -> static: %r" % (e,))
            anim = None
    return md, anim


def _load_tree(path):
    """打开并解析 FBX 节点树 -> (root, objects)。失败抛 FbxParseError。"""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except (IOError, OSError) as e:
        raise FbxParseError("cannot read file: %s" % e)
    if not data:
        raise FbxParseError("empty file")
    root = _parse_tree(data)
    objects = root.first("Objects")
    if not objects:
        raise FbxParseError("no Objects section")
    return root, objects


def read_skin(path):
    """解析绑定文件的蒙皮数据(SkinData)。无 skin / 解析失败返回 None。"""
    try:
        root, objects = _load_tree(path)
        return build_skin(root, objects, path)
    except Exception as e:
        _dbg("read_skin failed: %r" % (e,))
        return None


def read_action(path):
    """解析动作文件的骨骼动画(ActionData)。无动画 / 解析失败返回 None。"""
    try:
        root, objects = _load_tree(path)
        return build_action(root, objects)
    except Exception as e:
        _dbg("read_action failed: %r" % (e,))
        return None
