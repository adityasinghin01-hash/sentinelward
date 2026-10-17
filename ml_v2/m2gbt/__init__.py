"""M2 v2: is this bedside monitor alarm real? Features + portable gradient-boosted trees.

Written fresh on 17 Oct 2026 for SentinelWard (does not use ml/). Pure numpy/scipy at
inference so the same code runs on IBM LinuxONE (s390x, big-endian) and on a laptop.
"""
MODEL_VERSION = 'M2-gbt-2026-10-17'
FS = 125
WINDOW_S = 10
ALARM_TYPES = ('ASYSTOLE', 'BRADY', 'TACHY', 'VFIB', 'VTACH')
