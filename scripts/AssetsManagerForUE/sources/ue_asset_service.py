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
import stat
import time
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
    """检查固定发布路径；源资产不可访问时抛错，不能误判为没有发布包。"""
    asset_root = os.path.normpath(str(asset_root or ""))
    if not stat.S_ISDIR(os.stat(asset_root).st_mode):
        raise NotADirectoryError(asset_root)
    ue_root = os.path.join(asset_root, "UE")
    try:
        ue_is_dir = stat.S_ISDIR(os.stat(ue_root).st_mode)
    except FileNotFoundError:
        # NAS 在两次检查之间断开时，也不能显示“没有 UE”。
        os.stat(asset_root)
        return ""
    if not ue_is_dir:
        return ""
    content_root = os.path.join(ue_root, "Content")
    try:
        content_is_dir = stat.S_ISDIR(os.stat(content_root).st_mode)
    except FileNotFoundError:
        content_is_dir = False
    if content_is_dir:
        return os.path.normpath(content_root)
    # 兼容旧发布格式，交给建计划时统一扫描，避免递归遍历两次。
    return os.path.normpath(ue_root)


def _raise_walk_error(error):
    raise error


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
        "source_available": False,
        "ue_directory_exists": bool(source_root),
        "source_message": u"服务器没有 UE 发布目录，无法加载资产",
    }
    if not source_root:
        return plan

    manifest = _read_manifest(asset_root, source_root)
    plan["manifest"] = manifest
    for root, dirs, names in os.walk(source_root, onerror=_raise_walk_error):
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
            size = os.path.getsize(source)
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
    plan["source_available"] = bool(plan["package_object_paths"])
    plan["source_message"] = (
        u"服务器有 UE 发布主包，可加载资产" if plan["source_available"]
        else u"UE 发布目录中没有 .uasset 或 .umap 主包，无法加载资产")
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


def _build_package_file_import_plan(package_files, source_content_root,
                                    selected_source_file,
                                    project_content_dir=None,
                                    missing_dependencies=None,
                                    dependency_resolved=False):
    """把一组主包及 sidecar 转成保持 Content 相对路径不变的复制计划。"""
    source_content_root = os.path.abspath(
        os.path.normpath(str(source_content_root or "")))
    selected_source_file = os.path.abspath(
        os.path.normpath(str(selected_source_file or "")))
    target_root = _project_content_dir(project_content_dir)
    plan = {
        "asset_root": _forward(os.path.dirname(selected_source_file)),
        "source_root": _forward(source_content_root),
        "source_content_root": _forward(source_content_root),
        "target_root": _forward(target_root),
        "files": [],
        "package_object_paths": [],
        "main_object_path": object_path_for_source_file(
            selected_source_file, source_content_root),
        "manifest": {},
        "missing_dependencies": list(missing_dependencies or []),
        "dependency_resolved": bool(dependency_resolved),
        "state": "missing",
        "message": u"没有找到可迁移的特效包",
    }
    if not os.path.isdir(source_content_root):
        plan["state"] = "error"
        plan["message"] = u"特效库 Content 目录不可访问"
        return plan

    seen_files = set()
    seen_objects = set()
    for package_file in package_files or []:
        package_file = os.path.abspath(os.path.normpath(str(package_file or "")))
        extension = os.path.splitext(package_file)[1].lower()
        if extension not in PRIMARY_EXTENSIONS or not os.path.isfile(package_file):
            continue
        try:
            inside_source = (
                os.path.commonpath((source_content_root, package_file))
                == source_content_root)
        except ValueError:
            inside_source = False
        if not inside_source:
            continue

        object_path = object_path_for_source_file(package_file, source_content_root)
        object_key = object_path.lower()
        if object_path and object_key not in seen_objects:
            seen_objects.add(object_key)
            plan["package_object_paths"].append(object_path)

        package_stem = os.path.splitext(package_file)[0]
        family = [package_file]
        for sidecar_extension in sorted(PACKAGE_EXTENSIONS - PRIMARY_EXTENSIONS):
            sidecar = package_stem + sidecar_extension
            if os.path.isfile(sidecar):
                family.append(sidecar)
        for source in family:
            source = os.path.abspath(os.path.normpath(source))
            source_key = os.path.normcase(source)
            if source_key in seen_files:
                continue
            seen_files.add(source_key)
            relative = os.path.relpath(source, source_content_root)
            target = os.path.abspath(os.path.join(target_root, relative))
            try:
                inside_target = os.path.commonpath((target_root, target)) == target_root
            except ValueError:
                inside_target = False
            if not inside_target:
                continue
            file_extension = os.path.splitext(source)[1].lower()
            try:
                size = os.path.getsize(source)
            except OSError:
                size = 0
            plan["files"].append({
                "source": _forward(source),
                "target": _forward(target),
                "relative": _forward(relative),
                "size": int(size),
                "extension": file_extension,
            })

    plan["files"].sort(key=lambda entry: (
        entry["extension"] in PRIMARY_EXTENSIONS,
        entry["relative"].lower(),
    ))
    plan["package_object_paths"].sort(key=str.lower)
    plan = query_filesystem_state(plan)
    if plan["missing_dependencies"]:
        plan["state"] = "error"
        plan["message"] = u"特效有 {0} 个依赖既不在服务器 Content 中，也不在当前工程/插件中".format(
            len(plan["missing_dependencies"]))
    elif dependency_resolved:
        if plan.get("state") == "ready":
            plan["message"] = u"特效及其 {0} 个依赖包已在当前工程中".format(
                max(0, len(plan["package_object_paths"]) - 1))
        elif plan.get("state") == "missing":
            plan["message"] = u"已解析 {0} 个特效及依赖包，等待迁移".format(
                len(plan["package_object_paths"]))
    return plan


