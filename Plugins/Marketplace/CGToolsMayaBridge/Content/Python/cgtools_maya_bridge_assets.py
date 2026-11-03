"""Lazy entry point: no asset manager window, database query, or login needed."""
import os
import sys

import unreal


def invoke(operation, payload_base64):
    scripts = unreal.Paths.convert_relative_path_to_full(unreal.Paths.engine_content_dir())
    scripts = os.path.join(scripts, "Python", "scripts")
    if scripts not in sys.path:
        sys.path.append(scripts)
    site_packages = "Y:/MCCTools/src/venv/Lib/site-packages"
    if site_packages not in sys.path:
        sys.path.append(site_packages)
    from AssetsManagerForUE.sources.maya_bridge_service import invoke as run
    return run(operation, payload_base64)
