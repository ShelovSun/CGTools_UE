#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Created: 28/1/2026 by Sunxh<175702994@qq.com>
# 这是Deadline任务的Pre执行文件，拷贝到 DeadlineRepository10\scripts\Jobs 里

import os
import subprocess
import glob
import winreg


def __main__(plugin_instance, *args):
    # 1. 获取 Job 对象
    deadlineJob = plugin_instance.GetJob()
    print("--- Listing all Job Info Keys ---")
    keys = deadlineJob.GetJobInfoKeys()
    for key in keys:
        print(f"Key: {key} | Value: {deadlineJob.GetJobInfoKeyValue(key)}")
    print("---------------------------------")
    
    # 2. 从 Comment 获取原始 UNC 根路径
    # 预期内容: \\10.0.196.152\pppp\UE5
    # try:
    #     # 打开注册表项
    #     reg_path = r"SOFTWARE\EpicGames\Unreal Engine\5.3"
    #     explorer = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path,
    #                              access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    #
    #     # 读取安装目录 (例如: C:\Program Files\Epic Games\UE_5.3)
    #     ue_install_dir, _type = winreg.QueryValueEx(explorer, "InstalledDirectory")
    #     winreg.CloseKey(explorer)
    #
    #     # 拼接出正确的执行文件路径
    #     ue_exe = os.path.join(ue_install_dir, "Engine", "Binaries", "Win64", "UnrealEditor-Cmd.exe")
    #
    #     if os.path.exists(ue_exe):
    #         deadlineJob.SetJobPluginInfoKeyValue("Executable", ue_exe)
    #         print(f"SUCCESS: Found UE 5.3 via Registry at: {ue_exe}")
    #     else:
    #         print(f"ERROR: Registry path exists but file not found: {ue_exe}")
    # except Exception as e:
    #     print(f"WARNING: Could not find UE 5.3 in Registry. Error: {str(e)}")
        
    comment_unc_path = deadlineJob.JobComment.strip()

    if not comment_unc_path.startswith("\\\\"):
        print("Error: Job Comment does not contain a valid UNC path (must start with \\\\).")
        print(f"Comment content: {comment_unc_path}")
        return

    print(f"UNC Path from Comment: {comment_unc_path}")

    # 3. 规范化路径
    # 确保是 Windows 反斜杠格式
    normalized_path = comment_unc_path.replace('/', '\\')
    # 4. 执行映射逻辑
    # 我们直接将 Comment 里的完整路径映射为 U: 盘根目录
    print(f"Mapping U: drive to {normalized_path}...")
    
    # 先清理旧映射
    # subprocess.call('subst U: /D', shell=True)
    subprocess.call(f'net use U: /delete /yes', shell=True)
    
    # 建立新映射 (使用双引号处理路径中的空格)
    # cmd = 'subst U: "{0}"'.format(normalized_path)
    cmd = f'net use U: "{normalized_path}" 123 /user:Render /persistent:no'
    exit_code = subprocess.call(cmd, shell=True)

    if exit_code == 0:
        print(f"SUCCESS: U: mapped to {normalized_path}")
    else:
        print(f"FAILURE: net failed with exit code {exit_code}")

    print("--- End of Pre-Job Script ---")
    print("修改了Executable:", deadlineJob.GetJobPluginInfoKeyValue("Executable"))
    print("修改了ProjectFile:", deadlineJob.GetJobPluginInfoKeyValue("ProjectFile"))

        # 4. 验证映射是否真实有效
        # if os.path.exists("U:"):
            # 搜索 .uproject
            # found = glob.glob("U:/*.uproject") + glob.glob("U:/*/*.uproject")
            # if found:
            #     real_uproject = found[0].replace('/', '\\')

                # 获取插件正在寻找的旧路径
                # job_project_file = deadlineJob.GetJobPluginInfoKeyValue("ProjectFile")

                # print(f"Real project found: {real_uproject}")

                # --- 终极方案：直接修改 Job 的启动命令行参数 ---
                # 虚幻插件通常把 ProjectFile 作为第一个参数传给命令行
                # 我们直接把这个 Job 属性改了
                # deadlineJob.SetJobPluginInfoKeyValue("ProjectFile", real_uproject)
                #
                # # 如果 copy 失败（权限不足），尝试用 Python 强制改变当前环境
                # # 很多时候 RenderPlugin 还是会读初始值，我们尝试一种更直接的强制写入
                # try:
                #     # 尝试强制更新插件的参数列表
                #     plugin_instance.SetProcessProperty("ProjectFile", real_uproject)
                # except:
                #     # 如果还是报错，我们退而求其次：
                #     # 既然不能在 U 盘里写，我们就在渲染机的本地临时目录写一个“替身”
                #     temp_uproject = os.path.join(os.environ["TEMP"], os.path.basename(job_project_file))
                #     import shutil
                #     shutil.copy2(real_uproject, temp_uproject)
                #     print(f"Fallback: Created local temp surrogate at {temp_uproject}")
                #     # 尝试让 Job 指向这个本地临时文件
                #     deadlineJob.SetJobPluginInfoKeyValue("ProjectFile", temp_uproject)
                # else:
                #     print("Names match, no redirection needed.")
                # deadlineJob.SetJobPluginInfoKeyValue("ProjectFile", real_uproject)
                # 2. 【核心修复】直接修改当前插件实例的内存参数
                # UnrealEngine 插件会从 PluginInfo 中读取 ProjectFile 启动命令行
                # 我们使用 SetPluginInfoEntry 强制覆盖当前进程看到的参数
                # try:
                #     plugin_instance.SetPluginInfoEntry("ProjectFile", real_uproject)
                #     print(f"SUCCESS: Plugin Instance memory updated -> {real_uproject}")
                # except Exception as e:
                #     print(f"DEBUG: SetPluginInfoEntry not available, trying SetProcessProperty: {str(e)}")
                #     # 备选方案：如果是某些旧版本或特殊封装
                #     try:
                #         plugin_instance.SetProcessProperty("ProjectFile", real_uproject)
                #     except:
                #         pass
                # print(f"SUCCESS: ReMap Final Project Path -> {real_uproject}")
            # else:
            #     print("ERROR: U: drive is empty or no .uproject found!")
        # else:
        #     print("ERROR: Subst command returned 0 but U: is not accessible. Permissions?")