def build_single_package_import_plan(source_file, source_content_root,
                                     project_content_dir=None):
    """后台扫描卡片时使用的轻量状态计划；不调用 UE，也不展开依赖。"""
    return _build_package_file_import_plan(
        [source_file], source_content_root, source_file,
        project_content_dir=project_content_dir,
        dependency_resolved=False)


def get_external_asset_class_names(asset_file_paths, source_content_root):
    """批量读取工程外 uasset 的 UE 类型，返回（与输入对齐的类型列表, 错误）。"""
    paths = [str(value) for value in (asset_file_paths or [])]
    if not paths:
        return [], ""
    if unreal is None:
        return [], u"当前不在 Unreal Editor 中"
    bridge = getattr(unreal, "CGToolsAssetBridgeLibrary", None)
    if bridge is None:
        return [], u"未启用 CGToolsAssetBridge 插件"
    query_method = getattr(bridge, "get_external_asset_class_names", None)
    if query_method is None:
        return [], u"CGToolsAssetBridge 版本低于 1.3.2，不支持按特效类型过滤"
    try:
        try:
            result = query_method(paths, str(source_content_root))
        except TypeError:
            result = query_method(paths, str(source_content_root), [], "")
    except Exception as exc:
        return [], u"读取外部特效类型失败：{0}".format(exc)

    if not isinstance(result, (tuple, list)):
        return [], u"CGToolsAssetBridge 返回了无法识别的类型结果：{0}".format(result)
    values = list(result)
    if len(values) >= 3 and isinstance(values[0], bool):
        success = bool(values[0])
        classes_value, error_value = values[1:3]
    elif len(values) >= 2:
        classes_value, error_value = values[:2]
        success = not bool(error_value)
    else:
        return [], u"CGToolsAssetBridge 返回了无法识别的类型结果：{0}".format(result)

    try:
        class_names = [str(value) for value in (
            classes_value if classes_value is not None else [])]
    except TypeError:
        class_names = []
    error = str(error_value or "")
    if not success:
        return [], error or u"原生桥无法读取外部特效类型"
    if len(class_names) != len(paths):
        return [], u"原生桥返回的特效类型数量不匹配：{0}/{1}".format(
            len(class_names), len(paths))
    return class_names, error


