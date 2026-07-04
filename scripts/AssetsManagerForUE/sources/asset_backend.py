#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
asset_backend —— 资产 tab 的「无 Qt」后端数据/动作层，供原生 EUW（经 euw_bridge）调用。

它把 sources/assetTools.py 里和 UI 无关的逻辑抽出来用纯函数实现，便于原生界面复用：
    - 项目/类型列表   <- projectSetting.json（与 Qt 版同源）
    - 资产列表        <- PostgreSQL（与 assetTools.get_database 同一条 SQL）
    - 导入            <- 忠实复刻 assetTools.AssetToolsUI.importFile 的核心（无 Qt）

不依赖 PySide，可在 UE 主线程/蓝图节点里直接调用。
"""

import os
import sys

# 让 `from utils import ...` 可用（与 assetTools 同样的做法：把包目录加进 sys.path）
_PKG_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__))).replace('\\', '/')
if _PKG_DIR not in sys.path:
    sys.path.append(_PKG_DIR)

# venv 路径：psycopg2 等第三方库在这里（与 assetTools.py 一致）。
# UE 启动时没有加这个路径，所以后端被调用时要自己确保它在 sys.path 里。
_VENV = "Y:/MCCTools/src/venv/Lib/site-packages"
if os.path.isdir(_VENV) and _VENV not in sys.path:
    sys.path.insert(0, _VENV)

# 与 assetTools.py 保持一致的常量
_JSON_PATH = 'Y:/ACTools/CGTools/scripts/AssetsManagerForMaya'   # projectSetting.json 所在
_DB_HOST = '10.0.203.34'
_DB_PORT = '5432'


# --------------------------------------------------------------------------- #
# 配置 / 登录
# --------------------------------------------------------------------------- #
def project_setting():
    from utils import jsonHelper
    return jsonHelper.readDictFromFile('%s/config/projectSetting.json' % _JSON_PATH)


def get_projects():
    return [str(p) for p in project_setting().get('projects', [])]


def get_types():
    return [str(t) for t in project_setting().get('type', [])]


def _login():
    """复用主界面的登录信息：%APPDATA%/ShotManagerTemp/setting.json -> {user, password}。"""
    import json
    sm_json = "{}/ShotManagerTemp/setting.json".format(os.environ.get('APPDATA'))
    if os.path.isfile(sm_json):
        try:
            with open(sm_json, 'rb') as fp:
                d = json.loads(fp.read())
            return d.get('user', ''), d.get('password', '')
        except Exception:
            pass
    # 兜底：SMConfig
    try:
        from config import SMConfig
        return (SMConfig.SMConfig().getPrefsValue("Info/user", ""),
                SMConfig.SMConfig().getPrefsValue("Info/password", ""))
    except Exception:
        return '', ''


# --------------------------------------------------------------------------- #
# 数据查询（与 assetTools.get_database 同一条 SQL）
# --------------------------------------------------------------------------- #
def query_assets(project, asset_type):
    """
    返回该 项目/类型 下的资产列表：
        [{name, zh_name, mod_status, rig_status, icon, folder}, ...]
    folder = icon 路径里 '/Icon/' 之前的部分（即资产根目录，和 importFile 取法一致）。
    """
    import psycopg2
    user, password = _login()
    sql = (
        'SELECT "asset.date","asset.name","asset.zh_name","asset.mod_artist",'
        '"asset.mod_status","asset.rig_artist","asset.rig_status","asset.icon" '
        'FROM public."asset" WHERE "asset.type" = \'%s\';' % asset_type
    )
    conn = cur = None
    rows = []
    try:
        conn = psycopg2.connect(database=project, user=user, password=password,
                                host=_DB_HOST, port=_DB_PORT)
        cur = conn.cursor()
        cur.execute(sql)
        for r in cur.fetchall():
            icon = r[7] or ''
            folder = icon.split('/Icon/')[0] if '/Icon/' in icon else ''
            rows.append({'name': r[1], 'zh_name': r[2],
                         'mod_status': r[4], 'rig_status': r[6],
                         'icon': icon, 'folder': folder})
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()
    return rows


def asset_names(project, asset_type):
    return [r['name'] for r in query_assets(project, asset_type)]


def _find_asset(project, asset_type, name):
    for r in query_assets(project, asset_type):
        if r['name'] == name:
            return r
    return None


def asset_folder(project, asset_type, name):
    r = _find_asset(project, asset_type, name)
    return r['folder'] if r else ''


def open_asset_dir(project, asset_type, name):
    """在资源管理器里打开资产目录，返回打开的路径（失败返回 '')。"""
    folder = asset_folder(project, asset_type, name)
    if folder and os.path.isdir(folder):
        os.startfile(folder)
        return folder
    return ''


# --------------------------------------------------------------------------- #
# 导入（忠实复刻 assetTools.AssetToolsUI.importFile / repathAssets，去掉 Qt 依赖）
# --------------------------------------------------------------------------- #
def import_asset(project, asset_type, name):
    """把选中资产的骨骼网格 FBX 导入 UE，返回状态串。"""
    import unreal
    from utils import assetFunctions

    r = _find_asset(project, asset_type, name)
    if not r or not r['folder']:
        return "Asset/path not found: %s" % name

    fbx_path = '%s/FBX/%s.fbx' % (r['folder'], name)
    if not os.path.isfile(fbx_path):
        return "FBX not found: %s" % fbx_path

    character_folder = '/Game/Assets/%s/%s/' % (asset_type, name)
    material_folder = character_folder + 'Material/'
    texture_folder = character_folder + 'Texture/'

    AF = assetFunctions.AssetFunctions()
    task = AF.buildImportTask(fbx_path, character_folder, AF.buildSkeletalMeshImportOptions())
    AF.executeImportTasks([task])

    if not unreal.EditorAssetLibrary.does_directory_exist(material_folder):
        unreal.EditorAssetLibrary.make_directory(material_folder)
    if not unreal.EditorAssetLibrary.does_directory_exist(texture_folder):
        unreal.EditorAssetLibrary.make_directory(texture_folder)

    _repath_assets(character_folder)
    return "Imported: %s -> %s" % (name, character_folder)


def _repath_assets(character_folder):
    """把导入产生的 Material / Texture 归位（同 assetTools.repathAssets）。"""
    import unreal
    lib = unreal.EditorAssetLibrary()
    for asset in lib.list_assets(character_folder):
        ad = lib.find_asset_data(asset)
        a = ad.get_asset()
        cls = a.get_class().get_name()
        path_name = a.get_path_name()
        nm = a.get_name()
        base = character_folder.rsplit('/', 1)[0]
        if cls in ('Material', 'MaterialInstanceConstant'):
            lib.rename_asset(path_name, '{0}/Material/{1}.{1}'.format(base, nm))
        elif cls == 'Texture2D':
            lib.rename_asset(path_name, '{0}/Texture/{1}.{1}'.format(base, nm))
