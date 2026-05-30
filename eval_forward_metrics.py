# eval_forward_metrics.py
# 计算 E_target vs E_forward_pred 的 SSIM / RRMSD / foreground CV / foreground yjd
#
# 改进点：
# 1. 支持 --drop 删除异常样本，例如 shape_3__472178
# 2. 支持 --erode 做核心前景区域评价，避免图案边缘过渡像素掩盖主体效果
# 3. 支持 --norm_mode p99，用稳健归一化降低局部亮点/极值对指标的影响
# 4. 支持 --align_mode mean / lsq，对 RRMSD 计算进行前景亮度尺度对齐
# 5. 保留原有 minmax / none 模式，便于和旧结果对照

import argparse
import csv
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd


def safe_name(s: str) -> str:
    s = str(s)
    s = re.sub(r"[^\w\-\.]+", "_", s, flags=re.UNICODE)
    return s.strip("_")[:120] or "sample"


def normalize_array(x: np.ndarray, mode: str = "minmax", percentile: float = 99.0) -> np.ndarray:
    """
    指标归一化。

    minmax:
        旧版逻辑，减最小值后除以最大值。
        缺点是容易被单个局部亮点影响。

    p99:
        稳健归一化，减最小值后除以指定百分位数。
        更适合照度图中存在局部亮点/噪声尖峰的情况。
    """
    x = np.asarray(x, dtype=np.float32)
    x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)

    x = x - float(np.min(x))

    if mode == "minmax":
        denom = float(np.max(x)) + 1e-12
    elif mode == "p99":
        positive = x[x > 0]
        if positive.size > 0:
            denom = float(np.percentile(positive, percentile)) + 1e-12
        else:
            denom = float(np.max(x)) + 1e-12
    else:
        raise ValueError(f"Unknown norm_mode: {mode}")

    x = x / denom
    x = np.clip(x, 0.0, 1.0)
    return x.astype(np.float32)


def load_npy_or_mat(path: str, prefer_key: str = "") -> np.ndarray:
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(str(path))

    if path.suffix.lower() == ".npy":
        return np.load(path).astype(np.float32)

    if path.suffix.lower() == ".mat":
        try:
            from scipy.io import loadmat

            obj = loadmat(str(path))
            if prefer_key and prefer_key in obj:
                return np.asarray(obj[prefer_key]).astype(np.float32)

            for k, v in obj.items():
                if k.startswith("__"):
                    continue
                arr = np.asarray(v)
                if arr.ndim >= 2 and np.issubdtype(arr.dtype, np.number):
                    return np.squeeze(arr).astype(np.float32)

        except NotImplementedError:
            import h5py

            with h5py.File(str(path), "r") as f:
                if prefer_key and prefer_key in f:
                    arr = np.array(f[prefer_key])
                    return np.squeeze(arr).astype(np.float32).T

                for k in f.keys():
                    arr = np.array(f[k])
                    if arr.ndim >= 2:
                        return np.squeeze(arr).astype(np.float32).T

    raise ValueError(f"Unsupported file or no valid array found: {path}")


def ssim_global(x: np.ndarray, y: np.ndarray) -> float:
    """
    备用全局 SSIM。
    如果安装了 scikit-image，会优先使用 skimage 的 local SSIM。
    """
    x = x.astype(np.float64)
    y = y.astype(np.float64)

    c1 = 0.01 ** 2
    c2 = 0.03 ** 2

    mux = x.mean()
    muy = y.mean()
    vx = x.var()
    vy = y.var()
    cov = ((x - mux) * (y - muy)).mean()

    return float(
        ((2 * mux * muy + c1) * (2 * cov + c2))
        / ((mux ** 2 + muy ** 2 + c1) * (vx + vy + c2) + 1e-12)
    )


def calc_ssim_from_normed(t: np.ndarray, p: np.ndarray) -> float:
    """
    输入已经是归一化后的 t / p。
    """
    try:
        from skimage.metrics import structural_similarity

        h, w = t.shape[-2], t.shape[-1]
        win_size = 7
        if min(h, w) < 7:
            win_size = min(h, w)
            if win_size % 2 == 0:
                win_size -= 1
            win_size = max(win_size, 3)

        return float(structural_similarity(t, p, data_range=1.0, win_size=win_size))
    except Exception:
        return ssim_global(t, p)


