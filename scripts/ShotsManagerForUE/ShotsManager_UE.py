#!/usr/bin/env python
# -*- coding: utf-8 -*-
# <CGPipelineTool_UE> Created: 19/03/2021 by Sunxh<175702994@qq.com>
# log:


import os, sys, shutil,re,shutil,time,getpass,unreal
scriptsPath = os.path.split(os.path.realpath(__file__))[0].replace('\\', '/')
sys.path.append('Y:\\ACTools\\LGTSet_UE\\UE4.26.1\\venv\\Lib\\site-packages')
sys.path.append('%s/uti/'% scriptsPath)
# import Common
from PySide2 import QtUiTools, QtWidgets, QtCore, QtGui
from functools import partial
from .uti import jsonHelper, assetFunctions, sequenceFunctions
import imp
imp.reload(sequenceFunctions)
# imp.reload(jsonHelper)
imp.reload(assetFunctions)
SYSTEMP = os.environ['TMP'].replace('\\', '/')+'/'

sys.path.append('C:\\CgTeamWork_v6.2\\bin\\base')
try:
    import cgtw2
    t_tw = cgtw2.tw()
    login = t_tw.login.is_login()
    if login != True:
        msg = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, u"提示：", u"<h3>请先登入CGTeamWork !</h3>")
        msg.setStandardButtons(QtWidgets.QMessageBox.Cancel)
        msg.setDefaultButton(QtWidgets.QMessageBox.Cancel)
        msg.exec_()
except:
    msg = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, u"提示：", u"<h3>请先登入CGTeamWork !  并且安装在C盘标准目录下!</h3>")
    msg.setStandardButtons(QtWidgets.QMessageBox.Cancel)
    msg.setDefaultButton(QtWidgets.QMessageBox.Cancel)
    msg.exec_()

