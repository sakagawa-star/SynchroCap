#!/usr/bin/env python3
import argparse, os, glob, csv
import cv2, toml, numpy as np

def parse_size_entry(val):
    w = int(round(float(val[0]))); h = int(round(float(val[1])))
    return w, h

def make_obj_points(cols, rows, square):
    obj = np.zeros((cols*rows, 3), np.float64)
    grid = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    obj[:, :2] = grid * square
    return obj

def load_intrinsics(toml_path, section):
    data = toml.load(toml_path)
    ent = data[section]
    K = np.array(ent["matrix"], dtype=np.float64)
    dist = np.array(ent["distortions"], dtype=np.float64).reshape(-1,1)
    w,h = parse_size_entry(ent["size"])
    return K, dist, (w,h)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intrinsics", required=True)
    ap.add_argument("--section", required=True)  # 例: int_cam03_img
    ap.add_argument("--pattern", required=True)  # "6,8"
    ap.add_argument("--square", required=True, type=float)
    ap.add_argument("--glob", required=True)     # 例: ./ext_cam03_img/*.png
    ap.add_argument("--fast-check", choices=["on","off"], default="on")
    ap.add_argument("--outdir", default="viz_out")
    args = ap.parse_args()

    cols, rows = [int(x) for x in args.pattern.split(",")]
    obj = make_obj_points(cols, rows, args.square)
    K, dist, expect = load_intrinsics(args.intrinsics, args.section)

    os.makedirs(args.outdir, exist_ok=True)
    flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
    if args.fast_check == "on":
        flags |= cv2.CALIB_CB_FAST_CHECK

    for imgp in sorted(glob.glob(args.glob)):
        im = cv2.imread(imgp)
        if im is None: continue
        h, w = im.shape[:2]
        if (w,h) != expect:
            print(f"skip size mismatch {imgp}: got {w}x{h}, expect {expect}")
            continue
        gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        found, corners = cv2.findChessboardCorners(gray, (cols,rows), flags)
        if not found:
            print(f"not found: {imgp}")
            continue
        # subpix
        corners = cv2.cornerSubPix(
            gray, corners, (11,11), (-1,-1),
            (cv2.TERM_CRITERIA_EPS+cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-3)
        )
        # PnP（iterative）
        ok, rvec, tvec = cv2.solvePnP(obj, corners, K, dist, flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok:
            print(f"solvePnP failed: {imgp}")
            continue
        proj, _ = cv2.projectPoints(obj, rvec, tvec, K, dist)

        # 可視化：検出コーナー（青）・再投影（赤）・誤差カラー線
        vis = im.copy()
        cv2.drawChessboardCorners(vis, (cols,rows), corners, True)
        diff = corners - proj
        err = np.sqrt(np.sum(diff**2, axis=2)).reshape(-1)
        for i, (p, q, e) in enumerate(zip(corners.reshape(-1,2), proj.reshape(-1,2), err)):
            u,v = map(int, np.round(p))
            uu,vv = map(int, np.round(q))
            cv2.circle(vis, (uu,vv), 3, (0,0,255), -1)       # 再投影 赤
            color = (0,255,0) if e < 1.0 else (0,165,255) if e < 2.0 else (0,0,255)
            cv2.line(vis, (u,v), (uu,vv), color, 1)
        # 数個のインデックスも描く（方位確認用）
        for j in [0, cols-1, cols*rows-1, (rows-1)*cols]:
            u,v = corners[j,0]
            cv2.putText(vis, str(j), (int(u)+3, int(v)-3), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,0,0), 1, cv2.LINE_AA)

        base = os.path.splitext(os.path.basename(imgp))[0]
        out_img = os.path.join(args.outdir, f"{args.section}_{base}_viz.png")
        cv2.imwrite(out_img, vis)

        # CSV（idx,u,v,proj_u,proj_v,err_px）
        out_csv = os.path.join(args.outdir, f"{args.section}_{base}_corners.csv")
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            wtr = csv.writer(f)
            wtr.writerow(["idx","u","v","proj_u","proj_v","err_px"])
            for i,(p,q,e) in enumerate(zip(corners.reshape(-1,2), proj.reshape(-1,2), err)):
                wtr.writerow([i, f"{p[0]:.6f}", f"{p[1]:.6f}", f"{q[0]:.6f}", f"{q[1]:.6f}", f"{e:.6f}"])
        print(f"wrote: {out_img} ; {out_csv} ; mean={err.mean():.4f} max={err.max():.4f}")

if __name__ == "__main__":
    main()