def resolve_external_asset_dependencies(asset_file_path, source_content_root):
    """在 UE 主线程调用原生桥，返回（包文件列表、缺失包列表、错误文本）。"""
    if unreal is None:
        return [], [], u"当前不在 Unreal Editor 中"
    bridge = getattr(unreal, "CGToolsAssetBridgeLibrary", None)
    if bridge is None:
        return [], [], u"未启用 CGToolsAssetBridge 插件"
    resolve_method = getattr(bridge, "resolve_external_asset_dependencies", None)
    if resolve_method is None:
        return [], [], u"CGToolsAssetBridge 版本低于 1.3.0，不支持特效依赖迁移"
    try:
        try:
            result = resolve_method(str(asset_file_path), str(source_content_root))
        except TypeError:
            result = resolve_method(
                str(asset_file_path), str(source_content_root), [], [], "")
    except Exception as exc:
        return [], [], u"解析特效依赖失败：{0}".format(exc)

    if not isinstance(result, (tuple, list)):
        return [], [], u"CGToolsAssetBridge 返回了无法识别的依赖结果：{0}".format(result)

    # UE Python 对“C++ 返回值 + 多个输出引用”的包装在不同引擎版本中不同：
    # - 某些版本返回 (bool, OutPackageFiles, OutMissingPackages, OutError)；
    # - UE 5.7 实测会省略 bool，返回 (OutPackageFiles, OutMissingPackages, OutError)。
    # unreal.Array 不是 Python list，但可迭代，因此在这里统一转成普通字符串列表。
    values = list(result)
    if len(values) >= 4 and isinstance(values[0], bool):
        success = bool(values[0])
        package_value, missing_value, error_value = values[1:4]
    elif len(values) >= 3:
        package_value, missing_value, error_value = values[:3]
        try:
            success = bool(len(package_value))
        except (TypeError, AttributeError):
            success = bool(package_value)
    else:
        return [], [], u"CGToolsAssetBridge 返回了无法识别的依赖结果：{0}".format(result)

    try:
        package_files = [str(value) for value in (package_value or [])]
    except TypeError:
        package_files = []
    try:
        missing_packages = [str(value) for value in (missing_value or [])]
    except TypeError:
        missing_packages = []
    error = str(error_value or "")
    if not success:
        return [], missing_packages, error or u"原生桥无法解析该特效的依赖"
    return package_files, missing_packages, error


def build_external_dependency_import_plan(source_file, source_content_root,
                                          project_content_dir=None):
    """为选中特效建立递归依赖闭包迁移计划；必须从 UE 主线程调用。"""
    package_files, missing_packages, error = resolve_external_asset_dependencies(
        source_file, source_content_root)
    if error and not package_files:
        plan = _build_package_file_import_plan(
            [source_file], source_content_root, source_file,
            project_content_dir=project_content_dir,
            dependency_resolved=False)
        plan["state"] = "error"
        plan["message"] = error
        return plan
    return _build_package_file_import_plan(
        package_files, source_content_root, source_file,
        project_content_dir=project_content_dir,
        missing_dependencies=missing_packages,
        dependency_resolved=True)


def query_filesystem_state(plan, verify_content=False):
    """Update red/orange/green state without loading UE packages.

    Background card scans keep the inexpensive size check.  A user-initiated
    load passes ``verify_content=True`` so equal-size but different packages
    are included in the conflict choices before the copy worker starts.
    """
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
        content_differs = target_size != entry["size"]
        if not content_differs and verify_content:
            try:
                content_differs = (
                    _sha1(entry["source"]) != _sha1(target))
            except OSError:
                # A source or target that cannot be read safely must not be
                # treated as identical merely because its byte size matches.
                content_differs = True
        if content_differs:
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


WINDOWS_FILE_LOCK_ERRORS = frozenset((32, 33))
FILE_OPERATION_RETRY_ATTEMPTS = 21
FILE_OPERATION_RETRY_DELAY_SECONDS = 0.2


def _is_windows_file_lock_error(exc):
    return getattr(exc, "winerror", None) in WINDOWS_FILE_LOCK_ERRORS