def make_foreground_mask(t_norm: np.ndarray, fg_thr: float, erode: int = 0) -> np.ndarray:
    """
    根据目标图生成前景 mask。

    注意：
    如果目标图接近二值图，那么 fg_thr=0.1 和 fg_thr=0.3 选出的区域可能完全相同。
    这种情况下，要想评价主体区域，应使用 erode 做核心前景区域。
    """
    mask = t_norm > fg_thr * float(np.max(t_norm))

    if not np.any(mask):
        mask = t_norm > 0

    if erode > 0 and np.any(mask):
        try:
            from scipy.ndimage import binary_erosion

            old_mask = mask.copy()
            mask = binary_erosion(mask, iterations=erode)

            # 防止细线、笔画、logo 被腐蚀没
            if not np.any(mask):
                mask = old_mask
        except Exception:
            pass

    return mask


def align_prediction_to_target(
    t: np.ndarray,
    p: np.ndarray,
    mask: np.ndarray,
    align_mode: str = "none",
) -> tuple[np.ndarray, float]:
    """
    只用于 RRMSD/MAE 的亮度尺度对齐。

    none:
        不对齐，保持旧逻辑。

    mean:
        将预测前景均值对齐到目标前景均值。
        适合评价图案形状和相对亮度分布，而不是惩罚整体亮度尺度差异。

    lsq:
        最小二乘尺度对齐，使 scale * p 与 t 的平方误差最小。
    """
    if align_mode == "none":
        return p, 1.0

    t_fg = t[mask].astype(np.float64)
    p_fg = p[mask].astype(np.float64)

    if p_fg.size == 0:
        return p, 1.0

    if align_mode == "mean":
        scale = float(np.mean(t_fg) / (np.mean(p_fg) + 1e-12))
    elif align_mode == "lsq":
        scale = float(np.sum(t_fg * p_fg) / (np.sum(p_fg * p_fg) + 1e-12))
    else:
        raise ValueError(f"Unknown align_mode: {align_mode}")

    p_aligned = p.astype(np.float64) * scale
    p_aligned = np.clip(p_aligned, 0.0, 1.0).astype(np.float32)

    return p_aligned, scale


def calc_metrics(
    e_target: np.ndarray,
    e_pred: np.ndarray,
    fg_thr: float = 0.1,
    erode: int = 0,
    norm_mode: str = "minmax",
    norm_percentile: float = 99.0,
    align_mode: str = "none",
) -> dict:
    t = normalize_array(e_target, mode=norm_mode, percentile=norm_percentile)
    p = normalize_array(e_pred, mode=norm_mode, percentile=norm_percentile)

    mask = make_foreground_mask(t, fg_thr=fg_thr, erode=erode)
    bg_mask = ~mask

    ssim_v = calc_ssim_from_normed(t, p)

    if np.any(mask):
        t_fg = t[mask]
        p_fg = p[mask]

        p_for_error, scale = align_prediction_to_target(
            t=t,
            p=p,
            mask=mask,
            align_mode=align_mode,
        )
        p_err_fg = p_for_error[mask]

        rmse_fg = float(np.sqrt(np.mean((p_err_fg - t_fg) ** 2)))
        rrmsd_fg = rmse_fg / (float(np.mean(t_fg)) + 1e-12)

        mae_fg = float(np.mean(np.abs(p_err_fg - t_fg)))

        # CV 和 YJD 评价的是预测照度自身的前景波动，尺度缩放不影响 CV/YJD
        cv_fg = float(np.std(p_fg) / (np.mean(p_fg) + 1e-12))
        yjd_fg = float(np.min(p_fg) / (np.max(p_fg) + 1e-12))

        mean_pred_fg = float(np.mean(p_fg))
        mean_target_fg = float(np.mean(t_fg))
    else:
        scale = 1.0
        rmse_fg = np.nan
        rrmsd_fg = np.nan
        mae_fg = np.nan
        cv_fg = np.nan
        yjd_fg = np.nan
        mean_pred_fg = np.nan
        mean_target_fg = np.nan

    if np.any(bg_mask):
        bg_leak = float(np.sum(p[bg_mask]) / (np.sum(p) + 1e-12))
    else:
        bg_leak = 0.0

    return {
        "ssim": ssim_v,
        "rrmsd_fg_pct": rrmsd_fg * 100.0,
        "rmse_fg": rmse_fg,
        "mae_fg": mae_fg,
        "cv_fg_pct": cv_fg * 100.0,
        "yjd_fg": yjd_fg,
        "bg_leak_pct": bg_leak * 100.0,
        "mean_target_fg": mean_target_fg,
        "mean_pred_fg": mean_pred_fg,
        "align_scale": scale,
        "target_min": float(np.min(e_target)),
        "target_max": float(np.max(e_target)),
        "pred_min": float(np.min(e_pred)),
        "pred_max": float(np.max(e_pred)),
        "fg_pixels": int(np.sum(mask)),
    }


