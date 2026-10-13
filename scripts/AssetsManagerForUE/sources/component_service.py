#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""服务器 C++ 组件扫描、复制和 Unreal Editor 安全重启服务。"""

from __future__ import absolute_import

import base64
import hashlib
import os
import shutil
import subprocess
import time
import uuid

try:
    import unreal
except ImportError:
    unreal = None

from PySide6 import QtCore


COMPONENT_ROOT_CANDIDATES = (
    r"Y:\MCCTools\src\UE574\CppComponent",
    r"\\fznas.diandian.info\AC\MCCTools\src\UE574\CppComponent",
)
COPY_CHUNK_SIZE = 4 * 1024 * 1024
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
COMPONENT_EXCLUDED_DIRECTORIES = frozenset((
    "intermediate",
    "saved",
    "deriveddatacache",
    ".vs",
    "__pycache__",
    ".git",
    ".svn",
))
COMPONENT_EXCLUDED_FILE_EXTENSIONS = frozenset((
    ".rsp",
    ".obj",
    ".pch",
    ".tlog",
    ".idb",
    ".ipdb",
    ".iobj",
    ".tmp",
))


def _forward(path):
    return str(path or "").replace("\\", "/")


def _normal(path):
    return os.path.abspath(os.path.normpath(str(path or "")))


def _inside(parent, child, allow_equal=False):
    parent = _normal(parent)
    child = _normal(child)
    try:
        common = os.path.commonpath((parent, child))
    except ValueError:
        return False
    return common == parent and (allow_equal or child != parent)


def _is_excluded_component_directory(name):
    """过滤 Unreal/IDE 生成的缓存目录，不影响 Binaries 等正式插件内容。"""
    return str(name or "").strip().lower() in COMPONENT_EXCLUDED_DIRECTORIES


def _is_excluded_component_file(filename):
    """兜底过滤散落在缓存目录之外的编译中间文件。"""
    extension = os.path.splitext(str(filename or ""))[1].lower()
    return extension in COMPONENT_EXCLUDED_FILE_EXTENSIONS


def _remove_empty_directory(path):
    """仅删除空目录；存在其他待重启组件时保持 staging 根目录不变。"""
    if not path:
        return
    try:
        os.rmdir(path)
    except OSError:
        pass


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


def _same_file(source, target, cancelled=None):
    """复制后的文件通常保留 mtime；mtime 不同时再计算哈希，兼顾速度和准确性。"""
    try:
        source_stat = os.stat(source)
        target_stat = os.stat(target)
    except OSError:
        return False
    if source_stat.st_size != target_stat.st_size:
        return False
    source_time = getattr(source_stat, "st_mtime_ns", int(source_stat.st_mtime * 1e9))
    target_time = getattr(target_stat, "st_mtime_ns", int(target_stat.st_mtime * 1e9))
    if source_time == target_time:
        return True
    return _sha1(source, cancelled) == _sha1(target, cancelled)


def project_directory():
    if unreal is None:
        raise RuntimeError(u"当前不在 Unreal Editor 中，无法确定工程目录")
    value = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
    value = _normal(value)
    if not os.path.isdir(value):
        raise RuntimeError(u"当前 UE 工程目录不存在：{0}".format(value))
    return value


def project_plugins_directory():
    return os.path.join(project_directory(), "Plugins")


def _component_icon(component_folder, component_name):
    expected = os.path.join(component_folder, component_name + ".png")
    if os.path.isfile(expected):
        return expected
    expected_lower = (component_name + ".png").lower()
    try:
        names = os.listdir(component_folder)
    except OSError:
        return ""
    for filename in names:
        stem, extension = os.path.splitext(filename)
        if (filename.lower() == expected_lower
                or (stem.lower() == component_name.lower()
                    and extension.lower() in IMAGE_EXTENSIONS)):
            path = os.path.join(component_folder, filename)
            if os.path.isfile(path):
                return path
    return ""


def _descriptor(component_folder, component_name):
    descriptors = []
    for filename in os.listdir(component_folder):
        path = os.path.join(component_folder, filename)
        if os.path.isfile(path) and filename.lower().endswith(".uplugin"):
            descriptors.append(path)
    exact = [path for path in descriptors
             if os.path.splitext(os.path.basename(path))[0].lower()
             == component_name.lower()]
    if exact:
        return sorted(exact, key=str.lower)[0], ""
    if len(descriptors) == 1:
        return descriptors[0], ""
    if not descriptors:
        return "", u"组件目录中没有找到 .uplugin 描述文件"
    return "", u"组件目录中存在多个 .uplugin，无法确定要安装哪一个"