def _raise_file_in_use_error(path, attempts, delay_seconds):
    waited_seconds = max(0.0, (attempts - 1) * delay_seconds)
    raise RuntimeError(
        u"文件在等待 {0:.1f} 秒后仍被 UE 或其他程序占用，无法覆盖：\n{1}\n\n"
        u"请关闭正在编辑该资产的材质、网格体、蓝图等编辑器窗口后重试。".format(
            waited_seconds, _forward(path)))


def _replace_with_retry(source, target, cancelled=None,
                        attempts=FILE_OPERATION_RETRY_ATTEMPTS,
                        delay_seconds=FILE_OPERATION_RETRY_DELAY_SECONDS):
    """Replace a file while tolerating short-lived UE/Windows file locks."""
    attempts = max(1, int(attempts))
    for attempt in range(attempts):
        if cancelled and cancelled():
            raise RuntimeError(u"操作已取消")
        try:
            os.replace(source, target)
            return
        except OSError as exc:
            if not _is_windows_file_lock_error(exc):
                raise
            if attempt + 1 >= attempts:
                busy_path = source if os.path.exists(source) else target
                _raise_file_in_use_error(
                    busy_path, attempts, delay_seconds)
            time.sleep(delay_seconds)


def _remove_with_retry(path, cancelled=None,
                       attempts=FILE_OPERATION_RETRY_ATTEMPTS,
                       delay_seconds=FILE_OPERATION_RETRY_DELAY_SECONDS):
    """Remove a file while tolerating short-lived Asset Registry handles."""
    attempts = max(1, int(attempts))
    for attempt in range(attempts):
        if cancelled and cancelled():
            raise RuntimeError(u"操作已取消")
        try:
            os.remove(path)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            if not _is_windows_file_lock_error(exc):
                raise
            if attempt + 1 >= attempts:
                _raise_file_in_use_error(path, attempts, delay_seconds)
            time.sleep(delay_seconds)


def prepare_plan_overwrites(plan):
    """Fully load selected existing assets before the copy thread replaces them.

    UE may keep lazily loaded package files open without delete sharing.  On
    Windows that prevents the transaction from renaming the original file to
    its recovery backup.  ``fully_load_assets`` is the UE-provided operation
    whose documented purpose is to release those on-disk write locks.

    This function calls Unreal APIs and therefore must run on the UI thread.
    It returns warning strings instead of aborting the transaction; the copy
    worker still performs bounded retries and keeps its normal rollback path.
    """
    if unreal is None:
        return []

    overwrite_files = {
        _forward(value).lower()
        for value in ((plan or {}).get("overwrite_files") or [])
    }
    if not overwrite_files:
        return []

    assets = []
    object_paths = []
    warnings = []
    for entry in (plan or {}).get("files") or []:
        relative = _forward(entry.get("relative"))
        if relative.lower() not in overwrite_files:
            continue
        if str(entry.get("extension") or "").lower() != ".uasset":
            continue
        if not os.path.isfile(entry.get("target") or ""):
            continue
        object_path = _object_path_from_relative(relative)
        if not object_path:
            continue
        try:
            if not unreal.EditorAssetLibrary.does_asset_exist(object_path):
                continue
            asset = unreal.EditorAssetLibrary.load_asset(object_path)
            if asset:
                assets.append(asset)
                object_paths.append(object_path)
        except Exception as exc:
            warnings.append(u"无法准备覆盖 {0}：{1}".format(
                object_path, exc))

    if not assets:
        return warnings

    try:
        unreal.EditorLoadingAndSavingUtils.fully_load_assets(assets)
        plan["prepared_overwrite_object_paths"] = object_paths
    except Exception as exc:
        warnings.append(u"UE 无法释放待覆盖资产的磁盘句柄：{0}".format(exc))
    return warnings


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


