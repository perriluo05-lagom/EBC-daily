# -*- coding: utf-8 -*-
"""pytest 路径配置:使 tests 能 import 顶层 src/main。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
