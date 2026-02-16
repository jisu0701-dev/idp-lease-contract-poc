# -*- coding: utf-8 -*-
"""
이미지 내 PII(주민등록번호 뒷자리) 마스킹 — EasyOCR + OpenCV
로컬에서만 실행되며, 최초 실행 시 EasyOCR 모델 다운로드로 1~2분 소요될 수 있음.
"""

from typing import Optional

import cv2
import numpy as np
from PIL import Image as PILImage

# 로컬 OCR 엔진 (최초 import 시 또는 첫 사용 시 초기화)
_reader: Optional[object] = None


def _get_reader():
    """EasyOCR Reader 싱글톤 (한 번만 로드)."""
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(["ko", "en"], gpu=False)
    return _reader


def mask_pii_in_image(pil_img: PILImage.Image) -> PILImage.Image:
    """
    로컬에서 주민번호 뒷자리를 찾아 검은색으로 마스킹한 이미지를 반환한다.
    EasyOCR로 텍스트 영역을 추출한 뒤, 하이픈 뒤 6자리 이상 숫자 패턴 영역을 칠한다.
    """
    reader = _get_reader()
    open_cv_image = np.array(pil_img)
    img_bgr = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)

    results = reader.readtext(img_bgr)

    for (bbox, text, prob) in results:
        clean_text = text.replace(" ", "")
        if "-" in clean_text:
            after_hyphen = clean_text.split("-")[-1]
            if len(after_hyphen) >= 6:
                top_left = tuple(map(int, bbox[0]))
                bottom_right = tuple(map(int, bbox[2]))
                cv2.rectangle(img_bgr, top_left, bottom_right, (0, 0, 0), -1)

    return PILImage.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
