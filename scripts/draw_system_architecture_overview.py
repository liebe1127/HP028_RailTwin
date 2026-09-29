#!/usr/bin/env python3
"""크림색 4칸 시스템 아키텍처 구성도.

이미지 생성 모델이 아니라 Pillow로 글자를 찍는다.
한글이 깨지지 않게 문구는 이 파일의 문자열만 고치고 다시 실행한다.

  python3 scripts/draw_system_architecture_overview.py

출력: docs/archive/previous-roadmaps/system-architecture-overview-0927.png
디자인 원본(삭제 금지): docs/archive/previous-roadmaps/system-architecture-overview.png
개정 문구: 0927 결함 감지 집중 수정본
폰트: /System/Library/Fonts/AppleSDGothicNeo.ttc (Regular 0, Medium 2, SemiBold 4, Bold 6)

어두운 4단계 로드맵 포스터(docs/development-roadmap.jpg)는 이 스크립트 대상이 아니다.
그 그림은 Gemini 프롬프트 docs/gemini-prompt-4phase-roadmap.md 로 만든다.

대차 실물 사진: docs/hardware-digital-twin/photos/assembled/
파일별 설명은 docs/hardware-digital-twin/README.md.
01 전진(빨간 기판), 02·03 좌우 GY-521, 04 LR18과 아연 각파이프,
05 모터 전지 2셀(바퀴가 안 도는 상태), 06 흰 롤러, 07 각파이프 두 줄 위의 대차.
1칸의 알루미늄 프로파일 대차와 바닥 아연 각파이프는 이 사진을 기준으로 한다.
"""

from PIL import Image, ImageDraw, ImageFont

OUT = "/Users/junho2026/Developer/해운물류0717(최신)/docs/archive/previous-roadmaps/system-architecture-overview-0927.png"
FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"

W = 3000
BG = (255, 255, 255)
NAVY = (22, 50, 79)
CREAM = (243, 237, 224)
CARD = (247, 248, 250)
CARD_LINE = (213, 219, 227)
GREEN = (231, 240, 234)
GREEN_LINE = (176, 196, 180)
BLUE = (238, 243, 248)
BLUE_LINE = (186, 202, 216)
SAND = (248, 239, 230)
SAND_LINE = (214, 196, 168)
INK = (26, 26, 26)
MUTED = (90, 101, 115)
FOOT = (239, 242, 245)
WHITE = (255, 255, 255)


def font(size, weight="regular"):
    index = {"regular": 0, "medium": 2, "semibold": 4, "bold": 6}[weight]
    return ImageFont.truetype(FONT, size, index=index)


def wrap(draw, text, face, max_w):
    lines = []
    for para in text.split("\n"):
        if para == "":
            lines.append("")
            continue
        cur = ""
        for ch in para:
            trial = cur + ch
            if draw.textlength(trial, font=face) <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
    return lines


def text(draw, xy, s, face, fill=INK, anchor="lt"):
    draw.text(xy, s, font=face, fill=fill, anchor=anchor)


def panel(draw, box, title, title_face):
    x, y, w, h = box
    draw.rounded_rectangle((x, y, x + w, y + h), radius=22, fill=CREAM, outline=CARD_LINE, width=2)
    draw.rounded_rectangle((x, y, x + w, y + 72), radius=22, fill=NAVY)
    draw.rectangle((x, y + 36, x + w, y + 72), fill=NAVY)
    text(draw, (x + w / 2, y + 36), title, title_face, WHITE, "mm")


def card_height(title_face, body_face, n_lines):
    body_h = 0 if n_lines == 0 else n_lines * (body_face.size + 9) - 9
    return 18 + title_face.size + 12 + body_h + 20


def card(draw, box, fill, outline, title, lines, title_face, body_face):
    x, y, w, h = box
    draw.rounded_rectangle((x, y, x + w, y + h), radius=14, fill=fill, outline=outline, width=2)
    text(draw, (x + 22, y + 16), title, title_face, NAVY)
    yy = y + 18 + title_face.size + 12
    for line in lines:
        text(draw, (x + 22, yy), line, body_face, INK)
        yy += body_face.size + 9


