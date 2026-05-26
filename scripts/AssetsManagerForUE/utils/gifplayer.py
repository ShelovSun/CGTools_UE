# -*- coding: utf-8 -*-
# Created: 9/5/2021 by Sunxh<175702994@qq.com>

from PySide6 import QtWidgets, QtGui

class Player():
    def __init__(self):
        self.is_playing = False
        self.is_pause = False
        self.total_frame = 0
        self.cur_frame = 0
        self.movie = QtGui.QMovie()
        self.movie.setCacheMode(QtGui.QMovie.CacheAll)

    def qa(self):
        print("hahaha")

    def setPlayButtonState(self, Bttn):
        '''修改播放按钮的状态'''
        if self.is_playing:
            Bttn.setIcon(QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaStop))
            Bttn.setToolTip("停止播放")
            # self.popup_menu.setEnabled(False)
        else:
            Bttn.setIcon(QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
            Bttn.setToolTip("开始播放")
            # self.popup_menu.setEnabled(True)



    def play(self, speed,Bttn):
        '''播放按钮的槽函数'''
        if self.is_playing:
            self.movie.stop()  # 停止3
            self.movie.jumpToFrame(0)  # 回到第一帧
            self.is_playing = False
        else:
            self.movie.start()  #播放
            self.movie.setSpeed(speed)
            self.is_playing = True
        self.setPlayButtonState(Bttn)
        # self.setFrame()

    def toFrame(self):
        '''到设定的当前帧'''
        if self.is_playing:
            self.movie.stop()
            self.is_playing = False
            self.setPlayButtonState()
        self.movie.jumpToFrame(self.cur_frame)

    def firstFrame(self):
        '''到第一帧'''
        self.cur_frame = 0
        self.toFrame()

    def lastFrame(self):
        '''到最后一帧'''
        self.cur_frame = self.total_frame - 1
        self.toFrame()

    def prevFrame(self):
        '''到前一帧'''
        if self.cur_frame <= 0:
            self.cur_frame = self.total_frame - 1
        else:
            self.cur_frame = self.cur_frame - 1
        self.toFrame()

    def nextFrame(self):
        '''到后一帧'''
        if self.cur_frame >= self.total_frame - 1:
            self.cur_frame = 0
        else:
            self.cur_frame = self.cur_frame + 1
        self.toFrame()

    def setFrame(self):
        while self.is_playing :
            pass
            # lineEdit.setText(str(self.cur_frame) +'/'+ str(self.total_frame))