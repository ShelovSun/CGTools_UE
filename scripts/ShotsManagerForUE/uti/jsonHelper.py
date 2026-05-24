#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Created: 19/03/2021 by Sunxh<175702994@qq.com>

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
    f = open(filePath, 'r')
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