def build_component_plan(category_name, component_folder, plugins_dir,
                         cancelled=None):
    component_folder = _normal(component_folder)
    plugins_dir = _normal(plugins_dir)
    component_name = os.path.basename(component_folder)
    target_folder = os.path.join(plugins_dir, component_name)
    plan = {
        "name": component_name,
        "category": str(category_name),
        "source_folder": component_folder,
        "plugins_dir": plugins_dir,
        "target_folder": target_folder,
        "icon": _component_icon(component_folder, component_name),
        "descriptor": "",
        "files": [],
        "directories": [],
        "state": "missing",
        "message": u"等待检查组件",
    }
    try:
        descriptor, descriptor_error = _descriptor(component_folder, component_name)
    except OSError as exc:
        plan["state"] = "error"
        plan["message"] = u"无法读取组件目录：{0}".format(exc)
        return plan
    if descriptor_error:
        plan["state"] = "error"
        plan["message"] = descriptor_error
        return plan
    plan["descriptor"] = descriptor

    for root, dirnames, filenames in os.walk(component_folder):
        if cancelled and cancelled():
            raise RuntimeError(u"操作已取消")
        # 必须原地修改 dirnames，阻止 os.walk 继续进入开发机构建缓存。
        dirnames[:] = [
            name for name in dirnames
            if not _is_excluded_component_directory(name)
        ]
        dirnames.sort(key=str.lower)
        filenames = [
            name for name in filenames
            if not _is_excluded_component_file(name)
        ]
        filenames.sort(key=str.lower)
        relative_root = os.path.relpath(root, component_folder)
        if relative_root not in ("", "."):
            plan["directories"].append(_forward(relative_root))
        for filename in filenames:
            source = os.path.join(root, filename)
            relative = os.path.relpath(source, component_folder)
            try:
                size = os.path.getsize(source)
            except OSError as exc:
                plan["state"] = "error"
                plan["message"] = u"无法读取组件文件：{0}（{1}）".format(
                    _forward(relative), exc)
                return plan
            plan["files"].append({
                "source": source,
                "target": os.path.join(target_folder, relative),
                "relative": _forward(relative),
                "size": int(size),
            })
    plan["files"].sort(key=lambda value: value["relative"].lower())
    if not plan["files"]:
        plan["state"] = "error"
        plan["message"] = u"组件目录为空"
        return plan
    return query_component_state(plan, cancelled=cancelled)


def query_component_state(plan, cancelled=None):
    """比较服务器组件与工程 Plugins 中的同名组件。"""
    files = plan.get("files") or []
    if not plan.get("descriptor") or not files:
        plan["state"] = "error"
        plan["message"] = plan.get("message") or u"组件发布内容无效"
        return plan

    missing = []
    different = []
    existing = []
    for entry in files:
        if cancelled and cancelled():
            raise RuntimeError(u"操作已取消")
        target = entry["target"]
        if not os.path.isfile(target):
            missing.append(entry["relative"])
        elif _same_file(entry["source"], target, cancelled):
            existing.append(entry["relative"])
        else:
            different.append(entry["relative"])

    plan["missing_files"] = missing
    plan["different_files"] = different
    plan["existing_files"] = existing
    if different:
        plan["state"] = "conflict"
        plan["message"] = u"工程中已有不同版本（{0} 个文件不同）".format(
            len(different))
    elif not missing:
        plan["state"] = "ready"
        plan["message"] = u"组件已在当前工程 Plugins 中"
    elif existing:
        plan["state"] = "partial"
        plan["message"] = u"工程组件不完整，已有 {0}/{1} 个文件".format(
            len(existing), len(files))
    else:
        plan["state"] = "missing"
        plan["message"] = u"发现 {0} 个组件文件，等待加载".format(len(files))
    return plan