def project_asset_class_name(relative_path):
    """Return the class name of the matching asset in the current project."""
    if unreal is None:
        return ""
    object_path = _object_path_from_relative(relative_path)
    if not object_path:
        return ""
    return _asset_class_name(object_path)


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
    overwritten_count = len(plan.get("overwritten_files") or [])
    kept_count = len(plan.get("kept_existing_files") or [])
    policy_suffix = ""
    if overwritten_count or kept_count:
        policy_suffix = u"（覆盖 {0} 个冲突文件，保留工程版本 {1} 个）".format(
            overwritten_count, kept_count)
    if not require_placeable:
        plan["state"] = "ready"
        plan["message"] = u"分类蓝图已完整加载{0}".format(policy_suffix)
    elif plan["main_object_path"]:
        plan["state"] = "ready"
        plan["message"] = u"加载完成，可拖入关卡{0}".format(policy_suffix)
    else:
        plan["state"] = "partial"
        plan["message"] = (
            u"加载完成；包中没有可直接放置的 Actor 蓝图或网格体{0}".format(
                policy_suffix))
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
    """Focus the asset's folder, then select the asset in Content Browser."""
    object_path = _normalize_object_path(object_path)
    if unreal is None or not object_path:
        return False
    try:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        # SyncBrowserToObjects silently returns while the registry is loading.
        # Let the UI retry after the next Slate tick instead of reporting success.
        if registry.is_loading_assets():
            return False
        asset = unreal.EditorAssetLibrary.load_asset(object_path)
        if asset is None:
            return False
        utility = getattr(unreal, "EditorUtilityLibrary", None)
        sync_folders = getattr(utility, "sync_browser_to_folders", None)
        if callable(sync_folders):
            sync_folders([object_path.rsplit("/", 1)[0]])
        unreal.EditorAssetLibrary.sync_browser_to_objects([object_path])
        return True
    except Exception:
        return False


def open_asset_editor(object_path):
    """Open/focus the UE asset editor using the Python-exposed subsystem API."""
    object_path = _normalize_object_path(object_path)
    if unreal is None or not object_path:
        return False, u"没有可打开的 UE 资源"
    try:
        asset = unreal.EditorAssetLibrary.load_asset(object_path)
        if asset is None:
            return False, u"UE 无法加载 {0}".format(object_path)
        subsystem = unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)
        # The singular OpenEditorForAsset is C++ only in UE 5.7.
        if not subsystem.open_editor_for_assets([asset]):
            return False, u"UE 未能打开资源编辑器：{0}".format(object_path)
        return True, ""
    except Exception as exc:
        return False, u"打开资源编辑器失败：{0}".format(exc)


