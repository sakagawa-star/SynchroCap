import cv2
import numpy as np

# 仮のBayerGR8データを生成 (実際にはカメラから取得する)
# 1920x1080の1chデータ
height, width = 1080, 1920
bayer = np.random.randint(0, 256, (height, width), dtype=np.uint8)

# GPUにアップロード
gpu_mat = cv2.cuda_GpuMat()
gpu_mat.upload(bayer)

# GPUでBayerGR8 -> BGR変換
gpu_bgr = cv2.cuda.cvtColor(gpu_mat, cv2.COLOR_BayerGR2BGR)

# CPUに戻す
bgr_img = gpu_bgr.download()

# JPEGで保存
cv2.imwrite("test_frame.jpg", bgr_img, [cv2.IMWRITE_JPEG_QUALITY, 90])

print("done: test_frame.jpg saved")