def scan_component_library(candidates, plugins_dir, cancelled=None):
    """递归扫描分类文件夹；直接含 .uplugin 的目录是组件，分类在该层停止。"""
    root_path = ""
    errors = []
    for candidate in candidates:
        if cancelled and cancelled():
            raise RuntimeError(u"操作已取消")
        try:
            if os.path.isdir(candidate):
                root_path = _normal(candidate)
                break
        except OSError as exc:
            errors.append(str(exc))
    if not root_path:
        detail = u"（{0}）".format(errors[-1]) if errors else ""
        raise RuntimeError(u"无法访问组件库：{0}{1}".format(candidates[0], detail))

    def scan_directory(folder, ancestors):
        if cancelled and cancelled():
            raise RuntimeError(u"操作已取消")
        relative_path = _forward(os.path.relpath(folder, root_path))
        try:
            modified = int(os.path.getmtime(folder))
        except OSError:
            modified = 0
        directory = {
            "name": os.path.basename(folder),
            "path": relative_path,
            "folder": folder,
            "modified": modified,
            "categories": [],
            "components": [],
        }
        with os.scandir(folder) as entries:
            entries = sorted(entries, key=lambda entry: entry.name.lower())
        # 只检查本层描述文件；父目录不会因后代含插件而被误判为组件。
        if relative_path != "." and any(
                entry.name.lower().endswith(".uplugin") and entry.is_file()
                for entry in entries):
            category_name = _forward(os.path.relpath(
                os.path.dirname(folder), root_path))
            plan = build_component_plan(
                category_name, folder, plugins_dir, cancelled=cancelled)
            directory.update({
                "category": category_name,
                "icon": plan.get("icon") or "",
                "plan": plan,
            })
            return directory

        ancestors = ancestors | {os.path.normcase(os.path.realpath(folder))}
        for entry in entries:
            if cancelled and cancelled():
                raise RuntimeError(u"操作已取消")
            if not entry.is_dir():
                continue
            if os.path.normcase(os.path.realpath(entry.path)) in ancestors:
                continue
            child = scan_directory(entry.path, ancestors)
            key = "components" if "plan" in child else "categories"
            directory[key].append(child)
        return directory

    library = scan_directory(root_path, set())
    return {
        "root": root_path,
        "plugins_dir": _normal(plugins_dir),
        "categories": library["categories"],
        "components": library["components"],
    }


