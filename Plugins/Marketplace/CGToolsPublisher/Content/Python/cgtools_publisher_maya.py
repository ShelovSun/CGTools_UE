# -*- coding: utf-8 -*-
"""Bake a Maya archive before publishing; open the committed scene on request."""

import base64
import importlib.util
import hashlib
import json
import os
import shutil
import subprocess

import unreal


HANDOFF_SCRIPT = (
    "//fznas.diandian.info/AC/ADVRetargetUETool/ue57_adv_retarget_handoff.py"
)


def _registry_maya_locations():
    """Autodesk records custom-drive installs here; never modify the registry."""
    try:
        import winreg
    except ImportError:
        return []
    locations = []
    key_path = r"SOFTWARE\Autodesk\Maya\2022\Setup\InstallPath"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY, 0):
            try:
                with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view) as key:
                    value, _ = winreg.QueryValueEx(key, "MAYA_INSTALL_LOCATION")
                    if isinstance(value, str) and value.strip():
                        locations.append(value)
            except OSError:
                continue
    return locations


def _common_maya_locations():
    # Bound the fallback to conventional paths on fixed local drives. Do not
    # recursively scan disks or probe every mapped/network drive from UE's UI.
    locations = ["C:/Program Files/Autodesk/Maya2022"]
    for name in ("ProgramW6432", "ProgramFiles"):
        if os.environ.get(name):
            locations.append(os.path.join(os.environ[name], "Autodesk", "Maya2022"))
    if os.name == "nt":
        import ctypes
        drives = ctypes.windll.kernel32.GetLogicalDrives()
        for index in range(26):
            if drives & (1 << index):
                drive = chr(ord("A") + index) + ":/"
                if ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive)) == 3:
                    for relative in ("Program Files/Autodesk/Maya2022", "Autodesk/Maya2022", "Maya2022"):
                        locations.append(os.path.join(drive, relative))
    return locations


def _maya_bin_directory(location):
    location = str(location or "").strip().strip('"\'')
    if not location:
        return ""
    location = os.path.normpath(os.path.expanduser(os.path.expandvars(location)))
    if os.path.basename(location).lower() in ("maya.exe", "mayapy.exe"):
        return os.path.dirname(location)
    if os.path.basename(location).lower() == "bin":
        return location
    return os.path.join(location, "bin")


def _make_maya_finder(handoff):
    # Use one complete installation for both the background worker and visible
    # Maya. The shared ADV backend targets Maya 2022; never auto-pick another
    # version. An artist's explicit ADV/environment setting keeps precedence.
    selected_bin = ""

    def find(file_name):
        nonlocal selected_bin
        if file_name not in ("maya.exe", "mayapy.exe"):
            raise ValueError("不支持的 Maya 程序：" + str(file_name))
        if not selected_bin:
            settings = handoff.read_settings()
            candidates = [
                ("ADV maya_location", settings.get("maya_location", "")),
                ("MAYA_LOCATION", os.environ.get("MAYA_LOCATION", "")),
            ]
            candidates.extend(("Maya 2022 注册表", path) for path in _registry_maya_locations())
            candidates.extend(("Maya 2022 常用目录", path) for path in _common_maya_locations())
            checked = []
            seen = set()
            for source, location in candidates:
                directory = _maya_bin_directory(location)
                key = os.path.normcase(directory)
                if not directory or key in seen:
                    continue
                seen.add(key)
                missing = [name for name in ("maya.exe", "mayapy.exe")
                           if not os.path.isfile(os.path.join(directory, name))]
                if not missing:
                    selected_bin = directory
                    unreal.log("[CGToolsPublisher] Maya 安装目录（" + source + "）：" + directory)
                    break
                checked.append(source + "：" + directory + "（缺少 " + "、".join(missing) + "）")
            if not selected_bin:
                settings_path = getattr(handoff, "SETTINGS_FILE_PATH", "ADV 本机设置文件")
                raise RuntimeError(
                    "找不到完整的 Maya 2022 安装：同一 bin 目录中需要 maya.exe 和 mayapy.exe。\n"
                    "请将环境变量 MAYA_LOCATION 或以下设置文件的 maya_location 指向 Maya 安装根目录"
                    "（例如 D:\\Program Files\\Autodesk\\Maya2022）：\n" + str(settings_path)
                    + "\n已检查：\n" + "\n".join(checked)
                )
        return os.path.join(selected_bin, file_name)

    return find


def _load_handoff_module():
    if not os.path.isfile(HANDOFF_SCRIPT):
        raise RuntimeError("无法读取 ADV UE→Maya 脚本：" + HANDOFF_SCRIPT)
    # Load a private instance, without running the installer or changing the
    # existing menu's globals, Content Browser selection, or startup scripts.
    spec = importlib.util.spec_from_file_location(
        "cgtools_publisher_adv_handoff", HANDOFF_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("run", "selected_source_assets", "_show_bake_summary",
                 "launch_bake_worker", "write_json_atomic", "_find_maya_program", "read_settings"):
        if not callable(getattr(module, name, None)):
            raise RuntimeError("ADV 脚本接口已变化，缺少：" + name)
    module._find_maya_program = _make_maya_finder(module)
    return module


def _copy_maya_archive(source, destination):
    if not source or not source.lower().endswith(".ma") or not os.path.isfile(source):
        raise RuntimeError("未找到烘焙生成的 Maya ASCII 场景：" + str(source))
    with open(source, "rb") as handle:
        if not handle.read(128).lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"//Maya ASCII"):
            raise RuntimeError("烘焙结果不是有效的 Maya ASCII 场景：" + source)
    if not destination.lower().endswith(".ma") or not os.path.isdir(os.path.dirname(destination)):
        raise RuntimeError("Maya 暂存目标目录不存在或扩展名不是 .ma：" + destination)

    def digest(path):
        value = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                value.update(block)
        return value.digest()

    shutil.copyfile(source, destination)
    if digest(source) != digest(destination):
        raise RuntimeError("Maya 场景暂存校验失败：" + destination)


