"""Asset prerequisite operations for the native Maya Bridge's Yes/No dialogs."""

import base64
import json
import os

import unreal

from ..config import commonSetting
from . import asset_fbx_service, ue_asset_service


def asset_context(request):
    parts = [str(request.get(key) or "") for key in ("project_name", "asset_type", "asset_name")]
    if any(not part or part in (".", "..") or any(c in part for c in '/\\:') for part in parts):
        raise ValueError(u"项目、类型或资产名无效，无法确定服务器资产路径")
    if parts[1] not in ("Characters", "Props"):
        raise ValueError(u"资产类型必须为 Characters 或 Props")
    settings = commonSetting(force_reload=True)
    root = settings.get("rootPath")
    if not isinstance(root, str) or not root.strip():
        raise ValueError(u"commonSetting.json 缺少有效的 rootPath")
    project, asset_type, name = parts
    return {"asset_root": os.path.normpath(os.path.join(root, project, "Assets", asset_type, name)).replace("\\", "/"),
            "asset_type": asset_type, "asset_name": name}


def _skeleton_available(path):
    asset = unreal.load_asset(path)
    return isinstance(asset, unreal.Skeleton)


def _copy_asset(plan):
    errors, completed = [], []
    worker = ue_asset_service.AssetCopyWorker(plan)
    worker.failed.connect(errors.append)
    worker.finished.connect(completed.append)
    with unreal.ScopedSlowTask(100, u"正在加载资产…") as progress:
        progress.make_dialog(True)
        last_percent = [0]

        def update(percent, relative):
            if progress.should_cancel():
                worker.cancel()
            delta = max(0, percent - last_percent[0])
            last_percent[0] = max(last_percent[0], percent)
            progress.enter_progress_frame(delta, u"正在加载：{0}".format(relative))

        worker.progress.connect(update)
        worker.run()
    if errors or not completed:
        raise RuntimeError(errors[0] if errors else u"资产加载未完成")
    return completed[0]


def recover_asset(operation, request):
    context = asset_context(request)
    result = {"status": "ready", "asset_root": context["asset_root"], "message": ""}
    if operation == "describe":
        return result
    skeleton = str(request.get("skeleton_path") or "")
    if not skeleton.startswith("/Game/"):
        raise ValueError(u"无效的 UE 骨架路径：{0}".format(skeleton))
    if operation == "load":
        plan = ue_asset_service.build_import_plan(context["asset_root"])
        if not plan.get("source_available"):
            result.update(status="missing_ue", message=u"该资产还没有可加载的 UE 文件")
            return result
        # Shared materials often differ between published assets. Always retain
        # the project version, even when equal-size files have different bytes.
        # build_import_plan already classifies every existing target, so no
        # content comparison is needed to choose this no-overwrite policy.
        plan["overwrite_files"] = []
        plan["keep_existing_files"] = sorted(
            set(plan.get("existing_files", []) + plan.get("different_files", [])),
            key=str.lower)
        plan["kept_existing_files"] = list(plan["keep_existing_files"])
        if plan.get("missing_files"):
            plan = _copy_asset(plan)
        plan = ue_asset_service.refresh_asset_registry(plan, require_placeable=False)
        if plan["state"] == "error":
            raise RuntimeError(plan["message"])
    elif operation == "import_fbx":
        imported = asset_fbx_service.import_asset(context["asset_root"], context["asset_type"], context["asset_name"])
        if not unreal.EditorAssetLibrary.save_directory(imported["destination"], only_if_is_dirty=True, recursive=True):
            raise RuntimeError(u"资产 FBX 已导入，但 UE 保存资产失败")
    else:
        raise ValueError(u"未知的资产恢复操作：{0}".format(operation))
    if not _skeleton_available(skeleton):
        raise RuntimeError(u"资产操作已完成，但仍未找到指定骨架：{0}。请检查资产发布内容或 Bridge 的骨架路径配置。".format(skeleton))
    return result


def invoke(operation, payload_base64):
    """Base64 JSON avoids embedding received asset names as executable code."""
    try:
        request = json.loads(base64.b64decode(payload_base64).decode("utf-8"))
        result = recover_asset(operation, request)
    except Exception as exc:
        result = {"status": "error", "message": str(exc)}
        unreal.log_warning(u"Maya Bridge 资产恢复失败：{0}".format(exc))
    return base64.b64encode(json.dumps(result, ensure_ascii=False).encode("utf-8")).decode("ascii")
