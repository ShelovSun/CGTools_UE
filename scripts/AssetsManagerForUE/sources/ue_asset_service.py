#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""UE 最终资产包的发现、迁移、注册与视口放置服务。

磁盘扫描和文件复制可以在线程中执行；任何 ``unreal`` API 都必须由 UI
主线程调用。服务器约定优先为 ``<资产根>/UE/Content``，同时兼容旧试发布
时直接把 Content 相对内容放在 ``<资产根>/UE`` 的形式。
"""

from __future__ import absolute_import

import hashlib
import json
import os
import shutil
import uuid

from PySide6 import QtCore

try:
    import unreal
except ImportError:  # 允许在 UE 外做纯文件逻辑测试
    unreal = None


PACKAGE_EXTENSIONS = frozenset((".uasset", ".umap", ".uexp", ".ubulk", ".uptnl"))
PRIMARY_EXTENSIONS = frozenset((".uasset", ".umap"))
MANIFEST_NAMES = ("asset_manifest.json", "manifest.json", "ue_manifest.json")
COPY_CHUNK_SIZE = 4 * 1024 * 1024


class AssetConflictError(RuntimeError):
    pass


def _forward(path):
    return str(path or "").replace("\\", "/")


def asset_root_from_item_data(item_data):
    """从旧版数据库第 8 列 icon 路径反推资产根目录。"""
    try:
        icon_path = _forward(item_data[7])
    except (IndexError, TypeError):
        return ""
    marker = "/Icon/"
    index = icon_path.lower().find(marker.lower())
    if index >= 0:
        return icon_path[:index]
    return _forward(os.path.dirname(os.path.dirname(icon_path)))


def find_source_content_root(asset_root):
    """返回服务器 UE 发布内容根；找不到任何 UE 包时返回空字符串。"""
    ue_root = os.path.join(os.path.normpath(str(asset_root or "")), "UE")
    content_root = os.path.join(ue_root, "Content")
    if os.path.isdir(content_root):
        return os.path.normpath(content_root)
    if os.path.isdir(ue_root):
        for _root, _dirs, files in os.walk(ue_root):
            if any(os.path.splitext(name)[1].lower() in PRIMARY_EXTENSIONS for name in files):
                return os.path.normpath(ue_root)
    return ""


def _project_content_dir(project_content_dir=None):
    if project_content_dir:
        return os.path.abspath(os.path.normpath(str(project_content_dir)))
    if unreal is None:
        raise RuntimeError("当前不在 Unreal Editor 中，无法取得工程 Content 路径")
    value = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir())
    return os.path.abspath(os.path.normpath(str(value)))


def project_content_dir():
    """返回当前 UE 工程 Content 的绝对路径。"""
    return _project_content_dir()


def _read_manifest(asset_root, source_root):
    candidates = []
    ue_root = os.path.join(os.path.normpath(str(asset_root or "")), "UE")
    for base in (ue_root, source_root):
        if not base:
            continue
        for name in MANIFEST_NAMES:
            candidate = os.path.join(base, name)
            if candidate not in candidates:
                candidates.append(candidate)
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as stream:
                data = json.load(stream)
            if isinstance(data, dict):
                data["_manifest_path"] = _forward(path)
                return data
        except Exception as exc:
            return {"_manifest_path": _forward(path), "_manifest_error": str(exc)}
    return {}


def _object_path_from_relative(relative_path):
    rel = _forward(relative_path).lstrip("/")
    package_rel, extension = os.path.splitext(rel)
    if extension.lower() not in PRIMARY_EXTENSIONS:
        return ""
    asset_name = os.path.basename(package_rel)
    return "/Game/{0}.{1}".format(package_rel, asset_name)


def _normalize_object_path(value):
    value = _forward(value).strip()
    if not value:
        return ""
    if value.lower().endswith((".uasset", ".umap")):
        value = os.path.splitext(value)[0]
    if value.startswith("Game/"):
        value = "/" + value
    elif not value.startswith("/"):
        value = "/Game/" + value.lstrip("/")
    if "." not in value.rsplit("/", 1)[-1]:
        value = "{0}.{1}".format(value, value.rsplit("/", 1)[-1])
    return value


def build_import_plan(asset_root, project_content_dir=None):
    """建立一个可序列化的迁移计划，不调用任何 UE API。"""
    asset_root = os.path.abspath(os.path.normpath(str(asset_root or "")))
    target_root = _project_content_dir(project_content_dir)
    source_root = find_source_content_root(asset_root)
    plan = {
        "asset_root": _forward(asset_root),
        "source_root": _forward(source_root),
        "target_root": _forward(target_root),
        "files": [],
        "package_object_paths": [],
        "main_object_path": "",
        "manifest": {},
        "state": "missing",
        "message": u"没有找到 UE 发布目录",
    }
    if not source_root:
        return plan

    manifest = _read_manifest(asset_root, source_root)
    plan["manifest"] = manifest
    for root, dirs, names in os.walk(source_root):
        dirs.sort(key=str.lower)
        for name in sorted(names, key=str.lower):
            extension = os.path.splitext(name)[1].lower()
            if extension not in PACKAGE_EXTENSIONS:
                continue
            source = os.path.abspath(os.path.join(root, name))
            relative = os.path.relpath(source, source_root)
            if relative == os.pardir or relative.startswith(os.pardir + os.sep):
                continue
            target = os.path.abspath(os.path.join(target_root, relative))
            try:
                inside_target = os.path.commonpath((target_root, target)) == target_root
            except ValueError:
                inside_target = False
            if not inside_target:
                continue
            try:
                size = os.path.getsize(source)
            except OSError:
                size = 0
            entry = {
                "source": _forward(source),
                "target": _forward(target),
                "relative": _forward(relative),
                "size": int(size),
                "extension": extension,
            }
            plan["files"].append(entry)
            if extension in PRIMARY_EXTENSIONS:
                object_path = _object_path_from_relative(relative)
                if object_path:
                    plan["package_object_paths"].append(object_path)

    configured_main = (manifest.get("mainObjectPath") or manifest.get("main_object_path")
                       or manifest.get("mainPackage") or manifest.get("main_package"))
    plan["main_object_path"] = _normalize_object_path(configured_main)
    # 实时编辑器中先准备 sidecar，最后才让 .uasset/.umap 出现在 Content 目录。
    plan["files"].sort(key=lambda entry: (
        entry["extension"] in PRIMARY_EXTENSIONS,
        entry["relative"].lower(),
    ))
    return query_filesystem_state(plan)


def object_path_for_source_file(source_file, source_content_root):
    """把源 Content 目录下的包文件转换成当前工程对应的 /Game 对象路径。"""
    source_file = os.path.abspath(os.path.normpath(str(source_file or "")))
    source_content_root = os.path.abspath(
        os.path.normpath(str(source_content_root or "")))
    try:
        if os.path.commonpath((source_content_root, source_file)) != source_content_root:
            return ""
    except ValueError:
        return ""
    return _object_path_from_relative(os.path.relpath(source_file, source_content_root))


def build_folder_import_plan(source_folder, source_content_root,
                             project_content_dir=None):
    """为源 Content 根下的一个完整分类文件夹建立迁移计划。

    与普通资产的 ``<asset>/UE/Content`` 约定不同，蓝图库本身就是另一个
    UE 工程的 Content。目标路径必须相对于它的 Content 根保持不变，才能
    保留包内的 ``/Game/...`` 相互引用。一次计划会收集分类目录中的全部
    uasset/umap 及其 sidecar，任何一张卡片触发的都是同一个分类计划。
    """
    source_folder = os.path.abspath(os.path.normpath(str(source_folder or "")))
    source_content_root = os.path.abspath(
        os.path.normpath(str(source_content_root or "")))
    target_root = _project_content_dir(project_content_dir)
    plan = {
        "asset_root": _forward(source_folder),
        "source_root": _forward(source_folder),
        "source_content_root": _forward(source_content_root),
        "target_root": _forward(target_root),
        "target_folder": "",
        "package_path": "",
        "files": [],
        "package_object_paths": [],
        "main_object_path": "",
        "manifest": {},
        "state": "missing",
        "message": u"没有找到蓝图分类目录",
    }
    if not os.path.isdir(source_content_root):
        plan["message"] = u"蓝图库 Content 目录不可访问"
        return plan
    if not os.path.isdir(source_folder):
        return plan
    try:
        inside_source = (
            os.path.commonpath((source_content_root, source_folder))
            == source_content_root)
    except ValueError:
        inside_source = False
    if not inside_source:
        plan["state"] = "error"
        plan["message"] = u"蓝图分类目录不在配置的 Content 根目录中"
        return plan

    relative_folder = os.path.relpath(source_folder, source_content_root)
    target_folder = os.path.abspath(os.path.join(target_root, relative_folder))
    try:
        inside_target = (
            os.path.commonpath((target_root, target_folder)) == target_root
            and target_folder != target_root)
    except ValueError:
        inside_target = False
    if not inside_target:
        plan["state"] = "error"
        plan["message"] = u"蓝图分类的目标目录不安全"
        return plan
    plan["target_folder"] = _forward(target_folder)
    plan["package_path"] = "/Game/{0}".format(
        _forward(relative_folder).strip("/"))

    for root, dirs, names in os.walk(source_folder):
        dirs.sort(key=str.lower)
        for name in sorted(names, key=str.lower):
            extension = os.path.splitext(name)[1].lower()
            if extension not in PACKAGE_EXTENSIONS:
                continue
            source = os.path.abspath(os.path.join(root, name))
            relative = os.path.relpath(source, source_content_root)
            if relative == os.pardir or relative.startswith(os.pardir + os.sep):
                continue
            target = os.path.abspath(os.path.join(target_root, relative))
            try:
                inside_target = os.path.commonpath((target_root, target)) == target_root
            except ValueError:
                inside_target = False
            if not inside_target:
                continue
            try:
                size = os.path.getsize(source)
            except OSError:
                size = 0
            entry = {
                "source": _forward(source),
                "target": _forward(target),
                "relative": _forward(relative),
                "size": int(size),
                "extension": extension,
            }
            plan["files"].append(entry)
            if extension in PRIMARY_EXTENSIONS:
                object_path = _object_path_from_relative(relative)
                if object_path:
                    plan["package_object_paths"].append(object_path)

    # sidecar 先提交，主包最后提交，避免 UE 在复制未完成时发现半套资源。
    plan["files"].sort(key=lambda entry: (
        entry["extension"] in PRIMARY_EXTENSIONS,
        entry["relative"].lower(),
    ))
    return query_filesystem_state(plan)


def query_filesystem_state(plan):
    """用文件存在性/大小更新红、橙、绿状态；不会读取或加载 UE 包。"""
    files = plan.get("files") or []
    packages = plan.get("package_object_paths") or []
    if not files or not packages:
        plan["state"] = "missing"
        plan["message"] = u"UE 发布目录中没有 .uasset 或 .umap"
        return plan

    missing = []
    different = []
    existing = []
    for entry in files:
        target = entry["target"]
        if not os.path.isfile(target):
            missing.append(entry["relative"])
            continue
        try:
            target_size = os.path.getsize(target)
        except OSError:
            target_size = -1
        if target_size != entry["size"]:
            different.append(entry["relative"])
        else:
            existing.append(entry["relative"])

    plan["missing_files"] = missing
    plan["different_files"] = different
    plan["existing_files"] = existing
    if different:
        plan["state"] = "conflict"
        plan["message"] = u"工程内有 {0} 个同名但内容不同的文件".format(len(different))
    elif not missing:
        plan["state"] = "ready"
        plan["message"] = u"UE 包已在当前工程中"
    elif existing:
        plan["state"] = "partial"
        plan["message"] = u"已加载 {0}/{1} 个文件".format(len(existing), len(files))
    else:
        plan["state"] = "missing"
        plan["message"] = u"发现 {0} 个 UE 发布文件，等待加载".format(len(files))
    return plan


def _sha1(path, cancelled=None):
    digest = hashlib.sha1()
    with open(path, "rb") as stream:
        while True:
            if cancelled and cancelled():
                raise RuntimeError(u"操作已取消")
            chunk = stream.read(COPY_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _asset_class_name(object_path):
    try:
        data = unreal.EditorAssetLibrary.find_asset_data(object_path)
        class_path = data.asset_class_path
        return str(class_path.asset_name)
    except Exception:
        try:
            asset = unreal.EditorAssetLibrary.load_asset(object_path)
            return asset.get_class().get_name() if asset else ""
        except Exception:
            return ""


def _is_actor_blueprint(object_path):
    try:
        asset = unreal.EditorAssetLibrary.load_asset(object_path)
        generated_class = asset.generated_class() if asset else None
        default_object = unreal.get_default_object(generated_class) if generated_class else None
        return isinstance(default_object, unreal.Actor)
    except Exception:
        # 某些 UE/Python 版本不公开 generated_class；交给原生 CanDrop 做最终判断。
        return True


def resolve_placeable_object_path(plan):
    """按 Actor Blueprint > StaticMesh > SkeletalMesh 选择拖放主资产。"""
    if unreal is None:
        return ""
    configured = _normalize_object_path(plan.get("main_object_path"))
    if configured and unreal.EditorAssetLibrary.does_asset_exist(configured):
        return configured

    ranked = []
    for object_path in plan.get("package_object_paths") or []:
        try:
            if not unreal.EditorAssetLibrary.does_asset_exist(object_path):
                continue
        except Exception:
            continue
        class_name = _asset_class_name(object_path)
        if class_name in ("Blueprint", "AnimBlueprint"):
            if not _is_actor_blueprint(object_path):
                continue
            rank = 0
        elif class_name == "StaticMesh":
            rank = 1
        elif class_name == "SkeletalMesh":
            rank = 2
        else:
            continue
        ranked.append((rank, object_path.lower(), object_path))
    ranked.sort()
    return ranked[0][2] if ranked else ""


def refresh_asset_registry(plan, require_placeable=True):
    """在 UE 主线程刷新新复制的包并解析主资产，返回更新后的计划。"""
    if unreal is None:
        raise RuntimeError("当前不在 Unreal Editor 中")
    package_paths = plan.get("package_object_paths") or []
    scan_paths = sorted(set(path.rsplit("/", 1)[0].split(".", 1)[0] for path in package_paths))
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    try:
        registry.scan_paths_synchronous(scan_paths or ["/Game"], True, False)
    except TypeError:
        try:
            registry.scan_paths_synchronous(scan_paths or ["/Game"], True)
        except TypeError:
            registry.scan_paths_synchronous(scan_paths or ["/Game"])

    missing_packages = []
    for object_path in package_paths:
        try:
            if not unreal.EditorAssetLibrary.does_asset_exist(object_path):
                missing_packages.append(object_path)
        except Exception:
            missing_packages.append(object_path)
    if missing_packages:
        plan["state"] = "error"
        plan["message"] = u"文件已复制，但 UE 未识别 {0} 个包；请检查引擎版本和依赖".format(
            len(missing_packages))
        plan["missing_packages"] = missing_packages
        return plan

    plan["main_object_path"] = resolve_placeable_object_path(plan)
    if not require_placeable:
        plan["state"] = "ready"
        plan["message"] = u"分类蓝图已完整加载"
    elif plan["main_object_path"]:
        plan["state"] = "ready"
        plan["message"] = u"加载完成，可拖入关卡"
    else:
        plan["state"] = "partial"
        plan["message"] = u"加载完成；包中没有可直接放置的 Actor 蓝图或网格体"
    return plan


def _decode_bridge_result(result):
    """兼容 UE Python 对 return value + out parameter 的不同包装形式。"""
    if isinstance(result, tuple):
        success = False
        error = ""
        for value in result:
            if isinstance(value, bool) and not success:
                success = value
            elif isinstance(value, str) and value:
                error = value
        return success, error
    if isinstance(result, bool):
        return result, ""
    if isinstance(result, str):
        return False, result
    return bool(result), ""


def export_external_asset_thumbnail(asset_file_path, output_png_path):
    """通过原生桥读取外部 uasset 的嵌入缩略图并写入本机 PNG 缓存。"""
    if unreal is None:
        return False, u"当前不在 Unreal Editor 中"
    bridge = getattr(unreal, "CGToolsAssetBridgeLibrary", None)
    if bridge is None:
        return False, u"未启用 CGToolsAssetBridge 插件"
    export_method = getattr(bridge, "export_external_asset_thumbnail", None)
    if export_method is None:
        return False, u"CGToolsAssetBridge 版本低于 1.2.0，不支持外部缩略图"
    try:
        try:
            result = export_method(str(asset_file_path), str(output_png_path))
        except TypeError:
            result = export_method(str(asset_file_path), str(output_png_path), "")
        return _decode_bridge_result(result)
    except Exception as exc:
        return False, u"读取外部资产缩略图失败：{0}".format(exc)


def place_asset_at_cursor(object_path, screen_position=None):
    """调用原生桥在 Qt 鼠标松开位置执行 UE 官方 DropObjectsAtCoordinates。"""
    if unreal is None:
        return False, u"当前不在 Unreal Editor 中"
    bridge = getattr(unreal, "CGToolsAssetBridgeLibrary", None)
    if bridge is None:
        return False, u"未启用 CGToolsAssetBridge 插件，无法精确拖放到关卡视口"
    try:
        use_explicit_position = (
            screen_position is not None
            and hasattr(bridge, "place_asset_at_screen_position")
        )
        if use_explicit_position:
            screen_x, screen_y = int(screen_position[0]), int(screen_position[1])
            try:
                result = bridge.place_asset_at_screen_position(
                    str(object_path), screen_x, screen_y)
            except TypeError:
                result = bridge.place_asset_at_screen_position(
                    str(object_path), screen_x, screen_y, "")
        else:
            try:
                result = bridge.place_asset_at_cursor(str(object_path))
            except TypeError:
                result = bridge.place_asset_at_cursor(str(object_path), "")
    except Exception as exc:
        return False, u"视口放置失败：{0}".format(exc)
    success, error = _decode_bridge_result(result)
    if not success and not error:
        try:
            version = str(bridge.get_bridge_version())
        except Exception:
            version = u"未知"
        position_text = (u"，松手屏幕坐标={0},{1}".format(*screen_position)
                         if screen_position is not None else "")
        error = (u"原生桥返回失败但没有错误文本：资产={0}{1}，桥版本={2}。"
                 u"请确认已重新编译并启用 CGToolsAssetBridge 1.2.0。".format(
                     object_path, position_text, version))
        try:
            unreal.log_warning(error)
        except Exception:
            pass
    return success, error


def sync_to_content_browser(object_path):
    if unreal is None or not object_path:
        return False
    asset = unreal.EditorAssetLibrary.load_asset(object_path)
    if not asset:
        return False
    unreal.EditorAssetLibrary.sync_browser_to_objects([object_path])
    return True


class AssetStateWorker(QtCore.QObject):
    itemScanned = QtCore.Signal(int, str, object)
    finished = QtCore.Signal()

    def __init__(self, generation, requests, project_content_dir):
        super(AssetStateWorker, self).__init__()
        self._generation = int(generation)
        self._requests = list(requests or [])
        self._project_content_dir = project_content_dir
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @QtCore.Slot()
    def run(self):
        try:
            for key, asset_root in self._requests:
                if self._cancelled:
                    break
                try:
                    plan = build_import_plan(asset_root, self._project_content_dir)
                except Exception as exc:
                    plan = {
                        "asset_root": _forward(asset_root),
                        "state": "error",
                        "message": str(exc),
                        "main_object_path": "",
                    }
                self.itemScanned.emit(self._generation, str(key), plan)
        finally:
            self.finished.emit()


class AssetCopyWorker(QtCore.QObject):
    progress = QtCore.Signal(int, str)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, plan):
        super(AssetCopyWorker, self).__init__()
        self._plan = dict(plan or {})
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _is_cancelled(self):
        return self._cancelled

    @QtCore.Slot()
    def run(self):
        created_files = []
        temp_files = []
        staged_files = []
        try:
            files = self._plan.get("files") or []
            if not files:
                raise RuntimeError(u"没有可加载的 UE 发布文件")

            conflicts = []
            for entry in files:
                if self._cancelled:
                    raise RuntimeError(u"操作已取消")
                target = entry["target"]
                if not os.path.isfile(target):
                    continue
                if os.path.getsize(target) != entry["size"]:
                    conflicts.append(entry["relative"])
                    continue
                if _sha1(entry["source"], self._is_cancelled) != _sha1(target, self._is_cancelled):
                    conflicts.append(entry["relative"])
            if conflicts:
                shown = u"、".join(conflicts[:5])
                suffix = u" 等" if len(conflicts) > 5 else ""
                raise AssetConflictError(u"检测到 {0} 个同名不同内容文件：{1}{2}。为保护工程，本次未覆盖。".format(
                    len(conflicts), shown, suffix))

            total_bytes = max(1, sum(max(0, int(entry.get("size", 0))) for entry in files))
            completed_bytes = 0
            for entry in files:
                if self._cancelled:
                    raise RuntimeError(u"操作已取消")
                source = entry["source"]
                target = entry["target"]
                size = max(0, int(entry.get("size", 0)))
                if os.path.isfile(target):
                    completed_bytes += size
                    self.progress.emit(int(completed_bytes * 100.0 / total_bytes), entry["relative"])
                    continue

                parent = os.path.dirname(target)
                os.makedirs(parent, exist_ok=True)
                temp_path = target + ".cgtools_tmp_" + uuid.uuid4().hex
                temp_files.append(temp_path)
                with open(source, "rb") as src, open(temp_path, "xb") as dst:
                    while True:
                        if self._cancelled:
                            raise RuntimeError(u"操作已取消")
                        chunk = src.read(COPY_CHUNK_SIZE)
                        if not chunk:
                            break
                        dst.write(chunk)
                        completed_bytes += len(chunk)
                        percent = min(99, int(completed_bytes * 100.0 / total_bytes))
                        self.progress.emit(percent, entry["relative"])
                shutil.copystat(source, temp_path)
                staged_files.append((temp_path, target, entry))

            # 两阶段提交：全部字节复制成功后才暴露给 UE；sidecar 在主包之前提交。
            staged_files.sort(key=lambda row: (
                row[2]["extension"] in PRIMARY_EXTENSIONS,
                row[2]["relative"].lower(),
            ))
            for temp_path, target, entry in staged_files:
                if self._cancelled:
                    raise RuntimeError(u"操作已取消")
                if os.path.exists(target):
                    raise AssetConflictError(u"复制过程中目标文件被其他进程创建：{0}".format(entry["relative"]))
                os.replace(temp_path, target)
                temp_files.remove(temp_path)
                created_files.append(target)

            self._plan["created_files"] = [_forward(path) for path in created_files]
            self._plan = query_filesystem_state(self._plan)
            self.progress.emit(100, u"正在让 UE 注册新资产…")
            self.finished.emit(self._plan)
        except Exception as exc:
            for path in temp_files:
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                except OSError:
                    pass
            for path in reversed(created_files):
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                except OSError:
                    pass
            self.failed.emit(str(exc))


class FolderBackupWorker(QtCore.QObject):
    """在删除已有 UE 分类前，把整个物理目录复制到工程 Saved 备份区。"""

    progress = QtCore.Signal(int, str)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, source_folder, backup_folder):
        super(FolderBackupWorker, self).__init__()
        self._source_folder = os.path.abspath(os.path.normpath(str(source_folder)))
        self._backup_folder = os.path.abspath(os.path.normpath(str(backup_folder)))
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @QtCore.Slot()
    def run(self):
        try:
            if not os.path.isdir(self._source_folder):
                raise RuntimeError(u"工程蓝图目录不存在，无法创建替换前备份")
            if os.path.exists(self._backup_folder):
                raise RuntimeError(u"备份目录已存在，为防止覆盖已停止：{0}".format(
                    self._backup_folder))

            entries = []
            total_bytes = 0
            for root, dirs, names in os.walk(self._source_folder):
                if self._cancelled:
                    raise RuntimeError(u"操作已取消")
                dirs.sort(key=str.lower)
                for name in sorted(names, key=str.lower):
                    source = os.path.abspath(os.path.join(root, name))
                    relative = os.path.relpath(source, self._source_folder)
                    try:
                        size = max(0, int(os.path.getsize(source)))
                    except OSError:
                        size = 0
                    entries.append((source, relative, size))
                    total_bytes += size

            if not entries:
                raise RuntimeError(u"工程蓝图目录为空，无法创建替换前备份")

            os.makedirs(self._backup_folder)
            completed_bytes = 0
            for source, relative, size in entries:
                if self._cancelled:
                    raise RuntimeError(u"操作已取消")
                destination = os.path.abspath(os.path.join(self._backup_folder, relative))
                try:
                    inside_backup = (
                        os.path.commonpath((self._backup_folder, destination))
                        == self._backup_folder)
                except ValueError:
                    inside_backup = False
                if not inside_backup:
                    raise RuntimeError(u"备份文件目标超出备份目录：{0}".format(relative))

                os.makedirs(os.path.dirname(destination), exist_ok=True)
                with open(source, "rb") as src, open(destination, "xb") as dst:
                    while True:
                        if self._cancelled:
                            raise RuntimeError(u"操作已取消")
                        chunk = src.read(COPY_CHUNK_SIZE)
                        if not chunk:
                            break
                        dst.write(chunk)
                        completed_bytes += len(chunk)
                        percent = min(99, int(completed_bytes * 100.0 /
                                              max(1, total_bytes)))
                        self.progress.emit(percent, _forward(relative))
                shutil.copystat(source, destination)
                if size == 0:
                    self.progress.emit(
                        min(99, int(completed_bytes * 100.0 / max(1, total_bytes))),
                        _forward(relative))

            self.progress.emit(100, u"备份完成")
            self.finished.emit({
                "source_folder": _forward(self._source_folder),
                "backup_folder": _forward(self._backup_folder),
                "file_count": len(entries),
                "total_bytes": total_bytes,
            })
        except Exception as exc:
            # 失败时不自动删除已复制的数据，避免把可能有用的恢复文件再次破坏。
            self.failed.emit(str(exc))