def bake_animation_archive(object_path, output_ma):
    asset = unreal.load_asset(object_path)
    if not isinstance(asset, unreal.AnimSequence):
        raise RuntimeError("无法加载当前发布的动画序列：" + object_path)
    handoff = _load_handoff_module()
    # The original entry point queries the entire Content Browser selection.
    # Restrict only this private module to the current published source asset.
    handoff.selected_source_assets = lambda anim_only=False: [asset]
    # Native UI combines publication and handoff results into one completion
    # dialog; retain the original cancellable progress and worker lifecycle.
    handoff._show_bake_summary = lambda manifest, state: None
    # The shared tool defaults to opening every bake result. Change only this
    # private run's worker manifest, before launch, to keep baking headless.
    # Opening happens separately, after all three publication files commit.
    launch_worker = handoff.launch_bake_worker

    def launch_without_opening(manifest_path, reports_dir):
        with open(manifest_path, "r", encoding="utf-8-sig") as handle:
            manifest = json.load(handle)
        jobs = manifest.get("jobs") or []
        if manifest.get("mode") != "bake" or len(jobs) != 1 or jobs[0].get("object_path") != object_path:
            raise RuntimeError("ADV 任务与当前发布动画不一致，已停止烘焙。")
        manifest["open_results"] = False
        handoff.write_json_atomic(manifest_path, manifest)
        return launch_worker(manifest_path, reports_dir)

    handoff.launch_bake_worker = launch_without_opening
    result = handoff.run("bake")
    if not isinstance(result, dict):
        raise RuntimeError("ADV 自动处理没有返回结果，请查看 Output Log。")
    state = result.get("progress_result") or {}
    status = state.get("status", "failed")
    ok = (
        status == "completed"
        and int(state.get("succeeded_jobs", 0) or 0) == 1
        and not int(state.get("failed_jobs", 0) or 0)
        and not int(state.get("cancelled_jobs", 0) or 0)
        and not result.get("ue_export_errors")
    )
    details = list(result.get("ue_export_errors") or [])
    if ok:
        try:
            jobs = result.get("jobs") or []
            if len(jobs) != 1 or jobs[0].get("object_path") != object_path:
                raise RuntimeError("ADV 返回的场景与当前发布动画不一致。")
            _copy_maya_archive(jobs[0].get("output_scene"), output_ma)
        except Exception as exc:
            ok = False
            details.append(str(exc))
    if ok:
        message = "Maya 动画反求、烘焙与 .ma 暂存完成。"
    elif status == "cancelled":
        message = "Maya 自动处理已安全取消。"
    else:
        message = "Maya 自动处理未完成。"
    if state.get("message"):
        details.append(str(state["message"]))
    if (result.get("launch") or {}).get("error"):
        details.append(str(result["launch"]["error"]))
    for label, path in (
        ("结果目录", result.get("output_dir")),
        ("报告目录", result.get("reports_dir")),
        ("Worker 日志", state.get("worker_log_path")),
    ):
        if path:
            details.append(label + "：" + str(path))
    if details:
        message += "\n" + "\n".join(dict.fromkeys(details))
    return {"ok": ok, "message": message}


def open_published_scene(scene_ma):
    if not scene_ma.lower().endswith(".ma") or not os.path.isfile(scene_ma):
        raise RuntimeError("已发布的 Maya 场景不存在或不可访问：" + scene_ma)
    maya_exe = _load_handoff_module()._find_maya_program("maya.exe")
    if not maya_exe:
        raise RuntimeError("找不到 Maya maya.exe，请检查原 ADV 工具的 Maya 路径设置。")
    # Launch a separate Maya, preserving any currently open artist scenes.
    subprocess.Popen(
        [maya_exe, "-file", os.path.abspath(scene_ma)],
        cwd=os.path.dirname(os.path.abspath(scene_ma)),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return {"ok": True, "message": "已通知独立 Maya 打开发布的场景：\n" + scene_ma}


def invoke(request_base64):
    """Base64 transport keeps Unicode paths and Python quoting independent."""
    try:
        request = json.loads(base64.b64decode(request_base64).decode("utf-8"))
        if request["operation"] == "bake":
            response = bake_animation_archive(request["object_path"], request["output_ma"])
        elif request["operation"] == "open_scene":
            response = open_published_scene(request["scene_ma"])
        else:
            raise RuntimeError("不支持的 Maya 桥接操作：" + str(request["operation"]))
    except Exception as exc:
        response = {"ok": False, "message": "无法执行 Maya 自动处理：" + str(exc)}
    if not response["ok"]:
        unreal.log_warning("[CGToolsPublisher] " + response["message"])
    return base64.b64encode(
        json.dumps(response, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
