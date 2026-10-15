"""Server animation packages mapped to the selected asset's UE Action folder."""

import hashlib
import json
import os
import shutil
import uuid

from . import ue_asset_service


def action_context(source_file):
    source = os.path.abspath(os.path.normpath(str(source_file or ""))).replace("\\", "/")
    if not source_file or os.path.splitext(source)[1].lower() != ".uasset":
        raise ValueError(u"请选择动作对应的 .uasset 文件")
    marker = source.lower().rfind("/animations/")
    if marker < 0:
        raise ValueError(u"动作文件不在项目的 Animations 目录中：{0}".format(source))
    parts = source[marker + len("/animations/"):].split("/")
    if len(parts) < 4 or parts[2].lower() != "action":
        raise ValueError(u"动作路径必须为 项目/Animations/类型/资产名/Action：{0}".format(source))
    project_root = source[:marker]
    asset_type, asset_name = parts[:2]
    game_folder = "/Game/Assets/{0}/{1}".format(asset_type, asset_name)
    filename = os.path.splitext(os.path.basename(source))[0] + ".uasset"
    relative = "Assets/{0}/{1}/Action/{2}".format(asset_type, asset_name, filename)
    return {
        "source_file": source,
        "asset_name": asset_name,
        "asset_type": asset_type,
        "asset_root": "{0}/Assets/{1}/{2}".format(project_root, asset_type, asset_name),
        "game_folder": game_folder,
        "relative": relative,
        "package_name": "/Game/" + os.path.splitext(relative)[0],
    }


def _class_name(asset_data):
    return str(asset_data.asset_class_path.asset_name)


def asset_exists(context):
    """An empty directory or an Action-only folder does not count as the asset."""
    engine = ue_asset_service.unreal
    if engine is None:
        raise RuntimeError(u"当前不在 Unreal Editor 中")
    registry = engine.AssetRegistryHelpers.get_asset_registry()
    assets = registry.get_assets_by_path(context["game_folder"], recursive=True)
    return any(_class_name(data) == "SkeletalMesh" for data in assets)


def build_import_plan(source_file, project_content_dir=None, include_asset=False):
    context = action_context(source_file)
    source = context["source_file"]
    if not os.path.isfile(source):
        raise FileNotFoundError(u"找不到同名 UE 动画包：{0}".format(source))
    target_root = ue_asset_service._project_content_dir(project_content_dir)
    relative_stem = os.path.splitext(context["relative"])[0]
    source_stem = os.path.splitext(source)[0]
    files = []
    for extension in sorted(ue_asset_service.PACKAGE_EXTENSIONS - frozenset((".umap",))):
        candidate = source if extension == ".uasset" else source_stem + extension
        if not os.path.isfile(candidate):
            continue
        relative = relative_stem + extension
        files.append({
            "source": candidate,
            "target": os.path.join(target_root, relative).replace("\\", "/"),
            "relative": relative,
            "extension": extension,
            "size": os.path.getsize(candidate),
        })
    main_object = context["package_name"] + "." + os.path.basename(relative_stem)
    plan = {
        "action_context": context,
        "asset_root": context["asset_root"],
        "source_root": os.path.dirname(source),
        "target_root": target_root.replace("\\", "/"),
        "files": files,
        "package_object_paths": [main_object],
        "main_object_path": main_object,
        "prerequisite_plan": None,
    }
    if include_asset:
        prerequisite = ue_asset_service.build_import_plan(context["asset_root"], target_root)
        if not prerequisite.get("source_available"):
            raise RuntimeError(u"服务器资产没有可加载的 UE 发布包：{0}/UE".format(context["asset_root"]))
        if not any(path.lower().startswith(context["game_folder"].lower() + "/")
                   for path in prerequisite["package_object_paths"]):
            raise RuntimeError(u"服务器 UE 发布包不包含目标资产目录 {0}，无法先加载该资产。".format(context["game_folder"]))
        # The action library is authoritative when the asset's older UE export
        # also contains an animation package at this exact destination.
        by_target = {os.path.normcase(entry["target"]): entry for entry in prerequisite["files"]}
        by_target.update({os.path.normcase(entry["target"]): entry for entry in files})
        plan["files"] = list(by_target.values())
        plan["package_object_paths"] = list(dict.fromkeys(prerequisite["package_object_paths"] + [main_object]))
        plan["prerequisite_plan"] = prerequisite
    plan["files"].sort(key=lambda entry: (entry["extension"] in ue_asset_service.PRIMARY_EXTENSIONS, entry["relative"].lower()))
    plan = ue_asset_service.query_filesystem_state(plan, verify_content=True)
    return _accept_normalized_copy(plan)


def _repair_record_path(plan):
    key = hashlib.sha256(plan["action_context"]["relative"].lower().encode("utf-8")).hexdigest()
    return os.path.join(os.path.dirname(plan["target_root"]), "Saved", "CGTools", "ActionLoading", key + ".json")


def _action_entries(plan):
    stem = os.path.splitext(plan["action_context"]["relative"])[0]
    return [entry for entry in plan["files"] if os.path.splitext(entry["relative"])[0] == stem]


def _accept_normalized_copy(plan):
    """Recognize our resave only while BOTH source and local bytes are unchanged."""
    if not plan.get("different_files"):
        return plan
    try:
        with open(_repair_record_path(plan), encoding="utf-8") as stream:
            record = json.load(stream)
        entries = _action_entries(plan)
        snapshots = record["files"]
        if set(snapshots) != {entry["relative"] for entry in entries}:
            return plan
        for entry in entries:
            snapshot = snapshots[entry["relative"]]
            if (ue_asset_service._sha1(entry["source"]) != snapshot["source_sha1"]
                    or ue_asset_service._sha1(entry["target"]) != snapshot["target_sha1"]):
                return plan
    except (OSError, ValueError, KeyError, TypeError):
        return plan
    accepted = set(snapshots)
    plan["different_files"] = [name for name in plan["different_files"] if name not in accepted]
    plan["existing_files"] = sorted(set(plan["existing_files"]) | accepted)
    plan["keep_existing_files"] = sorted(accepted)
    if not plan["different_files"]:
        plan["state"] = "partial" if plan["missing_files"] else "ready"
        plan["message"] = u"已识别本工具修复过的动画包"
    return plan


