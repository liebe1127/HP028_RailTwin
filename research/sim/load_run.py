"""실측 주행 CSV를 레일 좌표로 맞춰 읽는다.

- 멈춰 있던 구간은 버리고 움직인 구간만 쓴다.
- 이음부 틈(600, 1200 mm)에서 센서 값이 튀는 지점을 찾아, 그 두 점이 600 과 1200 에 오도록
  엔코더 위치를 선형으로 다시 맞춘다(논문 3.1 과 같은 방법). 좌·우 따로.
"""
import numpy as np
import pandas as pd

JOINTS = (600.0, 1200.0)


def find_spikes(pos, gap, win=25, thr=0.5):
    """위로 튀는 지점(틈)의 중심 위치 두 개를 돌려준다."""
    g = pd.Series(gap)
    med = g.rolling(win, center=True, min_periods=5).median()
    dev = (g - med).to_numpy()
    idx = np.where(dev > thr)[0]
    if len(idx) == 0:
        return []
    # 가까운 샘플끼리 묶기
    clusters, cur = [], [idx[0]]
    for i in idx[1:]:
        if pos[i] - pos[cur[-1]] < 40:
            cur.append(i)
        else:
            clusters.append(cur)
            cur = [i]
    clusters.append(cur)
    centers = []
    for c in clusters:
        c = np.array(c)
        w = dev[c]
        centers.append((float(np.average(pos[c], weights=w)), float(w.max()), len(c)))
    return centers


def load_run(path, side_cols=("left", "right")):
    d = pd.read_csv(path)
    t = pd.to_datetime(d["time"])
    d["t"] = (t - t.iloc[0]).dt.total_seconds()
    out = {}
    for s in side_cols:
        pos = d[f"{s}_position_mm"].to_numpy(float)
        gap = d[f"{s}_sensor_distance_mm"].to_numpy(float)
        # 움직인 구간: 위치가 최종 위치의 3% 를 넘어선 뒤부터
        moving = pos > 0.03 * pos.max()
        # 마지막에 센서가 레일 끝을 벗어나 0 으로 떨어지는 부분 제거
        valid = moving & (gap > 1.0)
        p, g, tt = pos[valid], gap[valid], d["t"].to_numpy()[valid]
        spikes = find_spikes(p, g)
        spikes = sorted(spikes, key=lambda c: -c[1])[:2]  # 가장 큰 두 개
        spikes = sorted(spikes)
        if len(spikes) == 2:
            c1, c2 = spikes[0][0], spikes[1][0]
            scale = (JOINTS[1] - JOINTS[0]) / (c2 - c1)
            x = JOINTS[0] + (p - c1) * scale
        else:
            scale, x = 1.0, p
        out[s] = dict(t=tt, pos=p, x=x, gap=g, spikes=spikes, scale=scale,
                      tilt=d[f"{s}_tilt_deg"].to_numpy(float)[valid],
                      roll=d[f"{s}_roll_deg"].to_numpy(float)[valid],
                      az=d[f"{s}_mpu_accel_z"].to_numpy(float)[valid])
    return out


if __name__ == "__main__":
    import sys
    r = load_run(sys.argv[1])
    for s, v in r.items():
        print(s, "spikes", [(round(c, 1), round(a, 2), n) for c, a, n in v["spikes"]],
              "scale", round(v["scale"], 4), "rail x range", round(v["x"].min()), round(v["x"].max()))
