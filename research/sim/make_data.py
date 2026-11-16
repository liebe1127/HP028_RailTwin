"""실측 보정본 CSV 를 sim 코드가 읽는 이름(data/c{구성}_r{회차}.csv)으로 복사한다.

사용: python3 make_data.py "../../배준호_전달/레일측정데이터/보정"   (레포 루트 기준 경로)
구성 번호: 1 정상, 2 단차, 3 상하침하, 4 좌우 높이차. 회차는 파일 이름의 N차.
"""
import glob, os, re, shutil, sys, unicodedata

CFG = {"1. 정상": 1, "2. 단차": 2, "3. 상하침하": 3, "4. 좌우 높이차": 4}
src = sys.argv[1] if len(sys.argv) > 1 else os.path.join("..", "..", "배준호_전달", "레일측정데이터", "보정")
dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
os.makedirs(dst, exist_ok=True)
n = 0
for folder, cfg in CFG.items():
    for f in glob.glob(os.path.join(src, folder, "*.csv")):
        name = unicodedata.normalize("NFC", os.path.basename(f))
        m = re.search(r"(\d+)차", name)
        if not m:
            continue
        out = os.path.join(dst, f"c{cfg}_r{int(m.group(1))}.csv")
        shutil.copyfile(f, out); n += 1
print(f"{n}개 복사 → {os.path.abspath(dst)}")
