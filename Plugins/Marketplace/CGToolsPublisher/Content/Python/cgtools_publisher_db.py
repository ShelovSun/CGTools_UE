# -*- coding: utf-8 -*-
"""Database adapter for CGToolsPublisher.

The native editor module passes only Base64-encoded JSON. Credentials are read
locally from the same ShotManager settings used by the Maya publisher and are
never returned to C++, printed, or written into a published asset directory.
"""

from __future__ import annotations

import base64
import configparser
import datetime
import json
import os
import sys
from pathlib import Path


_PLUGIN_PYTHON_DIR = Path(__file__).resolve().parent
_COMMON_SETTING_PATH = Path(r"Y:\MCCTools\config\ShotManager_config\commonSetting.json")
_UE_COMPLETED_STATUS = "已完成"
_SITE_PACKAGES = _PLUGIN_PYTHON_DIR / "Lib" / "site-packages"
if str(_SITE_PACKAGES) not in sys.path:
    sys.path.insert(0, str(_SITE_PACKAGES))


def _credentials():
    appdata = Path(os.environ.get("APPDATA", ""))
    setting_json = appdata / "ShotManagerTemp" / "setting.json"
    if setting_json.is_file():
        try:
            data = json.loads(setting_json.read_text(encoding="utf-8-sig"))
            user = str(data.get("user", "")).strip()
            password = str(data.get("password", ""))
            if user:
                return user, password
        except Exception:
            pass

    prefs_ini = appdata / "ShotManagerTemp" / "Configs" / "prefs.ini"
    if prefs_ini.is_file():
        config = configparser.ConfigParser()
        config.read(str(prefs_ini), encoding="utf-8-sig")
        user = config.get("Info", "user", fallback="").strip()
        password = config.get("Info", "password", fallback="")
        if user:
            return user, password

    raise RuntimeError(
        "找不到 ShotManager 登录信息，请先登录 ShotManager，或检查 "
        "%APPDATA%/ShotManagerTemp/setting.json 与 Configs/prefs.ini。"
    )


def _database_host():
    """与 AssetsManager/原生发布窗口同源；连接前重读，避免保留旧 host。"""
    try:
        data = json.loads(_COMMON_SETTING_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("无法读取数据库配置 {0}：{1}".format(_COMMON_SETTING_PATH, exc)) from exc
    value = data.get("host") if isinstance(data, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("commonSetting.json 的 host 必须是非空字符串：{0}".format(_COMMON_SETTING_PATH))
    return value.strip()


def _connect(payload):
    import psycopg2

    project = str(payload["project"]).strip()
    if not project:
        raise ValueError("项目名为空。")
    host = _database_host()
    user, password = _credentials()
    return psycopg2.connect(
        database=project,
        user=user,
        password=password,
        host=host,
        port="5432",
        connect_timeout=5,
        application_name="CGToolsPublisher",
    ), user


def _check_scene_record(payload):
    conn, _user = _connect(payload)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT 1 FROM public.scene WHERE "scene.name" = %s LIMIT 1;',
                (str(payload["asset_name"]),),
            )
            exists = cursor.fetchone() is not None
        return {"ok": True, "exists": exists, "error": ""}
    finally:
        conn.close()


def _check_asset_record(payload):
    conn, _user = _connect(payload)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT 1 FROM public.asset WHERE "asset.name" = %s LIMIT 1;',
                (str(payload["asset_name"]),),
            )
            exists = cursor.fetchone() is not None
        return {"ok": True, "exists": exists, "error": ""}
    finally:
        conn.close()


