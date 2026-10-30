#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Start ShotsManager through its native UE progress launcher."""

import os
import sys


scripts_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if scripts_root not in sys.path:
    sys.path.insert(0, scripts_root)

from ShotsManagerForUE.launcher import showWin

showWin()