class CGPipelineToolUEUI(QtWidgets.QWidget):
    def __init__(self):
        super(CGPipelineToolUEUI, self).__init__()
        self.setLayout(QtWidgets.QHBoxLayout())
        self.layout().setContentsMargins(2, 2, 2, 2)
        self.idea_item_userRole = QtCore.Qt.UserRole
        self.scene_item_userRole = QtCore.Qt.UserRole + 1
        self.fbx_item_userRole = QtCore.Qt.UserRole + 2
        self.init_ui()
    def init_ui(self):
        global scriptsPath
        ui = QtCore.QFile('%s/ui/CGPipelineTool_UE.ui'%scriptsPath)
        ui.open(QtCore.QFile.ReadOnly)
        self.ui = QtUiTools.QUiLoader().load(ui)
        ui.close()
        self.layout().addWidget(self.ui)
        self.resize(900, 500)
        self.setWindowTitle('ShotsManager v 2.0.3')
        self.getStyleSheet()
        pos, size, proj, eps, shot = self.readSettings()
        if pos is not None and size is not None:
            self.resize(size)
            self.move(pos)
        self.getProject()
        if proj is not None:
            self.ui.Project_ComboBox.setCurrentIndex(proj)
        else:
            self.ui.Project_ComboBox.setCurrentIndex(0)
        self.getIdea_TW()
        if eps is not None:
            self.ui.ani_idea_listWgt.setCurrentRow(eps)
        else:
            self.ui.ani_idea_listWgt.setCurrentRow(0)
        self.getStage()
        self.getShot()
        if shot is not None:
            self.ui.ani_shot_listWgt.setCurrentRow(shot)
        else:
            self.ui.ani_shot_listWgt.setCurrentRow(0)
        self.getPath()
        self.getFile()
        self.ui.openFloder_bttn.clicked.connect(self.OpenFolder)
        self.ui.setting_bttn.setIcon(QtGui.QIcon('%s/icon/setting.png' % scriptsPath))
        self.ui.setting_bttn.setStyleSheet("border-style: flat; background: transparent;")
        self.ui.setting_bttn.clicked.connect(self.toolSetting_UI)
        self.ui.Project_ComboBox.currentIndexChanged.connect(self.changeProject)
        self.ui.ani_idea_listWgt.currentItemChanged.connect(self.changeIdea)
        self.ui.stages_listWgt.currentItemChanged.connect(self.changeStage)
        self.ui.ani_shot_listWgt.currentItemChanged.connect(self.changeShot)
        self.ui.ani_idea_line.textChanged.connect(self.idea_search)
        self.ui.ani_idea_line.addAction(QtGui.QIcon('%s/icon/search.png' % scriptsPath),
                                   QtWidgets.QLineEdit.LeadingPosition)
        self.ui.ani_shot_listWgt.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.ui.ani_shot_listWgt.customContextMenuRequested.connect(self.show_menu)
        self.ui.fbxImport_bttn.clicked.connect(self.importAnim)
        
    def getStyleSheet(self):
        global scriptsPath
        style_sheet_path = '%s/qss/UE5.qss' % scriptsPath
        with open(style_sheet_path) as (file):
            str = file.read()
        self.setStyleSheet(str)

    def readSettings(self):
        settings = QtCore.QSettings('Ani_Tools', 'Ani_Tools_Settings')
        pos = settings.value('pos')
        size = settings.value('size')
        proj = settings.value('proj')
        eps = settings.value('eps')
        shot = settings.value('shot')
        return (pos,size,proj,eps,shot)

    def rememberSettings(self):
        settings = QtCore.QSettings('Ani_Tools', 'Ani_Tools_Settings')
        settings.setValue('pos', self.pos())
        settings.setValue('size', self.size())
        settings.setValue('proj', self.ui.Project_ComboBox.currentIndex())
        settings.setValue('eps', self.ui.ani_idea_listWgt.currentRow())
        settings.setValue('shot', self.ui.ani_shot_listWgt.currentRow())

    def closeEvent(self, event):
        self.rememberSettings()

    def projectSetting(self):
        global scriptsPath
        data = jsonHelper.readDictFromFile('%s/config/projectSetting.json' % scriptsPath)
        return data

    def toolSetting_UI(self):
        Dialog = QtWidgets.QDialog(self)
        Dialog.resize(390, 95)
        Dialog.setWindowTitle(u"Enter Super User Password")
        font = QtGui.QFont()
        font.setFamily(u"Microsoft YaHei UI")
        font.setPointSize(10)
        label = QtWidgets.QLabel(Dialog)
        label.setText(u"*请输入管理员密码以获取修改权限：")
        label.setFont(font)
        label2 = QtWidgets.QLabel(Dialog)
        label2.setText(u"Password")
        label2.setFont(font)
        self.password_lineEdit = QtWidgets.QLineEdit(Dialog)
        self.password_lineEdit.setEchoMode(QtWidgets.QLineEdit.Password)
        bttnbox = QtWidgets.QDialogButtonBox(Dialog)
        bttnbox.setOrientation(QtCore.Qt.Horizontal)
        bttnbox.setStandardButtons(QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Ok)
        lay = QtWidgets.QGridLayout(Dialog)
        lay.setContentsMargins(10, 5, 10, 10)
        lay.addWidget(label,0,0,1,2)
        lay.addWidget(label2, 1, 0, 1, 1)
        lay.addWidget(self.password_lineEdit, 1, 1, 1, 1)
        lay.addWidget(bttnbox, 2, 1, 1, 1)
        bttnbox.accepted.connect(self.toolSetting)
        bttnbox.rejected.connect(Dialog.reject)
        Dialog.exec_()

    def toolSetting(self):
        password = self.password_lineEdit.text()
        jsonPath = '%s/config/projectSetting.json' % scriptsPath
        if password == "999999":
            if os.path.isfile(jsonPath):
                os.startfile(jsonPath)
            else:
                print(u"没有找到设置文件")
        else:
            QtWidgets.QMessageBox.warning(self, u'提示', u'密码错误')

    def _get_current_data(self):
        '''
        得到面板信息
        '''
        RootPath = self.projectSetting()['rootPath']
        current_project = str(self.ui.Project_ComboBox.currentText())
        current_idea = str(self.get_current_idea())
        current_idea_en = current_idea.split('   /   ')[0]
        if len(current_idea.split('   /   ')) == 2:
            current_idea_ch = current_idea.split('   /   ')[1]
        else:
            current_idea_ch = ''  
        current_stage = self.get_current_stage()
        current_shot = self.get_current_shot()
        current_fbxfile = ''
        return (RootPath,current_project,current_idea,current_idea_en,current_idea_ch,current_stage,current_shot,current_fbxfile)
    # def _get_curennt_data(self):
        # current_project = self.get_current_project()
        # current_idea = self.get_current_idea()
        # current_idea_data = self.get_current_idea_data()
        # current_scene = self.get_current_shot()
        # current_scene_data = self.get_current_scene_data()
        # return (current_project, current_idea, current_idea_data, current_scene, current_scene_data)
    def get_current_project(self):
        return self.ui.Project_ComboBox.currentText() 
    def get_current_idea(self):
        if self.ui.ani_idea_listWgt.currentItem():
            return self.ui.ani_idea_listWgt.currentItem().text()  
    def get_current_idea_data(self):
        if self.ui.ani_idea_listWgt.currentItem():
            return self.ui.ani_idea_listWgt.currentItem().data(self.idea_item_userRole) 
    def get_current_stage(self):
        if self.ui.stages_listWgt.currentItem():
            return self.ui.stages_listWgt.currentItem().text()    
        else:
            return "None"
    def get_current_shot(self):
        if self.ui.ani_shot_listWgt.currentItem():
            if self.ui.ani_shot_listWgt.currentItem().text() == '-- Custom --':
                return 'Custom'
            else:
                return ('{0}').format(self.ui.ani_shot_listWgt.currentItem().text())    
    def get_current_shot_data(self):
        if self.ui.ani_shot_listWgt.currentItem():
            if self.ui.ani_shot_listWgt.currentItem().text() == '-- Custom --':
                return 'Custom'
            else:
                return self.ui.ani_shot_listWgt.currentItem().data(self.scene_item_userRole)      
    
    def getPath(self):
        '''
        根据Project设置路径
        '''
        RootPath, current_project, current_idea, current_idea_en, current_idea_ch, current_stage, current_shot, current_fbxfile = self._get_current_data()
        self.ui.aniPath_label.setText(('{0}/{1}/Projects').format(self.projectSetting()['rootPath'], current_project))
        if current_idea != "None":
            self.ui.aniPath_label.setText(('{0}/{1}/Projects/{2}').format(self.projectSetting()['rootPath'], current_project, current_idea_en))
            if current_stage != "None":
                self.ui.aniPath_label.setText(('{0}/{1}/Projects/{2}/{3}').format(self.projectSetting()['rootPath'], current_project, current_idea_en, current_stage))
                if current_shot :
                    print(current_shot)
                    self.ui.aniPath_label.setText('{0}/{1}/Projects/{2}/{3}/{4}'.format(self.projectSetting()['rootPath'], current_project, current_idea_en,current_stage,current_shot))

    def getProject(self):
        '''
        得到Project列表，如果有txt则读取上次的Project设置
        '''
        self.ui.Project_ComboBox.addItems(self.projectSetting()['projects'])
        # if os.path.isfile(SYSTEMP  + 'Project.txt'):
        #     o = int(open(SYSTEMP  + 'Project.txt', 'r').read().split(':')[0])
        #     self.ui.Project_ComboBox.setCurrentIndex(o)

    def getStage(self):
        self.ui.stages_listWgt.addItems(self.projectSetting()['stages'])  # 设置阶段显示
        self.ui.stages_listWgt.setCurrentRow(0)

    def getShot(self):
        '''
        设置卡号显示
        '''
        RootPath, current_project, current_idea, current_idea_en, current_idea_ch, current_stage, current_shot, current_fbxfile = self._get_current_data()
        self.ui.ani_shot_listWgt.clear()
        shotPath = "{0}/{1}/Projects/{2}/{3}".format(RootPath,current_project,current_idea_en,current_stage)
        print(shotPath)
        if QtCore.QFileInfo(shotPath).exists():
            dir = QtCore.QDir(shotPath)
            for shot in dir.entryList(QtCore.QDir.NoDotAndDotDot ^ QtCore.QDir.AllEntries):
                item = QtWidgets.QListWidgetItem()
                item.setText(shot)
                self.ui.ani_shot_listWgt.addItem(item)

    def getFile(self):
        '''
        根据path 设置ma文件显示
        :return:
        '''
        file_path = str(self.ui.aniPath_label.text())
        self.ui.aniAST_listWgt.clear()
        folder_info = QtCore.QFileInfo(file_path)
        if folder_info.exists():
            fbx_list = os.listdir(file_path)
            for i in fbx_list:
                if i.endswith('.fbx'):
                    item = QtWidgets.QListWidgetItem()
                    item.setCheckState(QtCore.Qt.Checked)
                    item.setText(i)
                    item.setData(self.fbx_item_userRole, ('{0}/{1}').format(file_path, i))
                    self.ui.aniAST_listWgt.addItem(item)

    def getIdea(self):
        '''
        根据项目获得创意显示
        '''
        self.ui.ani_idea_listWgt.clear()
        current_project = self.get_current_project()
        idea_path = ('{0}/{1}/{2}').format(self.projectSetting()['rootPath'], current_project, 'projects')
        directory = QtCore.QDir(idea_path)
        directory.setNameFilters(['2019*', '2020*', '2021*', '2022*'])
        for dir in directory.entryList(QtCore.QDir.NoDotAndDotDot ^ QtCore.QDir.AllEntries):
            if dir.find('_') != -1:
                dir_item = QtWidgets.QListWidgetItem()
                dir_item.setText(dir.split('_', 1)[1])
                dir_item.setData(self.idea_item_userRole, dir)
                self.ui.ani_idea_listWgt.addItem(dir_item)

        self.ui.ani_idea_listWgt.setCurrentRow(0)
    
    def getIdea_TW(self):
        '''
        根据CGT和项目获得创意显示
        '''
        current_project = self.ui.Project_ComboBox.currentText()
        keyword = self.ui.ani_idea_line.text()
        TW_proj = self.projectSetting()['projectdiction'][current_project]
        t_eps_ids = t_tw.info.get_id(TW_proj, 'chuangyi', [])
        eps = t_tw.info.get(TW_proj, 'chuangyi', t_eps_ids, ['chuangyi.creatdate','chuangyi.entity','chuangyi.chname'])
        epslist = []
        for info in eps :
            aa = "{0}_{1}".format(info['chuangyi.creatdate'],info['chuangyi.entity'])+'   /   '+info['chuangyi.chname']
            epslist.append(aa)
        epslist.sort(reverse=True)
        self.ui.ani_idea_listWgt.clear()
        for i in epslist:
            if i.lower().find(keyword.lower()) != -1:
                item = QtWidgets.QListWidgetItem()
                item.setText(i)
                self.ui.ani_idea_listWgt.addItem(item)
        # RootPath,current_project,current_idea,current_idea_en,current_idea_ch,current_stage,current_shot,current_fbxfile = self._get_current_data()
        # #current_idea = self.get_current_idea()
        # IdeaPaths = RootPath + '/'+current_project + '/Projects/'
        # AA=self.TW_infoEN()
        # D=self.TW_info_dicENCN()
        # #ZZ=[]
        # if os.path.exists(IdeaPaths):
        #     self.ui.ani_idea_listWgt.clear()
        #     directory = QtCore.QDir(IdeaPaths)
        #     for i in directory.entryList(QtCore.QDir.NoDotAndDotDot ^ QtCore.QDir.AllEntries) :
        #         try:
        #             idea = i.split('_')[1]
        #             if idea in AA:
        #                 Z=i+'   /    '+D[idea]
        #                 item_data = {'idea_EN':i,'idea_CH':D[idea],'idea_ENCH':Z}
        #                 item = QtWidgets.QListWidgetItem()
        #                 item.setText(Z)
        #                 item.setData(QtCore.Qt.UserRole, item_data)
        #                 self.ui.ani_idea_listWgt.addItem(item)
        #             else:
        #                 Z=i
        #                 item_data = {'idea_EN':i,'idea_CH':None,'idea_ENCH':Z}
        #                 item = QtWidgets.QListWidgetItem()
        #                 item.setText(Z)
        #                 item.setData(QtCore.Qt.UserRole, item_data)
        #                 self.ui.ani_idea_listWgt.addItem(item)
        #             #ZZ.append(Z)
        #         except:
        #             pass
        # else:
        #     print (u'%s不存在！！！！！'%IdeaPaths)
        #     self.ui.ani_idea_listWgt.clear()
        # for z in ZZ:
            # item = QtWidgets.QListWidgetItem()
            # item.setText(z)
            # item.setData(QtCore.Qt.UserRole, item_data)
            # self.ui.ani_idea_listWgt.addItem(item)
    
    def TW_infoEN(self):
        '''
        得到创意英文名
        '''
        current_project = self.get_current_project()
        TW_proj = self.projectSetting()['projectdiction'][current_project]
        t_eps_ids = t_tw.info.get_id(TW_proj, 'chuangyi', [])
        TW_dictionInfo = t_tw.info.get(TW_proj,'chuangyi', t_eps_ids, ['chuangyi.entity','chuangyi.chname']) 
        AA=[]
        for info in TW_dictionInfo :
            A=info['chuangyi.entity']
            AA.append(A)
        return AA

    def TW_info_dicENCN(self):
        '''
        得到创意中英文对照字典
        '''
        current_project = self.get_current_project()
        TW_proj = self.projectSetting()['projectdiction'][current_project]
        t_eps_ids = t_tw.info.get_id(TW_proj, 'chuangyi', [])
        TW_dictionInfo = t_tw.info.get(TW_proj,'chuangyi', t_eps_ids, ['chuangyi.entity','chuangyi.chname']) 
        AA=[]
        D={}
        for info in TW_dictionInfo :
            A=info['chuangyi.entity']
            AA.append(A)
            B=info['chuangyi.chname']
            C={A:B}
            D.update(C)
        return D

    def changeProject(self):
        '''
        切换Project触发：1.设置路径；2.写入txt； 3.改变创意显示
        '''
        currentProjectIndex = str(self.ui.Project_ComboBox.currentIndex())
        currentProject = str(self.ui.Project_ComboBox.currentText())
        self.ui.aniPath_label.setText(
            ('{0}/{1}/{2}').format(self.projectSetting()['rootPath'], currentProject, 'Projects'))
        # f = open(SYSTEMP  + 'Project.txt', 'w')
        # f.write(currentProjectIndex+':'+currentProject)
        # f.close()
        self.getIdea_TW()
        self.getShot()

    def changeStage(self):
        '''
        切换阶段触发：更新卡号；更新path；清空文件名
        '''
        self.ui.ani_shot_listWgt.clear()
        RootPath, current_project, current_idea, current_idea_en, current_idea_ch, current_stage, current_shot, current_fbxfile = self._get_current_data()
        shot_path = ('{0}/{1}/{2}/{3}/{4}').format(self.projectSetting()['rootPath'], current_project, 'Projects',
                                                   current_idea_en, current_stage)
        self.ui.aniPath_label.setText(shot_path)
        directory = QtCore.QDir(shot_path)
        for dir in directory.entryList(QtCore.QDir.NoDotAndDotDot ^ QtCore.QDir.AllEntries):
            dir_item = QtWidgets.QListWidgetItem()
            dir_item.setText(dir)
            self.ui.ani_shot_listWgt.addItem(dir_item)
        self.ui.aniAST_listWgt.clear()

    def changeIdea(self):
        '''
        切换创意触发：得到卡号；设置Path
        '''
        self.ui.ani_shot_listWgt.clear()
        RootPath,current_project,current_idea,current_idea_en,current_idea_ch,current_stage,current_shot,current_fbxfile = self._get_current_data()
        if current_idea != "None":
            shot_path = ('{0}/{1}/Projects/{2}/ANI/AniFBX').format(RootPath, current_project, current_idea_en)
            self.ui.aniPath_label.setText(shot_path)
            directory = QtCore.QDir(shot_path)
            # prefix_scene = ('{0}_{1}_S').format(current_project, current_idea)
            for dir in directory.entryList(QtCore.QDir.NoDotAndDotDot ^ QtCore.QDir.AllEntries):
            # ani_file_path = ('{0}/{1}/{1}_ani.ma').format(shot_path, dir)
            # if dir.find(prefix_scene) != -1 and os.path.exists(ani_file_path):
                dir_item = QtWidgets.QListWidgetItem()
                dir_item.setText(dir)
                # dir_item.setData(self.scene_item_userRole, ani_file_path)
                self.ui.ani_shot_listWgt.addItem(dir_item)
        #self.ui.ani_shot_listWgt.setCurrentRow(0)
    
    def changeShot(self):
        '''
        切换卡号触发：更新path；更新fbx文件名
        '''
        self.ui.aniAST_listWgt.clear()
        RootPath,current_project,current_idea,current_idea_en,current_idea_ch,current_stage,current_shot,current_fbxfile = self._get_current_data()
        fbx_path = ('{0}/{1}/Projects/{2}/{3}/{4}').format(RootPath, current_project, current_idea_en,current_stage,current_shot)
        self.ui.aniPath_label.setText(fbx_path)
        self.getFile()
        # try:
            # ani_folder_path = QtCore.QFileInfo(item.data(self.scene_item_userRole)).path()
            # AniFBX_path = ani_folder_path.replace('/AniFile/', '/AniFBX/')
            # AniCamera_path = ani_folder_path.replace('/AniFile/', '/AniCamera/')
            # self.getFbx(AniFBX_path, item)
        # except:
            # pass

        #self.get_ani_path()
        
    def update_ani_name_example(self):
        current_project = self.get_current_project()
        current_idea = self.get_current_idea()
        current_shot = self.get_current_shot()
        ani_example_name = ('{0}_{1}_{2}_ani.ma').format(current_project, current_idea, current_shot)
        self.ui.ani_name_example_lable.setText(ani_example_name)

    # def idea_search(self):
        # '''
        # 搜索(findItems不起作用不知道为什么)
        # '''
        # text = str(self.ui.ani_idea_line.text())
        # print (text)
        # aa = self.ui.ani_idea_listWgt.count()
        # print (aa)
        # if text:
            # find_items = self.ui.ani_idea_listWgt.findItems('2021*', QtCore.Qt.MatchFixedString )
            # print (find_items)
            # for i in range(self.ui.ani_idea_listWgt.count()):
                # item = self.ui.ani_idea_listWgt.item(i)
                # item.setHidden(True)

            # for j in find_items:
                # j.setHidden(False)

        # else:
            # for i in range(self.ui.ani_idea_listWgt.count()):
                # item = self.ui.ani_idea_listWgt.item(i)
                # item.setHidden(False)
    def idea_search(self):
        '''
        搜索
        '''
        keyWords = str(self.ui.ani_idea_line.text())
        if keyWords:
            num = range(0,self.ui.ani_idea_listWgt.count())
            for n in num:
                allIdeaName = self.ui.ani_idea_listWgt.item(n).text()
                if re.search(keyWords, allIdeaName, re.IGNORECASE):
                    item = self.ui.ani_idea_listWgt.item(n)
                    item.setHidden(False)
                else:
                    item = self.ui.ani_idea_listWgt.item(n)
                    item.setHidden(True) 
        else:
            self.getIdea_TW()

    def get_ani_path(self):
        current_idea = self.get_current_idea()
        current_shot = self.get_current_shot()
        if current_idea is None or current_shot is None:
            animations_folder = '/Game/.../...'
        else:
            animations_folder = ('/Game/Projects/{0}/Animations/{1}').format(current_idea, current_shot)
        self.ui.aniPath_label.setText(animations_folder)
        return

    def get_selected_path(self):
        pass

    def OpenFolder(self):
        FilePath = self.ui.aniPath_label.text()
        os.startfile(FilePath)

    # def getFbx(self, path, item):
        # folder_info = QtCore.QFileInfo(path)
        # if folder_info.exists():
            # fbx_list = os.listdir(path)
            # for i in fbx_list:
                # if i.endswith('.fbx'):
                    # item = QtWidgets.QListWidgetItem()
                    # item.setCheckState(QtCore.Qt.Checked)
                    # item.setText(i)
                    # item.setData(self.fbx_item_userRole, ('{0}/{1}').format(path, i))
                    # self.ui.aniAST_listWgt.addItem(item)

    def importAnim(self):
        ''' 
        导入动画FBX
        '''
        m = self.ui.aniAST_listWgt.count()
        RootPath,current_project,current_idea,current_idea_en,current_idea_ch,current_stage,current_shot,current_fbxfile = self._get_current_data()
        animations_folder = ('/Game/Projects/{0}/Animations/{1}').format(current_idea_en, current_shot)
        reg = '([A-Za-z0-9]+_){3}_([A-Za-z0-9]+_){2}AST'
        assetName_list = self.get_asset_list(animations_folder) #得到animations_folder下的资产名单
        # print (assetName_list)

        '''导入动画FBX到骨架网格体'''
        NotFindSkeleton = []
        NotFindFBX = []
        for i in range(m):
            if self.ui.aniAST_listWgt.item(i).checkState() == QtCore.Qt.Checked:
                fbx_path = self.ui.aniAST_listWgt.item(i).data(self.fbx_item_userRole)
                itemText = self.ui.aniAST_listWgt.item(i).text()
                # print (itemText)
                assetNewName = ('{0}_{1}_{2}').format(current_idea_en, current_shot, itemText.split('__')[0])
                # print (assetNewName)
                if assetNewName in assetName_list:
                    continue
                elif fbx_path.find('AniFBX') != -1 and re.match(reg, itemText):
                    character_name = itemText.split('__')[1].split('_')[0]
                    # character_skeleton_path = ('/Game/Assets/Characters/{0}/Maya/{0}_Skeleton').format(character_name) # 旧的规范带maya
                    character_skeleton_path = ('/Game/Assets/Characters/{0}/{0}_Skeleton').format(character_name)
                    # prop_skeleton_path = ('/Game/Assets/Props/{0}/Maya/{0}_Skeleton').format(character_name)
                    prop_skeleton_path = ('/Game/Assets/Props/{0}/{0}_Skeleton').format(character_name)
                    if unreal.EditorAssetLibrary.does_asset_exist(character_skeleton_path):
                        self.importAniFBX(fbx_path, character_skeleton_path, animations_folder)
                    elif unreal.EditorAssetLibrary.does_asset_exist(prop_skeleton_path):
                        self.importAniFBX(fbx_path, prop_skeleton_path, animations_folder)
                    else:
                        NotFindSkeleton.append(character_name)
                else:
                    NotFindFBX.append(itemText)
                    character_name = itemText
        '''改名 FeliciaSexy_hi_rig__FeliciaSexy_FFA_AST_Anim 为 20210626_test_C3_FeliciaSexy_hi_rig'''
        self.renameAniFBX(animations_folder)
        if NotFindSkeleton:
            for name in NotFindSkeleton:
                unreal.log_warning(('Can not find {0} skeleton').format(name))
                msg = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, u"提示：", u"没有找到骨架:</h3>".format(name))
                msg.exec_()
        if NotFindFBX:
            for name in NotFindFBX:
                unreal.log_warning(('Please check {0} ').format(name))
                msg = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, u"提示：", u"<没有FBX:</h3>".format(name))
                msg.exec_()

        '''创建动画序列'''
        AF = assetFunctions.AssetFunctions()
        sequence_path = animations_folder
        # print(/Game/Projects/20210626_test/Animations/C3)
        '''如果 sequence_path 已经存在就删除'''
        if unreal.EditorAssetLibrary.does_asset_exist(asset_path=sequence_path):
            unreal.EditorAssetLibrary.delete_asset(sequence_path)
        '''创建资产'''
        AF.createGenericAsset(asset_path = sequence_path, unique_name = True, asset_class = unreal.LevelSequence, asset_factory = unreal.LevelSequenceFactoryNew()) #生成动画序列C1
        asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
        asset_list_new = asset_reg.get_assets_by_path(sequence_path)
        # 获取 sequence_path 下的资产注册信息
        # print ([{object_path: "/Game/Projects/20211105_ChuBingZhanShi/Animations/C1/20211105_ChuBingZhanShi_C1_MonikaHi_hi_rig.20211105_ChuBingZhanShi_C1_MonikaHi_hi_rig",
        #       package_name: "/Game/Projects/20211105_ChuBingZhanShi/Animations/C1/20211105_ChuBingZhanShi_C1_MonikaHi_hi_rig",
        #       package_path: "/Game/Projects/20211105_ChuBingZhanShi/Animations/C1",
        #       asset_name: "20211105_ChuBingZhanShi_C1_MonikaHi_hi_rig",
        #       asset_class: "AnimSequence"}])
        for asset in asset_list_new:
            if asset.asset_class == 'AnimSequence': # 如果资产类型是动画序列
                sequenceFunctions.addSkeletalAnimationTrack(sequence_path, asset.object_path) # 则把动作加入动画序列轨道
        '''建立 seq/Animations 文件夹，并把动画序列加入文件夹'''
        self.add_seq_folder(sequence_path)

        '''导入相机'''
        if self.ui.camImport_cBox.isChecked():
            ani_camera_folder = fbx_path.rsplit('/', 1)[0].replace('AniFBX', 'AniCamera')
            if os.path.exists(ani_camera_folder):
                for i in os.listdir(ani_camera_folder):
                    if i.endswith('.fbx'):
                        cameraFBX_path = '%s/%s' % (ani_camera_folder, i)
                        sequenceFunctions.addCamera(sequence_path, cameraFBX_path)

    def get_asset_list(self, animations_folder):
        '''
        得到'/Game/Projects/current_idea_en/Animations/current_shot'文件夹下的名单
        '''
        asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
        asset_list = asset_reg.get_assets_by_path(animations_folder)
        assetName_list = []
        for asset in asset_list:
            assetName_list.append(str(asset.object_path).split('.')[1])
        return assetName_list

    def add_seq_folder(self, sequence_path):
        '''
        在Sequencer添加文件夹
        '''
        # sequence_asset = unreal.LevelSequence.cast(unreal.load_asset(sequence_path)) # 旧的API,UE4.26.1
        sequence_asset = unreal.MovieSceneSequence.cast(unreal.load_asset(sequence_path))
        animation_folder = sequence_asset.add_root_folder_to_sequence('Animations')
        animation_folder.set_folder_color(unreal.Color(255, 250, 0, 255))
        spawn_list = sequence_asset.get_spawnables()
        for i in spawn_list:
            animation_folder.add_child_object_binding(i)

    def importAniFBX(self, animation_mesh_fbx, skeleton_path, animations_folder):
        '''
        导入动画到指定的骨架网格体
        '''
        AF = assetFunctions.AssetFunctions()
        asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
        asset_list_before = asset_reg.get_assets_by_path(animations_folder)#获取路径下的asset
        try:
            animation_mesh_task = AF.buildImportTask(animation_mesh_fbx, animations_folder, AF.buildAnimationImportOptions(skeleton_path)) #按骨骼路径创建导入
            AF.executeImportTasks([animation_mesh_task])
        except:
            unreal.log_warning(('Can not import {0}').format(animation_mesh_fbx))

        asset_list_after = asset_reg.get_assets_by_path(animations_folder)#再获取路径下的asset
        new_assets = list(set(asset_list_after) - set(asset_list_before))
        for asset in new_assets:
            if asset.asset_class == 'SkeletalMesh':
                unreal.EditorAssetLibrary.delete_asset(asset.object_path)  #如果多出的是骨架就删除
            print ('Deleted asset: ' + str(asset.object_path))
            if asset.asset_class == 'AnimSequence':
                anim = unreal.load_asset(asset.object_path)
                unreal.AnimationLibrary.set_is_root_motion_lock_forced(anim, True)
                print ('"Force Root Lock" enabled for: ' + str(asset.object_path))
                unreal.EditorAssetLibrary.save_asset(asset.object_path, only_if_is_dirty=False)

    def renameAniFBX(self, animations_folder):
        '''
        重命名animations_folder下的物体
        '''
        current_idea = self.get_current_idea()
        current_shot = self.get_current_shot()
        asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
        # print(<Object '/Script/AssetRegistry.Default__AssetRegistryImpl' (0x000002EEAD047580) Class 'AssetRegistryImpl'>)
        asset_list = asset_reg.get_assets_by_path(animations_folder)
        editorAssetLib = unreal.EditorAssetLibrary()
        for asset in asset_list:
            if asset.asset_class == 'AnimSequence':
                assetPathName = str(asset.object_path)
                # print(/Game/Projects/20210626_test/Animations/C3/FeliciaSexy_hi_rig__FeliciaSexy_FFA_AST_Anim.FeliciaSexy_hi_rig__FeliciaSexy_FFA_AST_Anim)
                folderNameList = assetPathName.split('/')
                if assetPathName.split('.')[1].find(('{0}_{1}_').format(current_idea, current_shot)) != -1:
                    continue
                else:
                    assetNewName = ('{0}_{1}_{2}').format(folderNameList[3], folderNameList[5], folderNameList[6].split('.')[0].split('__')[0])
                    # print(20210626_test_C3_FeliciaSexy_hi_rig)
                    targetPathName = ('{0}/{1}.{1}').format(assetPathName.rsplit('/', 1)[0], assetNewName)
                    # print(/Game/Projects/20210626_test/Animations/C3/20210626_test_C3_FeliciaSexy_hi_rig.20210626_test_C3_FeliciaSexy_hi_rig)
                    editorAssetLib.rename_asset(assetPathName, targetPathName)

    def deleteAniFBX(self, animations_folder):
        '''
        删除animations_folder下的物体
        '''
        asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
        asset_list = asset_reg.get_assets_by_path(animations_folder)
        editorAssetLib = unreal.EditorAssetLibrary()
        for asset in asset_list:
            editorAssetLib.delete_asset(asset.object_path)

    def createLevelSequence(self):
        pass

    def show_menu(self, point):
        '''
        右键菜单
        '''
        self.currentItem = self.ui.ani_shot_listWgt.itemAt(point)
        if self.currentItem is not None and self.currentItem.text() != '-- Custom --':
            pop = QtWidgets.QMenu(self.ui.ani_shot_listWgt)
            alembic_action = QtWidgets.QAction('Alembic', self)
            ani_action = QtWidgets.QAction('Ani', self)
            camera_action = QtWidgets.QAction('Camera', self)
            fbx_action = QtWidgets.QAction('FBX', self)
            playblast_action = QtWidgets.QAction('Playblast', self)
            pop.addAction(alembic_action)
            pop.addAction(ani_action)
            pop.addAction(camera_action)
            pop.addAction(fbx_action)
            pop.addAction(playblast_action)
            self.checkDir('AniAlembic', self.currentItem, alembic_action)
            self.checkDir('AniFile', self.currentItem, ani_action)
            self.checkDir('AniCamera', self.currentItem, camera_action)
            self.checkDir('AniFBX', self.currentItem, fbx_action)
            self.checkDir('AniPlayblast', self.currentItem, playblast_action)
            alembic_action.triggered.connect(partial(self.openDir, 'AniAlembic', self.currentItem))
            ani_action.triggered.connect(partial(self.openDir, 'AniFile', self.currentItem))
            camera_action.triggered.connect(partial(self.openDir, 'AniCamera', self.currentItem))
            fbx_action.triggered.connect(partial(self.openDir, 'AniFBX', self.currentItem))
            playblast_action.triggered.connect(partial(self.openDir, 'AniPlayblast', self.currentItem))
            pop.exec_(QtGui.QCursor.pos())
        return

    def openDir(self, type, item):
        ani_folder_path = QtCore.QFileInfo(item.data(self.scene_item_userRole)).path()
        folder_path = ani_folder_path.replace('/AniFile/', ('/{0}/').format(type))
        folder_info = QtCore.QFileInfo(folder_path)
        if folder_info.exists:
            QtGui.QDesktopServices.openUrl(folder_path)

    def checkDir(self, type, item, action):
        ani_folder_path = QtCore.QFileInfo(item.data(self.scene_item_userRole)).path()
        folder_path = ani_folder_path.replace('/AniFile/', ('/{0}/').format(type))
        folder_info = QtCore.QFileInfo(folder_path)
        if folder_info.exists():
            action.setEnabled(True)
        else:
            action.setEnabled(False)
        
        
app = None
if not QtWidgets.QApplication.instance():
    app = QtWidgets.QApplication(sys.argv)

def showWin():
    global win
    try:
        win.close()
    except:
        pass

    win = CGPipelineToolUEUI()
    win.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    # win.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint) #总在全部软件最前，总在UE最前未解决
    win.show()
    
    
    



