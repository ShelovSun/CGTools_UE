"""Asset/scene record creation and two-stage deletion; worker-thread I/O only."""

import json
import os
import re
import shutil
import stat
import time

from ..config import commonSetting, databaseHost


TABLES = {"asset": "Assets", "scene": "Scenes"}
SUBFOLDERS = {
    "asset": ("Design", "FBX", "Icon", "Image", "Mod", "Original", "Rig", "Texture"),
    "scene": ("Assembly", "FBX", "GPU", "Icon", "Mod", "Original", "Port", "Proxy", "Texture"),
}
ROW_FIELDS = {
    "asset": ("date", "name", "zh_name", "mod_artist", "mod_status", "rig_artist",
              "rig_status", "icon", "note", "ue_status", "ue_artist"),
    "scene": ("date", "name", "zh_name", "artist", "status", "artist", "status", "icon", "note"),
}


def _segment(value, label):
    if (not isinstance(value, str) or not value or value != value.strip()
            or value in (".", "..") or len(value) > 255
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', value) or value.endswith((".", " "))
            or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", value)):
        raise ValueError("{0}为空或含有不能用于文件夹名的字符".format(label))
    return value


def _layout(settings, table, project, record_type=None, name=None):
    if table not in TABLES:
        raise ValueError("不支持的资产表")
    _segment(project, "项目")
    if project not in settings.get("DataBase", []):
        raise ValueError("项目不在 commonSetting.json 的 DataBase 列表中")
    root = settings.get("rootPath")
    if not isinstance(root, str) or not os.path.isabs(root):
        raise ValueError("commonSetting.json 的 rootPath 必须是绝对路径")
    root = os.path.realpath(os.path.abspath(root))
    folder = (settings.get("assetFolder") or "Assets") if table == "asset" else "Scenes"
    parts = [project, _segment(folder, "资产根目录")]
    if record_type is not None:
        parts.append(_segment(record_type, "类型"))
    if name is not None:
        parts.append(_segment(name, "资产名"))
    path = root
    for part in parts:
        path = os.path.join(path, part)
        # Reject symlinks/junctions below the configured root, including existing parents.
        if os.path.normcase(os.path.realpath(path)) != os.path.normcase(os.path.abspath(path)):
            raise ValueError("资产路径包含链接或重定向目录，不能安全操作：{0}".format(path))
    return path


def _types(settings, table, project):
    path = _layout(settings, table, project)
    result = []
    if os.path.isdir(path):
        with os.scandir(path) as entries:
            result = sorted(entry.name for entry in entries if entry.is_dir(follow_symlinks=False))
    if not result and table == "asset":
        result = list(settings.get("type") or ["Characters", "Props"])
    return result


def read_add_options(table, project=""):
    settings = commonSetting(force_reload=True)
    projects = list(settings.get("DataBase") or [])
    if not projects:
        raise ValueError("commonSetting.json 的 DataBase 列表为空")
    project = project if project in projects else projects[0]
    return {"projects": projects, "project": project, "types": _types(settings, table, project)}


def _connect(user, password, project, settings):
    import psycopg2
    return psycopg2.connect(
        database=project, user=user, password=password, host=databaseHost(settings),
        port="5432", connect_timeout=4,
        options="-c statement_timeout=8000 -c lock_timeout=4000")


def _lock(cur, table, project, record_type, name):
    # Serialize this tool's same-record add/delete requests without locking other assets.
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                ("AssetsManagerForUE." + table, json.dumps([project, record_type.casefold(), name.casefold()])))


def _mkdir(path, created):
    if os.path.isdir(path):
        return
    parent = os.path.dirname(path)
    if parent != path and not os.path.isdir(parent):
        _mkdir(parent, created)
    try:
        os.mkdir(path)
        created.append(path)
    except FileExistsError:
        if not os.path.isdir(path):
            raise