def _normalize_animation(plan, animation):
    """Repair legacy disk-only renames locally, with a recoverable original."""
    context = plan["action_context"]
    expected_name = context["package_name"].rsplit("/", 1)[1]
    if animation.get_name() == expected_name:
        return
    engine = ue_asset_service.unreal
    package = animation.get_outer()
    if engine.find_object(package, expected_name):
        raise RuntimeError(u"动画包内已有同名对象，无法修复：{0}".format(expected_name))
    entries = _action_entries(plan)
    snapshots = {}
    for entry in entries:
        source_hash = ue_asset_service._sha1(entry["source"])
        if source_hash != ue_asset_service._sha1(entry["target"]):
            raise RuntimeError(u"本地动画已被修改，未自动修复或覆盖：{0}".format(entry["target"]))
        snapshots[entry["relative"]] = {"source_sha1": source_hash}
    record_path = _repair_record_path(plan)
    backup_dir = os.path.join(os.path.dirname(record_path), "Backups", uuid.uuid4().hex)
    os.makedirs(backup_dir)
    for entry in entries:
        shutil.copy2(entry["target"], os.path.join(backup_dir, os.path.basename(entry["target"])))
    renamed = False
    try:
        if not animation.rename(expected_name):
            raise RuntimeError(u"UE 无法修正动画对象名称")
        renamed = True
        # SavePackages accepts the package even before the renamed object has
        # been registered, and updates Asset Registry with its new primary asset.
        if not engine.EditorLoadingAndSavingUtils.save_packages([package], False):
            raise RuntimeError(u"UE 无法保存修正后的动画包")
        for entry in entries:
            snapshots[entry["relative"]]["target_sha1"] = ue_asset_service._sha1(entry["target"])
        record = {"files": snapshots, "backup_directory": backup_dir}
        temporary = record_path + "." + uuid.uuid4().hex + ".tmp"
        try:
            with open(temporary, "x", encoding="utf-8") as stream:
                json.dump(record, stream, ensure_ascii=False, indent=2)
            os.replace(temporary, record_path)
        finally:
            if os.path.isfile(temporary):
                os.remove(temporary)
    except Exception as exc:
        recovery_errors = []
        # UObject.rename creates an old-name redirector. Renaming back into
        # that occupied name can cause a fatal UE assertion, so restore disk
        # bytes and require a restart if an in-memory rename already happened.
        for entry in entries:
            try:
                shutil.copy2(os.path.join(backup_dir, os.path.basename(entry["target"])), entry["target"])
            except OSError as recovery_exc:
                recovery_errors.append(str(recovery_exc))
        raise RuntimeError(u"动画名称修复失败：{0}\n原文件备份：{1}{2}{3}".format(
            exc, backup_dir,
            u"\n已尝试恢复原磁盘文件；内存中的名称已变化，请重启工程后重试。" if renamed else "",
            "\n" + "\n".join(recovery_errors) if recovery_errors else "")) from exc
    plan["repaired_legacy_name"] = True
    plan["repair_backup_directory"] = backup_dir


def register_import(plan):
    """Refresh on the UE thread; require a visible, correctly named animation."""
    context = plan["action_context"]
    prerequisite = plan.get("prerequisite_plan")
    if prerequisite:
        registration_plan = dict(prerequisite)
        registration_plan["package_object_paths"] = [
            path for path in prerequisite["package_object_paths"]
            if path.rsplit(".", 1)[0].lower() != context["package_name"].lower()]
        prerequisite = ue_asset_service.refresh_asset_registry(registration_plan)
        plan["prerequisite_plan"] = prerequisite
        if prerequisite.get("state") == "error":
            raise RuntimeError(prerequisite["message"])
    if not asset_exists(context):
        raise RuntimeError(u"当前工程仍未找到资产 {0}，请先将骨架网格体加载到 {1}。".format(context["asset_name"], context["game_folder"]))
    engine = ue_asset_service.unreal
    registry = engine.AssetRegistryHelpers.get_asset_registry()
    target_file = next(entry["target"] for entry in plan["files"] if entry["relative"] == context["relative"])
    registry.scan_files_synchronous([target_file], True)
    assets = registry.get_assets_by_package_name(context["package_name"])
    for data in assets:
        if _class_name(data) != "AnimSequence":
            continue
        object_path = "{0}.{1}".format(data.package_name, data.asset_name)
        animation = engine.EditorAssetLibrary.load_asset(object_path)
        if not animation or animation.get_editor_property("skeleton") is None:
            raise RuntimeError(u"动画文件已复制，但 UE 加载失败，请检查动画的骨架依赖：{0}".format(object_path))
        _normalize_animation(plan, animation)
        object_path = animation.get_path_name()
        data = engine.AssetRegistryHelpers.create_asset_data(animation)
        if not data.is_u_asset():
            raise RuntimeError(u"动画尚不能在内容浏览器中显示：{0}".format(object_path))
        if plan.get("repaired_legacy_name"):
            registry.scan_files_synchronous([target_file], True)
        plan.update(state="ready", main_object_path=object_path, message=u"动作加载完成：{0}".format(object_path))
        return plan
    raise RuntimeError(u"动画文件已复制，但 UE 未识别为动画序列：{0}".format(target_file))
