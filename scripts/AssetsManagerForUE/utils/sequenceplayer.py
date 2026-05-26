# -*- coding: utf-8 -*-
# Created: 9/5/2021 by Sunxh<175702994@qq.com>

import os, re
from PySide6 import QtGui
from PySide6 import QtCore
from PySide6 import QtWidgets


class Player():

    def __init__(self):
        self.is_playing = True
        self.is_pause = False
        self.total_frame = 0
        self.cur_frame = 0
        self.movie = QtGui.QMovie()
        self.movie.setCacheMode(QtGui.QMovie.CacheAll)


    def setPlayButtonState(self, Bttn):
        '''修改播放按钮的状态'''
        if self.is_playing:
            Bttn.setIcon(QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaPause))
            Bttn.setToolTip("停止播放")
            # self.popup_menu.setEnabled(False)
        else:
            Bttn.setIcon(QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
            Bttn.setToolTip("开始播放")
            # self.popup_menu.setEnabled(True)

    def _play(self, Bttn, movie):
        if self.is_playing:
            movie.stop()
            self.is_playing = False
        else:
            movie.start()
            self.is_playing = True
        self.setPlayButtonState(Bttn)

    def play(self, speed, Bttn):
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


class ImageSequence(QtCore.QObject):
    DEFAULT_FPS = 30

    frameChanged = QtCore.Signal(int)

    def __init__(self, path, *args):
        QtCore.QObject.__init__(self, *args)

        self._fps = self.DEFAULT_FPS
        self._timer = None
        self._frame = 0
        self._frames = []
        self._dirname = None
        self._paused = False

        if path:
            self.setPath(path)

    def firstFrame(self):
        """
        Get the path to the first frame.
        :rtype: str
        """
        if self._frames:
            return self._frames[0]
        return ""

    def setPath(self, path):
        """
        Set a single frame or a directory to an image sequence.
        :type path: str
        """
        if os.path.isfile(path):
            self._frame = 0
            self._frames = [path]
        elif os.path.isdir(path):
            self.setDirname(path)

    def setDirname(self, dirname):
        """
        Set the location to the image sequence.
        :type dirname: str
        :rtype: None
        """

        def naturalSortItems(items):
            """
            Sort the given list in the way that humans expect.
            """
            convert = lambda text: int(text) if text.isdigit() else text
            alphanum_key = lambda key: [convert(c) for c in re.split('([0-9]+)', key)]
            items.sort(key=alphanum_key)

        self._dirname = dirname
        if os.path.isdir(dirname):
            self._frames = [dirname + "/" + filename for filename in os.listdir(dirname)]
            naturalSortItems(self._frames)

    def dirname(self):
        """
        Return the location to the image sequence.
        :rtype: str
        """
        return self._dirname

    def reset(self):
        """
        Stop and reset the current frame to 0.
        :rtype: None
        """
        if not self._timer:
            self._timer = QtCore.QTimer(self.parent())
            self._timer.setSingleShot(False)
            self._timer.timeout.connect(self._frameChanged)

        if not self._paused:
            self._frame = 0
        self._timer.stop()

    def pause(self):
        """
        ImageSequence will enter Paused state.
        :rtype: None
        """
        self._paused = True
        self._timer.stop()

    def resume(self):
        """
        ImageSequence will enter Playing state.
        :rtype: None
        """
        if self._paused:
            self._paused = False
            self._timer.start()

    def stop(self):
        """
        Stops the movie. ImageSequence enters NotRunning state.
        :rtype: None
        """
        self._timer.stop()

    def start(self):
        """
        Starts the movie. ImageSequence will enter Running state
        :rtype: None
        """
        self.reset()
        if self._timer:
            self._timer.start(1000.0 / self._fps)

    def frames(self):
        """
        Return all the filenames in the image sequence.
        :rtype: list[str]
        """
        return self._frames

    def _frameChanged(self):
        """
        Triggered when the current frame changes.
        :rtype: None
        """
        if not self._frames:
            return

        frame = self._frame
        frame += 1
        self.jumpToFrame(frame)

    def percent(self):
        """
        Return the current frame position as a percentage.
        :rtype: None
        """
        if len(self._frames) == self._frame + 1:
            _percent = 1
        else:
            _percent = float((len(self._frames) + self._frame)) / len(self._frames) - 1
        return _percent

    def frameCount(self):
        """
        Return the number of frames.
        :rtype: int
        """
        return len(self._frames)

    def currentIcon(self):
        """
        Returns the current frame as a QIcon.
        :rtype: QtGui.QIcon
        """
        return QtGui.QIcon(self.currentFilename())

    def currentPixmap(self):
        """
        Return the current frame as a QPixmap.
        :rtype: QtGui.QPixmap
        """
        return QtGui.QPixmap(self.currentFilename())

    def currentFilename(self):
        """
        Return the current file name.
        :rtype: str or None
        """
        try:
            return self._frames[self.currentFrameNumber()]
        except IndexError:
            pass

    def currentFrameNumber(self):
        """
        Return the current frame.
        :rtype: int or None
        """
        return self._frame

    def jumpToFrame(self, frame):
        """
        Set the current frame.
        :rtype: int or None
        """
        if frame >= self.frameCount():
            frame = 0
        self._frame = frame
        self.frameChanged.emit(frame)