class ComponentCopyWorker(QtCore.QObject):
    progress = QtCore.Signal(int, str)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, plan, stage_replacement=False):
        super(ComponentCopyWorker, self).__init__()
        self._plan = dict(plan or {})
        self._stage_replacement = bool(stage_replacement)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _is_cancelled(self):
        return self._cancelled

    def _copy_file(self, source, destination, relative, completed, total):
        with open(source, "rb") as src, open(destination, "xb") as dst:
            while True:
                if self._cancelled:
                    raise RuntimeError(u"操作已取消")
                chunk = src.read(COPY_CHUNK_SIZE)
                if not chunk:
                    break
                dst.write(chunk)
                completed += len(chunk)
                self.progress.emit(
                    min(99, int(completed * 100.0 / total)), relative)
        shutil.copystat(source, destination)
        return completed

    def _validate_plan(self):
        source_folder = _normal(self._plan.get("source_folder"))
        plugins_dir = _normal(self._plan.get("plugins_dir"))
        target_folder = _normal(self._plan.get("target_folder"))
        if not os.path.isdir(source_folder):
            raise RuntimeError(u"服务器组件目录已经不存在")
        if not plugins_dir or not _inside(plugins_dir, target_folder):
            raise RuntimeError(u"拒绝复制：目标组件不在当前工程 Plugins 内")
        return source_folder, plugins_dir, target_folder

    @QtCore.Slot()
    def run(self):
        temp_files = []
        created_files = []
        staging_root = ""
        staging_folder = ""
        try:
            source_folder, plugins_dir, target_folder = self._validate_plan()
            files = self._plan.get("files") or []
            if not files:
                raise RuntimeError(u"组件目录中没有可复制的文件")
            os.makedirs(plugins_dir, exist_ok=True)

            # 冲突版本不碰当前 UE 可能已经加载的 DLL；先完整复制到同卷暂存目录，
            # 确认重启后再由独立 helper 替换。
            if self._stage_replacement:
                staging_root = os.path.join(plugins_dir, ".AssetsManagerForUE_Staging")
                os.makedirs(staging_root, exist_ok=True)
                staging_folder = os.path.join(
                    staging_root, self._plan.get("name", "Component") + "_" + uuid.uuid4().hex)
                os.makedirs(staging_folder)
                total = max(1, sum(max(0, int(row.get("size", 0))) for row in files))
                completed = 0
                for relative_dir in self._plan.get("directories") or []:
                    os.makedirs(os.path.join(staging_folder, relative_dir), exist_ok=True)
                for entry in files:
                    if self._cancelled:
                        raise RuntimeError(u"操作已取消")
                    destination = os.path.join(staging_folder, entry["relative"])
                    os.makedirs(os.path.dirname(destination), exist_ok=True)
                    completed = self._copy_file(
                        entry["source"], destination, entry["relative"], completed, total)
                self._plan["staging_folder"] = staging_folder
                self._plan["install_mode"] = "replace_after_exit"
                self.progress.emit(100, u"新版本已复制到安全暂存目录")
                self.finished.emit(self._plan)
                return

            # 提交前做一次精确冲突检查，避免扫描后工程文件发生变化。
            conflicts = []
            for entry in files:
                target = entry["target"]
                if os.path.isfile(target) and not _same_file(
                        entry["source"], target, self._is_cancelled):
                    conflicts.append(entry["relative"])
            if conflicts:
                raise RuntimeError(
                    u"复制前检测到 {0} 个不同版本文件，请刷新后重新加载".format(
                        len(conflicts)))

            total = max(1, sum(max(0, int(row.get("size", 0))) for row in files))
            completed = 0
            if not os.path.exists(target_folder):
                staging_root = os.path.join(plugins_dir, ".AssetsManagerForUE_Staging")
                os.makedirs(staging_root, exist_ok=True)
                staging_folder = os.path.join(
                    staging_root, self._plan.get("name", "Component") + "_" + uuid.uuid4().hex)
                os.makedirs(staging_folder)
                for relative_dir in self._plan.get("directories") or []:
                    os.makedirs(os.path.join(staging_folder, relative_dir), exist_ok=True)
                for entry in files:
                    destination = os.path.join(staging_folder, entry["relative"])
                    os.makedirs(os.path.dirname(destination), exist_ok=True)
                    completed = self._copy_file(
                        entry["source"], destination, entry["relative"], completed, total)
                if os.path.exists(target_folder):
                    raise RuntimeError(u"复制过程中同名组件目录被其他进程创建")
                os.replace(staging_folder, target_folder)
                staging_folder = ""
                _remove_empty_directory(staging_root)
            else:
                # partial 只补齐缺失文件，不覆盖当前进程中可能被加载的文件。
                for entry in files:
                    if self._cancelled:
                        raise RuntimeError(u"操作已取消")
                    target = entry["target"]
                    size = max(0, int(entry.get("size", 0)))
                    if os.path.isfile(target):
                        completed += size
                        self.progress.emit(
                            min(99, int(completed * 100.0 / total)), entry["relative"])
                        continue
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    temp_path = target + ".cgtools_tmp_" + uuid.uuid4().hex
                    temp_files.append(temp_path)
                    completed = self._copy_file(
                        entry["source"], temp_path, entry["relative"], completed, total)
                    if os.path.exists(target):
                        raise RuntimeError(u"复制过程中目标文件被其他进程创建：{0}".format(
                            entry["relative"]))
                    os.replace(temp_path, target)
                    temp_files.remove(temp_path)
                    created_files.append(target)

            self._plan = query_component_state(self._plan, cancelled=self._is_cancelled)
            if self._plan.get("state") != "ready":
                raise RuntimeError(self._plan.get("message") or u"组件复制后校验失败")
            self.progress.emit(100, u"组件加载完成")
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
            if staging_folder and os.path.isdir(staging_folder):
                try:
                    shutil.rmtree(staging_folder)
                except OSError:
                    pass
            _remove_empty_directory(staging_root)
            self.failed.emit(str(exc))


def discard_staged_component(staging_folder, plugins_dir):
    staging_folder = _normal(staging_folder)
    staging_root = _normal(os.path.join(plugins_dir, ".AssetsManagerForUE_Staging"))
    if not _inside(staging_root, staging_folder):
        return False
    try:
        if os.path.isdir(staging_folder):
            shutil.rmtree(staging_folder)
        _remove_empty_directory(staging_root)
        return True
    except OSError:
        return False


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _restart_context():
    if unreal is None:
        raise RuntimeError(u"当前不在 Unreal Editor 中")
    project_file = _normal(unreal.Paths.convert_relative_path_to_full(
        unreal.Paths.get_project_file_path()))
    engine_dir = _normal(unreal.Paths.convert_relative_path_to_full(
        unreal.Paths.engine_dir()))
    editor_exe = os.path.join(engine_dir, "Binaries", "Win64", "UnrealEditor.exe")
    if not os.path.isfile(project_file):
        raise RuntimeError(u"没有找到当前工程的 .uproject：{0}".format(project_file))
    if not os.path.isfile(editor_exe):
        raise RuntimeError(u"没有找到 UnrealEditor.exe：{0}".format(editor_exe))
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if world is None:
        raise RuntimeError(u"当前没有可用于退出命令的编辑器 World")
    return project_file, editor_exe, world


