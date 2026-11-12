# -*- coding: utf-8 -*-
"""natfrp 九宫格本地识别器（MobileNet 余弦相似度匹配，零 API key）"""
import os
from io import BytesIO

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image

_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models", "mobilenet.onnx")
_SESSION = None
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _get_session():
    global _SESSION
    if _SESSION is None:
        model_path = os.environ.get("MOBILENET_PATH", _MODEL_PATH)
        _SESSION = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    return _SESSION


def _get_vector(img_rgb):
    img = cv2.resize(img_rgb, (224, 224))
    x = img.astype(np.float32) / 255.0
    x = (x - MEAN) / STD
    x = np.transpose(x, (2, 0, 1))[None, ...].astype(np.float32)
    out = _get_session().run(None, {_get_session().get_inputs()[0].name: x})[0][0]
    e = np.exp(out - out.max())
    return e / e.sum()


def _cosine(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def solve_nine_grid(image_bytes: bytes) -> list:
    """
    解析 GeeTest v3 九宫格验证码（本地 MobileNet 分类 + 余弦相似度匹配）

    Args:
        image_bytes: 九宫格验证码完整图片的字节数据

    Returns:
        点击坐标列表，格式如 ["1_2", "2_1", "2_3"]（1-based col_row）
    """
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解码九宫格图片")
    h, w = img.shape[:2]

    # 九宫格占上方约 83%，底部约 17% 是目标图标区
    grid_h = int(h * 0.83)
    cw = w // 3
    ch = grid_h // 3

    # 裁目标图标（底部左侧第一个格子宽度区域）
    icon_rgb = cv2.cvtColor(img[grid_h:h, 0:cw], cv2.COLOR_BGR2RGB)
    icon_vec = _get_vector(icon_rgb)

    # 计算 9 个格子与目标图标的余弦相似度
    scores = []
    for r in range(3):
        for c in range(3):
            cell = img[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw]
            cell_rgb = cv2.cvtColor(cell, cv2.COLOR_BGR2RGB)
            cell_vec = _get_vector(cell_rgb)
            sim = _cosine(icon_vec, cell_vec)
            scores.append((r + 1, c + 1, sim))

    # 按相似度降序排列，找最大间隔确定选择数量
    scores.sort(key=lambda x: -x[2])
    sims = [s[2] for s in scores]

    # 找最大间隔位置
    best_gap_idx = 0
    best_gap = 0
    for i in range(len(sims) - 1):
        gap = sims[i] - sims[i + 1]
        if gap > best_gap:
            best_gap = gap
            best_gap_idx = i

    select_count = best_gap_idx + 1
    if select_count < 1:
        select_count = 1

    # 取前 select_count 个格子
    selected = scores[:select_count]
    points = [f"{c}_{r}" for r, c, _ in selected]

    import logging
    logging.getLogger(__name__).info(
        f"九宫格识别: 选中 {select_count}/{9} 格 {points}, "
        f"相似度 {[round(s[2], 4) for s in selected]}"
    )
    return points
