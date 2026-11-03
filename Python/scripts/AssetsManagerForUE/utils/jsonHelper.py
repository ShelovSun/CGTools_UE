#!/usr/bin/env python
# -*- coding: utf-8 -*-
# <jsonHelper> Created: 19/03/2021 by Sunxh<175702994@qq.com>
# log:

import json, shutil, os

def writeDictToFile(filePath, dataDict):
    result = False
    try:
        f = open(filePath, 'w')
        f.write(json.dumps(dataDict, ensure_ascii=False, indent=4))
        f.close()
        result = True
    except:
        result = False

    return result


def readDictFromFile(filePath):
    if not os.path.isfile(filePath):
        return
    f = open(filePath, 'rb')
    data = f.read()
    f.close()
    decode_json = {}
    try:
        decode_json = json.loads(data)
        return decode_json
    except:
        print ('read json data file error!')
        return

    return