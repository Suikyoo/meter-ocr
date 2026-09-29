"""Constants and preprocessing shared by training and firmware.

Anything changed here must be mirrored in firmware/main/reader.cc.
"""
import numpy as np
import cv2

CLASSES = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "blank", "unsure"]
BLANK = CLASSES.index("blank")
UNSURE = CLASSES.index("unsure")

IMG_W = 20
IMG_H = 32

# Minimum contrast range used by the stretch. Stops a blank digit (only
# background and faint ghost segments) from being stretched into a fake "8".
MIN_RANGE = 80


def normalize(crop: np.ndarray) -> np.ndarray:
    """Resize a grayscale crop to IMG_W x IMG_H and contrast-stretch it to uint8."""
    img = cv2.resize(crop, (IMG_W, IMG_H), interpolation=cv2.INTER_AREA)
    lo = int(img.min())
    rng = max(int(img.max()) - lo, MIN_RANGE)
    out = (img.astype(np.int32) - lo) * 255 // rng
    return np.clip(out, 0, 255).astype(np.uint8)
