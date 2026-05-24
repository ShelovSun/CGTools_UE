import sys,os
scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/')
sys.path.append('%s/scripts/'% scriptsPath)
import Common
#from imp import reload
#reload(Common)