def main():
    title_f = font(52, "bold")
    sub_f = font(24, "medium")
    badge_f = font(26, "bold")
    head_f = font(28, "bold")
    card_title = font(23, "bold")
    body = font(20, "regular")
    foot_f = font(22, "medium")
    foot_s = font(18, "regular")
    arrow_f = font(15, "bold")

    margin, gap, top, footer_h = 44, 46, 156, 128
    pad, vgap = 16, 14
    header_h = 88
    weights = (0.23, 0.22, 0.31, 0.24)
    inner_w = W - margin * 2 - gap * 3
    widths = [int(inner_w * part) for part in weights]
    widths[-1] = inner_w - sum(widths[:-1])
    xs = [margin]
    for width in widths[:-1]:
        xs.append(xs[-1] + width + gap)

    probe = ImageDraw.Draw(Image.new("RGB", (W, 20), BG))

    def lines_for(width, raw):
        return wrap(probe, raw, body, width - pad * 2 - 44)

    columns = [
        [
            ("축소 주행 모형", CARD, CARD_LINE,
             "알루미늄 프로파일 대차\n바닥의 아연 각파이프 두 줄\n대상   이음부 단차 · 수직 변형 · 좌우 높이차"),
            ("ESP32-S3 1장", CARD, CARD_LINE,
             "좌·우를 한 보드의 I2C 두 버스로 읽는다\nMCU   ESP32-S3-DevKitC-1 N16R8\n간격  LR18-08U 좌·우, 0–10V\nADC   ADS1115, 20k/10k 분압 후 입력\n충격  MPU-6050 세로 가속도\n기울기  가속도의 중력 방향\n위치  JGB37-520 내장 엔코더\n구동  L298N · 18650"),
            ("엣지에서 바로 하는 일", CARD, CARD_LINE,
             "결함 판정은 하지 않는다\n주행 중에만 센서 배치를 보낸다\n정지 중 간격은 평균으로 누른다\n세로 충격이 크면 즉시 정지\n끊기면 브로커가 LWT offline"),
        ],
        [
            ("Mosquitto  MQTT 브로커", GREEN, GREEN_LINE,
             "QoS 1\n업링크   …/telemetry · …/status\n하행     …/command   {motion}\n토픽     rail/v1/nodes/{id}/…"),
            ("전송 경로  Wi-Fi", BLUE, BLUE_LINE,
             "한 장이 left · right 두 장치로 발행\nFastAPI 구독   railtwin-backend\nDocker Compose   포트 1883"),
            ("시연 대체 경로", BLUE, BLUE_LINE,
             "DEMO_MODE=true\n더미 스트리머가 같은 Queue로 넣는다\n20–25cm  이음부 단차\n45–70cm  수직 변형\n80–90cm  좌우 높이차\n화면에는 시뮬레이션이라고 표시"),
        ],
        [
            ("1. 스키마 검증", BLUE, BLUE_LINE,
             "schema v1 sensor_batch.  left / right 로 나눈다"),
            ("2. asyncio Queue · Consumer", BLUE, BLUE_LINE,
             "수신 순서대로 꺼낸다. 중복 batch_seq 는 버린다"),
            ("3. 좌·우 짝 · 50mm 구간", BLUE, BLUE_LINE,
             "같은 시각의 양쪽을 맞춰 구간 특징으로 만든다"),
            ("4. 특징 여섯 개", BLUE, BLUE_LINE,
             "m = (좌+우)/2\nΔ = 좌-우. 결함 없는 구간 영점을 뺀다\ndm/dx,  dΔ/dx\napeak 세로 가속도 최댓값,  tilt_deg"),
            ("5. 네 분류 규칙", BLUE, BLUE_LINE,
             "이음부 단차   apeak 큼, dm/dx 큼\n수직 변형   m 변화 큼, apeak 작음, Δ 작음\n좌우 높이차   |Δ| 큼, tilt와 부호가 같음\n해당 없으면 정상"),
            ("6. 단계와 동작", BLUE, BLUE_LINE,
             "한계선 50% 이하   ok · 평속\n50% ~ 한계선   caution · 해당 구간 감속\n한계선 초과   danger · 진입 전 정지"),
            ("출력 계약    WebSocket /ws", SAND, SAND_LINE,
             "defects[]     종류 · 단계 · 구간\nrail_risk     좌·우 구간 색\nmotion        cruise / slow / stop"),
        ],
        [
            ("InfluxDB", GREEN, GREEN_LINE,
             "시계열 저장. 토큰이 없으면 쓰기를 쉰다\n버킷   crane_data\n간격 · 여섯 특징 · 판정 결과"),
            ("웹 대시보드", CARD, CARD_LINE,
             "frontend/index.html\n주소   /dashboard\n정상 초록 · 주의 노랑 · 위험 빨강\nWebSocket /ws 구독"),
            ("Unity WebGL  레일", CARD, CARD_LINE,
             "레일만 표시. 크레인 메시는 없다\n같은 좌표의 구간 색과 현재 위치\n정상 초록 · 주의 노랑 · 위험 빨강\nWebSocket /ws"),
        ],
    ]

    prepared = []
    for width, blocks in zip(widths, columns):
        drawn = []
        for title, fill, outline, raw in blocks:
            lines = lines_for(width, raw)
            drawn.append((title, fill, outline, lines, card_height(card_title, body, len(lines))))
        prepared.append(drawn)

    content_h = max(sum(item[4] for item in col) + vgap * (len(col) - 1) for col in prepared)
    col_h = header_h + content_h + 18
    H = top + col_h + footer_h

    im = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(im)

    text(draw, (W / 2, 52), "RailTwin 전체 시스템 아키텍처 구성도", title_f, NAVY, "mm")
    text(
        draw,
        (W / 2, 108),
        "하부 주행 레일 이상 구간   |   간격·충격·기울기·위치  →  50mm 구간 규칙 판정  →  웹 · Unity 레일",
        sub_f,
        MUTED,
        "mm",
    )
    badge = "0927 결함 감지 집중 수정본"
    bw = draw.textlength(badge, font=badge_f) + 40
    bx, by = W - 56 - bw, 24
    draw.rounded_rectangle((bx, by, bx + bw, by + 50), radius=12, fill=NAVY)
    text(draw, (bx + bw / 2, by + 25), badge, badge_f, WHITE, "mm")

    titles = (
        "1. 물리 · 엣지 계측",
        "2. 전송",
        "3. 서버 처리 (FastAPI)",
        "4. 저장 · 시각화",
    )
    for x, width, title in zip(xs, widths, titles):
        panel(draw, (x, top, width, col_h), title, head_f)

    for x, width, blocks in zip(xs, widths, prepared):
        slack = content_h - (sum(item[4] for item in blocks) + vgap * (len(blocks) - 1))
        extra = slack // len(blocks)
        y = top + header_h
        for index, (title, fill, outline, lines, height) in enumerate(blocks):
            grow = extra + (slack % len(blocks) if index == len(blocks) - 1 else 0)
            card(draw, (x + pad, y, width - pad * 2, height + grow), fill, outline, title, lines, card_title, body)
            y += height + grow + vgap

    mid = top + col_h * 0.42
    labels = ("발행", "구독", "전달")
    for i, label in enumerate(labels):
        left = xs[i] + widths[i]
        right = xs[i + 1]
        cx = (left + right) / 2
        draw.line((left + 8, mid, right - 16, mid), fill=NAVY, width=3)
        draw.polygon([(right - 6, mid), (right - 16, mid - 7), (right - 16, mid + 7)], fill=NAVY)
        tw = draw.textlength(label, font=arrow_f)
        draw.rounded_rectangle((cx - tw / 2 - 8, mid - 28, cx + tw / 2 + 8, mid - 6), radius=6, fill=BG)
        text(draw, (cx, mid - 17), label, arrow_f, NAVY, "mm")

    fy = top + col_h + 18
    draw.rounded_rectangle((margin, fy, W - margin, H - 22), radius=14, fill=FOOT, outline=CARD_LINE, width=2)
    text(
        draw,
        (W / 2, fy + 32),
        "데이터 흐름    ESP32-S3 1장  →  MQTT QoS 1  →  FastAPI 규칙 판정  →  InfluxDB + WebSocket  →  웹 대시보드 · Unity WebGL",
        foot_f,
        NAVY,
        "mm",
    )
    text(
        draw,
        (W / 2, fy + 74),
        "0927 결함 감지 집중 수정본.   웨이블릿 · 파고율 · RBF · Godot 는 쓰지 않는다.   시연 더미는 시뮬레이션이며 정확도로 쓰지 않는다.",
        foot_s,
        MUTED,
        "mm",
    )

    im.save(OUT, "PNG")
    print(OUT, im.size)


if __name__ == "__main__":
    main()