def restart_editor(replacement_plan=None):
    """保存工程，后台等待当前 UE 退出，可选替换插件，然后重开同一工程。"""
    helper = None
    try:
        project_file, editor_exe, world = _restart_context()
        result = unreal.EditorLoadingAndSavingUtils.save_dirty_packages_with_dialog(
            True, True)
        if result is False:
            return False, u"用户取消了保存，未重启 UE"

        project_saved = _normal(unreal.Paths.convert_relative_path_to_full(
            unreal.Paths.project_saved_dir()))
        log_folder = os.path.join(project_saved, "AssetsManagerForUE")
        os.makedirs(log_folder, exist_ok=True)
        log_path = os.path.join(log_folder, "ComponentRestart.log")
        lines = [
            "$ErrorActionPreference = 'Stop'",
            "$logPath = {0}".format(_ps_quote(log_path)),
            "try {",
            "  Wait-Process -Id {0} -ErrorAction SilentlyContinue".format(os.getpid()),
            "  Start-Sleep -Milliseconds 1200",
        ]
        if replacement_plan:
            staging = _normal(replacement_plan.get("staging_folder"))
            target = _normal(replacement_plan.get("target_folder"))
            plugins_dir = _normal(replacement_plan.get("plugins_dir"))
            if (not _inside(plugins_dir, target)
                    or not _inside(os.path.join(plugins_dir, ".AssetsManagerForUE_Staging"), staging)
                    or not os.path.isdir(staging)):
                raise RuntimeError(u"暂存组件或目标组件路径不安全，已取消替换")
            component_name = replacement_plan.get("name") or os.path.basename(target)
            safe_name = "".join(
                "_" if char in '<>:"/\\|?*' else char
                for char in str(component_name)) or "Component"
            backup = os.path.join(
                project_saved, "AssetsManagerForUE", "ComponentBackups",
                time.strftime("%Y%m%d_%H%M%S") + "_" + safe_name + "_" + uuid.uuid4().hex[:8])
            lines.extend([
                "  $stage = {0}".format(_ps_quote(staging)),
                "  $target = {0}".format(_ps_quote(target)),
                "  $backup = {0}".format(_ps_quote(backup)),
                "  $hadOld = Test-Path -LiteralPath $target",
                "  if ($hadOld) {",
                "    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null",
                "    Move-Item -LiteralPath $target -Destination $backup",
                "  }",
                "  try {",
                "    Move-Item -LiteralPath $stage -Destination $target",
                "  } catch {",
                "    if ($hadOld -and -not (Test-Path -LiteralPath $target) -and (Test-Path -LiteralPath $backup)) {",
                "      Move-Item -LiteralPath $backup -Destination $target",
                "    }",
                "    throw",
                "  }",
                "  Add-Content -LiteralPath $logPath -Value ('组件更新完成；原版本备份：' + $backup)",
            ])
        lines.extend([
            # Start-Process 会把 ArgumentList 重新拼接成命令行；显式保留双引号，
            # 确保带空格或中文的 .uproject 路径仍作为一个参数传入。
            "  Start-Process -FilePath {0} -ArgumentList @({1})".format(
                _ps_quote(editor_exe), _ps_quote('"' + project_file + '"')),
            "} catch {",
            "  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $logPath) | Out-Null",
            "  Add-Content -LiteralPath $logPath -Value ((Get-Date).ToString('s') + ' ' + $_.Exception.ToString())",
            "}",
        ])
        script = "\r\n".join(lines)
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        powershell = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        helper = subprocess.Popen(
            [powershell, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
             "-EncodedCommand", encoded],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creation_flags,
        )
        if helper.poll() is not None:
            raise RuntimeError(u"UE 重启辅助进程未能启动")
        unreal.SystemLibrary.execute_console_command(world, "QUIT_EDITOR")
        return True, ""
    except Exception as exc:
        if helper is not None and helper.poll() is None:
            try:
                helper.terminate()
            except Exception:
                pass
        return False, u"重启 UE 失败：{0}".format(exc)
