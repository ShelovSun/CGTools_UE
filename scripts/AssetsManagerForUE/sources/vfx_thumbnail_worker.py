"""Headless UE worker. Executed as a script, never imported by the browser UI."""

import json
import os
import time
from pathlib import Path

import unreal


def main(max_requests=24):
    job = Path(os.environ["CGTOOLS_VFX_THUMBNAIL_JOB"])
    bridge = getattr(unreal, "CGToolsAssetBridgeLibrary", None)
    export = getattr(bridge, "export_external_vfx_thumbnail", None)
    results = job / "results.jsonl"

    def report(value):
        with results.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + "\n")

    if export is None:
        report({"fatal": "读取旧特效预览图需要 CGToolsAssetBridge 1.3.3，请更新插件并重启 UE"})
        return
    started = last_work = time.monotonic()
    attempted = set()
    # Bound worker memory and lifetime. No UE object API runs in a Python thread.
    while time.monotonic() - started < 180 and len(attempted) < max_requests:
        try:
            request = json.loads((job / "requests.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            time.sleep(0.1)
            continue
        candidate = next((asset for asset in request.get("assets", [])
                          if asset["thumbnail"] not in attempted), None)
        if candidate is None:
            if time.monotonic() - last_work > 15:
                break
            time.sleep(0.1)
            continue
        source = candidate["source_file"]
        png = Path(candidate["thumbnail"])
        attempted.add(str(png))
        temporary = png.with_name(png.stem + ".writing_{0}.png".format(os.getpid()))
        error = ""
        success = png.is_file()
        try:
            if not success:
                before = Path(source).stat()
                expected = candidate.get("source_signature")
                if expected and list(expected) != [before.st_size, before.st_mtime_ns]:
                    raise RuntimeError("服务器特效已更新，请刷新特效库后重试")
                error = str(export(source, request["content_root"], str(temporary)))
                after = Path(source).stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    error = "ERROR|读取期间服务器特效已更新，请刷新特效库后重试"
                if not error and temporary.is_file():
                    os.replace(str(temporary), str(png))
                    success = True
                elif not error:
                    error = "ERROR|原生缩略图接口未生成 PNG"
            if error.startswith("NO_THUMBNAIL|"):
                Path(candidate["no_thumbnail"]).parent.mkdir(parents=True, exist_ok=True)
                Path(candidate["no_thumbnail"]).write_text(error, encoding="utf-8")
        except Exception as exc:
            error = "ERROR|{0}".format(exc)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        report({"source_file": source, "thumbnail": str(png),
                "success": success, "error": error})
        # Release loaded external effects and dependencies between requests.
        unreal.SystemLibrary.collect_garbage()
        last_work = time.monotonic()


if __name__ == "__main__":
    main()