def read_forward_time(mat_path: Path) -> float:
    try:
        if mat_path.suffix.lower() != ".mat":
            return math.nan

        try:
            from scipy.io import loadmat

            obj = loadmat(str(mat_path))
            if "forward_time_s" in obj:
                return float(np.squeeze(obj["forward_time_s"]))
        except NotImplementedError:
            import h5py

            with h5py.File(str(mat_path), "r") as f:
                if "forward_time_s" in f:
                    return float(np.squeeze(np.array(f["forward_time_s"])))
    except Exception:
        pass

    return math.nan


def flatten_summary_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [
        "_".join([str(x) for x in col if str(x) != ""])
        if isinstance(col, tuple)
        else str(col)
        for col in df.columns
    ]
    return df


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument("--manifest", required=True)
    ap.add_argument("--forward_root", required=True)
    ap.add_argument("--out_csv", required=True)
    ap.add_argument("--ckpts", nargs="+", default=["best_val", "last"])

    ap.add_argument("--fg_thr", type=float, default=0.1)
    ap.add_argument(
        "--erode",
        type=int,
        default=0,
        help="前景 mask 腐蚀次数。0=全前景；1=核心前景，常用于减少边缘过渡影响。",
    )
    ap.add_argument(
        "--drop",
        nargs="*",
        default=[],
        help="跳过异常样本。可写 sample_folder/name/sample_id，例如 shape_3__472178。",
    )

    ap.add_argument(
        "--norm_mode",
        choices=["minmax", "p99"],
        default="minmax",
        help="指标归一化方式。minmax 为旧逻辑；p99 可降低局部亮点/极值影响。",
    )
    ap.add_argument(
        "--norm_percentile",
        type=float,
        default=99.0,
        help="当 norm_mode=p99 时使用的百分位数。",
    )
    ap.add_argument(
        "--align_mode",
        choices=["none", "mean", "lsq"],
        default="none",
        help="RRMSD/MAE 是否做前景亮度尺度对齐。none=旧逻辑；mean=前景均值对齐；lsq=最小二乘对齐。",
    )

    args = ap.parse_args()

    manifest = Path(args.manifest)
    forward_root = Path(args.forward_root)
    drop_set = set(args.drop or [])

    rows = []
    with open(manifest, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get("status", "") != "ok":
                continue
            if not r.get("eval_e_path", "").strip():
                continue
            rows.append(r)

    if not rows:
        raise RuntimeError("No valid rows found in manifest.")

    results = []

    for ckpt in args.ckpts:
        for r in rows:
            name = safe_name(r["name"])
            sid = safe_name(r["sample_id"])
            sample_folder = f"{name}__{sid}"

            if sample_folder in drop_set or name in drop_set or sid in drop_set:
                print(f"[drop] {ckpt:8s} {sample_folder}")
                continue

            e_target_path = Path(r["eval_e_path"])
            e_forward_mat = forward_root / ckpt / sample_folder / "E_forward_pred.mat"
            e_forward_npy = forward_root / ckpt / sample_folder / "E_forward_pred.npy"

            if e_forward_mat.exists():
                e_pred_path = e_forward_mat
                e_pred = load_npy_or_mat(str(e_forward_mat), prefer_key="E_forward_pred")
            elif e_forward_npy.exists():
                e_pred_path = e_forward_npy
                e_pred = load_npy_or_mat(str(e_forward_npy))
            else:
                print(f"[missing] {ckpt} {sample_folder}: no E_forward_pred.mat/.npy")
                continue

            e_target = load_npy_or_mat(str(e_target_path))

            e_target = np.squeeze(e_target)
            e_pred = np.squeeze(e_pred)

            if e_target.shape != e_pred.shape:
                raise ValueError(
                    f"shape mismatch: {sample_folder}, target={e_target.shape}, pred={e_pred.shape}"
                )

            m = calc_metrics(
                e_target=e_target,
                e_pred=e_pred,
                fg_thr=args.fg_thr,
                erode=args.erode,
                norm_mode=args.norm_mode,
                norm_percentile=args.norm_percentile,
                align_mode=args.align_mode,
            )

            forward_time_s = read_forward_time(e_forward_mat)

            item = {
                "ckpt": ckpt,
                "name": r.get("name", ""),
                "sample_id": r.get("sample_id", ""),
                "sample_folder": sample_folder,
                "category": r.get("category", r.get("name", "")),
                "eval_e_path": str(e_target_path),
                "e_forward_path": str(e_pred_path),
                "forward_time_s": forward_time_s,
                "fg_thr": args.fg_thr,
                "erode": args.erode,
                "norm_mode": args.norm_mode,
                "norm_percentile": args.norm_percentile,
                "align_mode": args.align_mode,
            }
            item.update(m)
            results.append(item)

            print(
                f"[ok] {ckpt:8s} {sample_folder:35s} "
                f"SSIM={m['ssim']:.4f} "
                f"RRMSD_fg={m['rrmsd_fg_pct']:.2f}% "
                f"CV_fg={m['cv_fg_pct']:.2f}% "
                f"YJD_fg={m['yjd_fg']:.4f} "
                f"fg={m['fg_pixels']}"
            )

    if not results:
        raise RuntimeError("No metrics computed.")

    df = pd.DataFrame(results)
    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    summary = df.groupby(["ckpt"]).agg(
        {
            "ssim": ["mean", "std"],
            "rrmsd_fg_pct": ["mean", "std"],
            "cv_fg_pct": ["mean", "std"],
            "yjd_fg": ["mean", "std"],
            "bg_leak_pct": ["mean", "std"],
            "forward_time_s": ["mean", "std"],
            "fg_pixels": ["mean", "std"],
        }
    )
    summary = flatten_summary_columns(summary.reset_index())

    summary_csv = out_csv.with_name(out_csv.stem + "_summary.csv")
    summary.to_csv(summary_csv, index=False, encoding="utf-8-sig")

    category_summary = df.groupby(["ckpt", "category"]).agg(
        {
            "sample_folder": "count",
            "ssim": "mean",
            "rrmsd_fg_pct": "mean",
            "cv_fg_pct": "mean",
            "yjd_fg": "mean",
            "fg_pixels": "mean",
        }
    )
    category_summary = category_summary.rename(columns={"sample_folder": "count"}).reset_index()

    category_summary_csv = out_csv.with_name(out_csv.stem + "_category_summary.csv")
    category_summary.to_csv(category_summary_csv, index=False, encoding="utf-8-sig")

    print(f"\n[done] metrics csv = {out_csv}")
    print(f"[done] summary csv = {summary_csv}")
    print(f"[done] category summary csv = {category_summary_csv}")

    print("\n[setting]")
    print(f"fg_thr          = {args.fg_thr}")
    print(f"erode           = {args.erode}")
    print(f"norm_mode       = {args.norm_mode}")
    print(f"norm_percentile = {args.norm_percentile}")
    print(f"align_mode      = {args.align_mode}")
    print(f"drop            = {args.drop}")


if __name__ == "__main__":
    main()