def _write_scene_record(payload):
    conn, user = _connect(payload)
    asset_name = str(payload["asset_name"])
    chinese_name = str(payload.get("chinese_name") or "").strip()
    asset_type = str(payload["asset_type"])
    icon_path = str(payload.get("icon_path") or "")
    overwrite = bool(payload.get("overwrite"))
    date_value = int(datetime.datetime.now().strftime("%Y%m%d"))

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT 1 FROM public.scene WHERE "scene.name" = %s LIMIT 1;',
                (asset_name,),
            )
            exists = cursor.fetchone() is not None

            if exists and not overwrite:
                return {
                    "ok": False,
                    "exists": True,
                    "error": "数据库里已有同名资产，且本次未授权覆盖。",
                }

            if exists:
                # UE publishing owns the UE fields, not the scene's model work.
                cursor.execute(
                    '''
                    UPDATE public.scene
                    SET "scene.zh_name" = COALESCE(NULLIF(%s, ''), "scene.zh_name"),
                        "scene.ue_artist" = %s,
                        "scene.ue_status" = %s,
                        "scene.icon" = %s,
                        "scene.type" = %s
                    WHERE "scene.name" = %s;
                    ''',
                    (chinese_name, user, _UE_COMPLETED_STATUS,
                     icon_path, asset_type, asset_name),
                )
            else:
                cursor.execute(
                    '''
                    INSERT INTO public.scene (
                        "scene.date", "scene.name", "scene.zh_name",
                        "scene.artist", "scene.status", "scene.icon",
                        "scene.type", "scene.note", "scene.ue_artist", "scene.ue_status"
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                    ''',
                    (
                        date_value,
                        asset_name,
                        chinese_name,
                        "",
                        "未开始",
                        icon_path,
                        asset_type,
                        "",
                        user,
                        _UE_COMPLETED_STATUS,
                    ),
                )
        conn.commit()
        return {"ok": True, "exists": exists, "error": ""}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _write_asset_record(payload):
    conn, user = _connect(payload)
    asset_name = str(payload["asset_name"])
    chinese_name = str(payload.get("chinese_name") or "").strip()
    asset_type = str(payload["asset_type"])
    icon_path = str(payload.get("icon_path") or "")
    overwrite = bool(payload.get("overwrite"))
    date_value = int(datetime.datetime.now().strftime("%Y%m%d"))

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT 1 FROM public.asset WHERE "asset.name" = %s LIMIT 1;',
                (asset_name,),
            )
            exists = cursor.fetchone() is not None

            if exists and not overwrite:
                return {
                    "ok": False,
                    "exists": True,
                    "error": "数据库里已有同名资产，且本次未授权覆盖。",
                }

            if exists:
                # UE publishing owns only the UE artist/status, not model/rig work.
                cursor.execute(
                    '''
                    UPDATE public.asset
                    SET "asset.zh_name" = COALESCE(NULLIF(%s, ''), "asset.zh_name"),
                        "asset.ue_artist" = %s,
                        "asset.ue_status" = %s,
                        "asset.icon" = %s,
                        "asset.type" = %s
                    WHERE "asset.name" = %s;
                    ''',
                    (chinese_name, user, _UE_COMPLETED_STATUS,
                     icon_path, asset_type, asset_name),
                )
            else:
                cursor.execute(
                    '''
                    INSERT INTO public.asset (
                        "asset.date", "asset.name", "asset.zh_name",
                        "asset.mod_artist", "asset.mod_status", "asset.icon",
                        "asset.type", "asset.note", "asset.ue_artist", "asset.ue_status"
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                    ''',
                    (
                        date_value,
                        asset_name,
                        chinese_name,
                        "",
                        "未开始",
                        icon_path,
                        asset_type,
                        "",
                        user,
                        _UE_COMPLETED_STATUS,
                    ),
                )
        conn.commit()
        return {"ok": True, "exists": exists, "error": ""}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def invoke(operation, payload_base64):
    """Return Base64 JSON; UE receives Python string results using ``repr``."""
    try:
        payload = json.loads(base64.b64decode(payload_base64).decode("utf-8"))
        if operation == "check_scene_record":
            response = _check_scene_record(payload)
        elif operation == "check_asset_record":
            response = _check_asset_record(payload)
        elif operation == "write_scene_record":
            response = _write_scene_record(payload)
        elif operation == "write_asset_record":
            response = _write_asset_record(payload)
        else:
            raise ValueError("未知数据库操作：%s" % operation)
    except Exception as exc:
        response = {"ok": False, "exists": False, "error": str(exc)}
    response_json = json.dumps(response, ensure_ascii=False).encode("utf-8")
    return base64.b64encode(response_json).decode("ascii")
