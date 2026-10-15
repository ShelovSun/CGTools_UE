"""The asset card's Import FBX operation, also used by Maya Bridge recovery."""

import os

import unreal

from ..utils import assetFunctions


def repath_assets(character_folder):
    library = unreal.EditorAssetLibrary
    for asset_path in library.list_assets(character_folder):
        asset = library.find_asset_data(asset_path).get_asset()
        asset_class = asset.get_class().get_name()
        subfolder = {"Material": "Material", "MaterialInstanceConstant": "Material",
                     "Texture2D": "Texture"}.get(asset_class)
        if subfolder:
            target = "{0}/{1}/{2}.{2}".format(character_folder.rstrip("/"), subfolder, asset.get_name())
            if asset.get_path_name() != target and not library.rename_asset(asset.get_path_name(), target):
                raise RuntimeError(u"无法整理导入的资源：{0}".format(asset.get_path_name()))


def import_asset(asset_root, asset_type, asset_name):
    """Use the existing skeletal FBX options without requiring an asset-card UI."""
    fbx_path = os.path.join(asset_root, "FBX", asset_name + ".fbx").replace("\\", "/")
    if not os.path.isfile(fbx_path):
        raise FileNotFoundError(u"找不到资产 FBX：{0}".format(fbx_path))
    destination = "/Game/Assets/{0}/{1}".format(asset_type, asset_name)
    functions = assetFunctions.AssetFunctions()
    task = functions.buildImportTask(fbx_path, destination, functions.buildSkeletalMeshImportOptions())
    functions.executeImportTasks([task])
    # UE 5.7 Interchange can report imported objects separately from path strings.
    paths = list(task.get_editor_property("imported_object_paths"))
    if not paths and not task.get_objects():
        raise RuntimeError(u"Import FBX 未生成资产：{0}".format(fbx_path))
    for subfolder in ("Material", "Texture"):
        folder = destination + "/" + subfolder
        if not unreal.EditorAssetLibrary.does_directory_exist(folder):
            unreal.EditorAssetLibrary.make_directory(folder)
    repath_assets(destination)
    return {"destination": destination, "imported_paths": paths}