def add_record(user, password, table, project, record_type, name, zh_name):
    settings = commonSetting(force_reload=True)
    folder = _layout(settings, table, project, record_type, name)
    if record_type not in _types(settings, table, project):
        raise ValueError("所选类型不存在，请重新选择")
    if not isinstance(zh_name, str) or "\x00" in zh_name:
        raise ValueError("中文名含有无效字符")
    project_root = os.path.join(os.path.realpath(settings["rootPath"]), project)
    if not os.path.isdir(project_root):
        raise ValueError("项目目录不存在：{0}".format(project_root))
    # Store the configured spelling (normally Y:/...), as the Maya publisher does.
    table_folder = (settings.get("assetFolder") or "Assets") if table == "asset" else "Scenes"
    icon = os.path.join(settings["rootPath"], project, table_folder, record_type, name,
                        "Icon", name + ".png").replace("\\", "/")
    date = int(time.strftime("%Y%m%d"))
    if table == "asset":
        fields = ROW_FIELDS[table] + ("type",)
        values = (date, name, zh_name, user, "未开始", "", "未开始", icon, "", "未开始", "", record_type)
    else:
        fields = ("date", "name", "zh_name", "artist", "status", "icon", "note", "type")
        values = (date, name, zh_name, user, "未开始", icon, "", record_type)
    columns = ", ".join('"{0}.{1}"'.format(table, field) for field in fields)
    returning = ", ".join('"{0}.{1}"'.format(table, field) for field in ROW_FIELDS[table])
    conn = cur = None
    created = []
    try:
        conn = _connect(user, password, project, settings)
        cur = conn.cursor()
        _lock(cur, table, project, record_type, name)
        cur.execute('SELECT "{0}.name" FROM public."{0}" '
                    'WHERE lower("{0}.name") = lower(%s) AND lower("{0}.type") = lower(%s)'.format(table),
                    (name, record_type))
        if cur.fetchall():
            raise ValueError("资产已存在：{0} / {1} / {2}".format(project, record_type, name))
        cur.execute('INSERT INTO public."{0}" ({1}) VALUES ({2}) RETURNING {3}'.format(
            table, columns, ", ".join(["%s"] * len(values)), returning), values)
        rows = cur.fetchall()
        if len(rows) != 1:
            raise RuntimeError("添加资产未返回唯一记录")
        for sub in SUBFOLDERS[table]:
            _mkdir(os.path.join(folder, sub), created)
        if table == "asset":
            animation_folder = _segment(settings.get("animationFolder") or "Animations", "动作库目录")
            action_folder = _segment(settings.get("actionFolder") or "Action", "动作目录")
            action_path = os.path.join(project_root, animation_folder, record_type, name, action_folder)
            if os.path.normcase(os.path.realpath(action_path)) != os.path.normcase(os.path.abspath(action_path)):
                raise ValueError("动作库路径包含链接或重定向目录：{0}".format(action_path))
            _mkdir(action_path, created)
        conn.commit()
        return {"project": project, "type": record_type, "row": tuple(rows[0]), "operation": "add"}
    except Exception:
        if conn is not None:
            conn.rollback()
        # Only remove empty directories created by this request; never remove existing data.
        for path in reversed(created):
            try:
                os.rmdir(path)
            except OSError:
                pass
        raise
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()


def validated_delete_folder(settings, table, project, record_type, row):
    name = str(row[1])
    expected = _layout(settings, table, project, record_type, name)
    icon = str(row[7] or "").replace("\\", "/")
    if "/Icon/" not in icon or ".." in icon.split("/"):
        raise ValueError("卡片没有有效的 Icon 路径，无法安全确定服务器资产文件夹")
    folder = os.path.realpath(os.path.abspath(os.path.normpath(icon.rsplit("/Icon/", 1)[0])))
    if os.path.normcase(folder) != os.path.normcase(os.path.abspath(expected)):
        raise ValueError("Icon 路径与当前项目/类型/资产名不一致：{0}".format(folder))
    return expected


def delete_record(user, password, table, project, record_type, row):
    settings = commonSetting(force_reload=True)
    if table not in TABLES or len(row) < 8:
        raise ValueError("无效的资产记录")
    _segment(project, "项目")
    if project not in settings.get("DataBase", []):
        raise ValueError("项目不在 commonSetting.json 的 DataBase 列表中")
    _segment(record_type, "类型")
    _segment(str(row[1]), "资产名")
    conn = cur = None
    try:
        conn = _connect(user, password, project, settings)
        cur = conn.cursor()
        _lock(cur, table, project, record_type, str(row[1]))
        cur.execute('DELETE FROM public."{0}" WHERE "{0}.name" = %s AND "{0}.type" = %s '
                    'AND "{0}.icon" IS NOT DISTINCT FROM %s RETURNING "{0}.name"'.format(table),
                    (str(row[1]), record_type, row[7]))
        if len(cur.fetchall()) != 1:
            raise RuntimeError("记录不存在、已被修改或存在重名记录，请刷新后重试")
        conn.commit()
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()
    result = {"project": project, "type": record_type, "row": tuple(row), "operation": "delete",
              "folder": "", "folder_exists": False, "folder_error": ""}
    try:
        result["folder"] = validated_delete_folder(settings, table, project, record_type, row)
        try:
            mode = os.stat(result["folder"]).st_mode
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISDIR(mode):
                raise ValueError("服务器资产路径不是文件夹：{0}".format(result["folder"]))
            result["folder_exists"] = True
    except Exception as exc:
        result["folder_error"] = str(exc)
    return result


def delete_folder(table, result):
    settings = commonSetting(force_reload=True)
    folder = validated_delete_folder(settings, table, result["project"], result["type"], result["row"])
    if os.path.normcase(folder) != os.path.normcase(result["folder"]):
        raise ValueError("服务器目录已改变，取消删除")
    if not os.path.isdir(folder):
        raise ValueError("服务器资产文件夹不存在：{0}".format(folder))
    shutil.rmtree(folder)
    return result
