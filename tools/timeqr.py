import os
import time
import cv2

# OpenCV 内蔵 Qt が探すフォントディレクトリが存在しない場合、作成して警告を抑制
_cv2_qt_fonts = os.path.join(os.path.dirname(cv2.__file__), "qt", "fonts")
os.makedirs(_cv2_qt_fonts, exist_ok=True)
import numpy as np
from PIL import Image
import qrcode

FPS = 30.0
FRAME_PERIOD = 1.0 / FPS

QR_VERSION = 3
BOX_SIZE = 12
BORDER = 2

WINDOW_WIDTH = 800
WINDOW_HEIGHT = 600

def make_qr_pil(data: str):
    qr = qrcode.QRCode(
        version=QR_VERSION,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=BOX_SIZE,
        border=BORDER,
    )
    qr.add_data(data)
    qr.make(fit=False)
    img = qr.make_image(fill_color="black", back_color="white")
    return img

def pil_to_cv(img_pil: Image.Image):
    img_pil = img_pil.convert("RGB")
    arr = np.array(img_pil, dtype=np.uint8)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

def main():
    cv2.namedWindow("TimeQR", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("TimeQR", WINDOW_WIDTH, WINDOW_HEIGHT)

    start_perf = time.perf_counter()
    frame = 0
    next_t = start_perf

    scale = 2.5  # ここでスマホ画面くらいに調整

    while True:
        now_perf = time.perf_counter()
        if now_perf < next_t:
            time.sleep(next_t - now_perf)
            now_perf = time.perf_counter()

        unix_t = time.time()
        ms = int((unix_t - int(unix_t)) * 1000)

        payload = f"{unix_t:.3f},f={frame}"
        qr_pil = make_qr_pil(payload)
        qr_cv = pil_to_cv(qr_pil)

        h, w = qr_cv.shape[:2]
        qr_cv_big = cv2.resize(qr_cv, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_NEAREST)

        text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(unix_t)) + f".{ms:03d}  frame={frame}"
        cv2.putText(qr_cv_big, text, (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,0,255), 2, cv2.LINE_AA)

        cv2.imshow("TimeQR", qr_cv_big)

        # キーで終了（ESC）
        key = cv2.waitKey(1) & 0xFF
        if key == 27:
            break

        frame += 1
        next_t += FRAME_PERIOD


    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