def sync_plan_to_content_browser(plan):
    """Locate the best imported object from a plan in Content Browser.

    A placeable mesh/Actor Blueprint remains the first choice.  Packages that
    contain no placeable object still locate their first existing UE asset so
    a successful load never leaves the user searching for the copied files.
    Returns ``(success, object_path)``.
    """
    if unreal is None:
        return False, ""

    candidates = []
    seen_candidates = set()
    for value in [plan.get("main_object_path")] + list(
            plan.get("package_object_paths") or []):
        object_path = _normalize_object_path(value)
        object_key = object_path.lower()
        if object_path and object_key not in seen_candidates:
            seen_candidates.add(object_key)
            candidates.append(object_path)

    for object_path in candidates:
        try:
            if (unreal.EditorAssetLibrary.does_asset_exist(object_path)
                    and sync_to_content_browser(object_path)):
                return True, object_path
        except Exception:
            continue
    return False, ""


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
                        "source_available": None,
                        "ue_directory_exists": None,
                        "source_message": u"无法确认服务器 UE 发布文件：{0}".format(exc),
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
        replaced_files = []
        temp_files = []
        staged_files = []
        try:
            files = self._plan.get("files") or []
            if not files:
                raise RuntimeError(u"没有可加载的 UE 发布文件")

            overwrite_files = {
                _forward(value).lower()
                for value in (self._plan.get("overwrite_files") or [])
            }
            keep_existing_files = {
                _forward(value).lower()
                for value in (self._plan.get("keep_existing_files") or [])
            }

            conflicts = []
            for entry in files:
                if self._cancelled:
                    raise RuntimeError(u"操作已取消")
                target = entry["target"]
                if not os.path.isfile(target):
                    continue
                relative_key = _forward(entry["relative"]).lower()
                content_differs = os.path.getsize(target) != entry["size"]
                if not content_differs:
                    content_differs = (
                        _sha1(entry["source"], self._is_cancelled)
                        != _sha1(target, self._is_cancelled))
                if (content_differs
                        and relative_key not in overwrite_files
                        and relative_key not in keep_existing_files):
                    conflicts.append(entry["relative"])
            if conflicts:
                shown = u"、".join(conflicts[:5])
                suffix = u" 等" if len(conflicts) > 5 else ""
                raise AssetConflictError(
                    u"检测到 {0} 个尚未选择处理方式的冲突文件：{1}{2}。"
                    u"请重新加载并选择覆盖或保留。".format(
                        len(conflicts), shown, suffix))

            total_bytes = max(1, sum(max(0, int(entry.get("size", 0))) for entry in files))
            completed_bytes = 0
            for entry in files:
                if self._cancelled:
                    raise RuntimeError(u"操作已取消")
                source = entry["source"]
                target = entry["target"]
                size = max(0, int(entry.get("size", 0)))
                relative_key = _forward(entry["relative"]).lower()
                should_overwrite = relative_key in overwrite_files
                if os.path.isfile(target) and not should_overwrite:
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
                relative_key = _forward(entry["relative"]).lower()
                should_overwrite = relative_key in overwrite_files
                target_existed = os.path.exists(target)
                if target_existed and not should_overwrite:
                    raise AssetConflictError(u"复制过程中目标文件被其他进程创建：{0}".format(entry["relative"]))
                if target_existed:
                    backup_path = target + ".cgtools_backup_" + uuid.uuid4().hex
                    _replace_with_retry(
                        target, backup_path, self._is_cancelled)
                    replaced_files.append((target, backup_path, entry["relative"]))
                _replace_with_retry(
                    temp_path, target, self._is_cancelled)
                temp_files.remove(temp_path)
                if not target_existed:
                    created_files.append(target)

            self._plan["created_files"] = [_forward(path) for path in created_files]
            self._plan["overwritten_files"] = sorted(
                (_forward(relative) for _target, _backup, relative in replaced_files),
                key=str.lower)
            self._plan["kept_existing_files"] = sorted(
                (_forward(entry["relative"]) for entry in files
                 if _forward(entry["relative"]).lower() in keep_existing_files),
                key=str.lower)
            self._plan = query_filesystem_state(self._plan)

            # 计划和磁盘状态都更新成功后再清掉原文件备份；此前任一步失败，
            # except 分支仍能利用这些备份把所有已覆盖文件恢复原状。
            recovery_backups = []
            for _target, backup_path, _relative in replaced_files:
                try:
                    if os.path.isfile(backup_path):
                        _remove_with_retry(
                            backup_path, self._is_cancelled)
                except (OSError, RuntimeError):
                    recovery_backups.append(_forward(backup_path))
            if recovery_backups:
                self._plan["recovery_backup_files"] = recovery_backups
            self.progress.emit(100, u"正在让 UE 注册新资产…")
            self.finished.emit(self._plan)
        except Exception as exc:
            rollback_errors = []
            for path in temp_files:
                try:
                    if os.path.isfile(path):
                        _remove_with_retry(path)
                except (OSError, RuntimeError) as rollback_error:
                    rollback_errors.append(str(rollback_error))
            for path in reversed(created_files):
                try:
                    if os.path.isfile(path):
                        _remove_with_retry(path)
                except (OSError, RuntimeError) as rollback_error:
                    rollback_errors.append(str(rollback_error))
            for target, backup_path, _relative in reversed(replaced_files):
                try:
                    if os.path.isfile(target):
                        _remove_with_retry(target)
                    if os.path.isfile(backup_path):
                        _replace_with_retry(backup_path, target)
                except (OSError, RuntimeError) as rollback_error:
                    rollback_errors.append(str(rollback_error))
            message = str(exc)
            if rollback_errors:
                message += u"\n回滚时有文件未能自动恢复：{0}".format(
                    u"；".join(rollback_errors[:3]))
            self.failed.emit(message)


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
