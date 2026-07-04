import sys,os
scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/')
sys.path.append('%s/scripts/'% scriptsPath)
import Common
#from imp import reload
#reload(Common)

# 注册 AssetsManager 原生 EUW 的蓝图节点（Category: AssetsManager）。
# 必须在编辑器启动时 import 一次，EUW 蓝图里才会出现这些节点；失败不影响其余功能。
try:
    import AssetsManagerForUE.euw_bridge  # noqa: F401
except Exception as _e:
    print("[init_unreal] euw_bridge 注册失败: %s" % _e)