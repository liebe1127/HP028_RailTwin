#!/usr/bin/env python3
"""디지털 트윈·Unity 멘토 보고 PDF.

2026-09-22 대화 브리핑을 인쇄용으로 옮긴다. 사실 관계는 그 브리핑과 같게 유지한다.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "2026-09-22_디지털트윈_Unity_멘토보고.pdf"
FONT = "/System/Library/Fonts/Supplemental/AppleGothic.ttf"

pdfmetrics.registerFont(TTFont("Kr", FONT))
pdfmetrics.registerFont(TTFont("Kr-Med", FONT))
pdfmetrics.registerFont(TTFont("Kr-Bold", FONT))
pdfmetrics.registerFontFamily("Kr", normal="Kr", bold="Kr-Bold", italic="Kr", boldItalic="Kr-Bold")

NAVY = HexColor("#0B3A5B")
TEAL = HexColor("#1A6B7A")
INK = HexColor("#1C2430")
MUTED = HexColor("#5B6573")
LINE = HexColor("#D5DDE6")
PALE = HexColor("#F4F7FA")
PALE_TEAL = HexColor("#E7F3F5")
PALE_GOLD = HexColor("#F8F1E3")
GOLD = HexColor("#8A5A12")
PAGE_W, PAGE_H = A4


def S(name, **kw):
    base = dict(fontName="Kr", textColor=INK, alignment=TA_LEFT)
    base.update(kw)
    return ParagraphStyle(name, **base)


STY = {
    "kicker": S("kicker", fontName="Kr-Med", fontSize=8.5, leading=12, textColor=TEAL),
    "title": S("title", fontName="Kr-Bold", fontSize=16, leading=22, textColor=NAVY, spaceAfter=2),
    "sub": S("sub", fontSize=9, leading=13.5, textColor=MUTED, spaceAfter=8),
    "lead": S("lead", fontSize=10, leading=16, spaceAfter=8),
    "h": S("h", fontName="Kr-Bold", fontSize=12, leading=16, textColor=NAVY, spaceBefore=8, spaceAfter=4),
    "body": S("body", fontSize=9.2, leading=14.4, spaceAfter=6),
    "note": S("note", fontSize=8.3, leading=12.6, textColor=GOLD, spaceBefore=1, spaceAfter=6),
    "th": S("th", fontName="Kr-Bold", fontSize=7.6, leading=10.4, textColor=white, alignment=TA_CENTER),
    "td": S("td", fontSize=7.5, leading=10.6),
    "tdc": S("tdc", fontName="Kr-Med", fontSize=7.5, leading=10.6, alignment=TA_CENTER),
    "q": S("q", fontName="Kr-Bold", fontSize=9.2, leading=13.5, textColor=NAVY, spaceBefore=2, spaceAfter=2),
    "choice": S("choice", fontSize=8.6, leading=12.8, leftIndent=8, spaceAfter=1),
    "foot": S("foot", fontSize=8, leading=11, textColor=MUTED),
    "sum": S("sum", fontSize=9.4, leading=15, spaceAfter=0),
}


def P(text, style="body"):
    return Paragraph(text, STY[style])


def bullets(items):
    return ListFlowable(
        [ListItem(Paragraph(item, STY["body"]), leftIndent=10, bulletColor=TEAL) for item in items],
        bulletType="bullet",
        start="•",
        leftIndent=12,
        bulletFontName="Kr",
        bulletFontSize=8,
        spaceBefore=0,
        spaceAfter=4,
    )


def status_table():
    header = [
        P("영역", "th"),
        P("상태", "th"),
        P("구현된 것", "th"),
        P("아직 아닌 것", "th"),
    ]
    rows_raw = [
        (
            "Unity 씬",
            "구현·미검증",
            "Unity 6000.6.0f1 프로젝트. 큐브 세그먼트로 레일 두 줄과 흰 마커를 코드로 생성. ApplyState가 색과 마커를 갱신.",
            "에디터 Play와 대시보드에서 40–50cm가 노랑·빨강으로 바뀌었다는 확인 기록은 없음.",
        ),
        (
            "WebGL 삽입",
            "구현·미검증",
            "대시보드가 SendMessage로 x, 좌 l[], 우 r[]를 전달. 산출물 frontend/unity/Build/는 2026-09-16 로컬 파일.",
            "build/ gitignore라 산출물은 저장소에 없음. Unity 원본 폴더도 아직 커밋 전. 브라우저 상태 문구가 Unity WebGL인지 확인 필요.",
        ),
        (
            "화면이 받는 값",
            "구현·미검증",
            "서버가 distance_x, rail_risk, defects(구간 from_mm/to_mm, defect_type은 null, 근거는 간격 편차·롤)를 보냄. 규칙 단위 테스트는 이 계약을 검사.",
            "Unity는 구간 배열과 x만 읽고, 구간 길이·결함 구간·mm/deg는 3D에 그리지 않음.",
        ),
        (
            "좌표 정합",
            "미실시",
            "시연 길이는 100cm, 20구간(한 칸 5cm). 마커는 x/100으로 길이 1.0 씬 위에 올림.",
            "문서상 모형 계획 약 1.4m, 바퀴 지름 5.3cm와 씬이 연결되지 않음. 엔코더 교정 전.",
        ),
        (
            "기하 변형",
            "계획",
            "색만 바뀜. 레일 메시의 높이·기울기는 센서값으로 움직이지 않음.",
            "간격 mm·롤 deg를 형상으로 보여주는 단계는 착수 전.",
        ),
        (
            "실물 → 트윈",
            "미실시",
            "2026-08-23 사용자 확인: 센서 배선, 펌웨어 동작, 구동부 출력, 전체 모형 조립.",
            "반복 주행과 실측 저장은 안 함. 화면에 칠해지는 이상은 더미의 40–50cm.",
        ),
        (
            "Godot",
            "이력",
            "godot/rail_twin_websocket.gd가 남아 있음.",
            "2026-09-16 이후 현재 화면 작업이 아님.",
        ),
        (
            "상용 크레인 모델",
            "범위 밖",
            "디지털 시각화용으로 구매해 둠.",
            "현재 씬에 넣지 않음. 라이선스 때문에 공개 저장소에 올리지 않음.",
        ),
    ]
    data = [header]
    for area, state, done, pending in rows_raw:
        data.append([P(area, "td"), P(state, "tdc"), P(done, "td"), P(pending, "td")])

    col = [26 * mm, 24 * mm, 64 * mm, 64 * mm]
    table = Table(data, colWidths=col, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Kr-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("GRID", (0, 0), (-1, -1), 0.3, LINE),
        ("BACKGROUND", (0, 1), (-1, -1), white),
    ]
    tint = {
        "구현·미검증": PALE_GOLD,
        "미실시": PALE,
        "계획": PALE_TEAL,
        "이력": HexColor("#EEF0F3"),
        "범위 밖": HexColor("#F6F1EA"),
    }
    for i, row in enumerate(rows_raw, start=1):
        style_cmds.append(("BACKGROUND", (1, i), (1, i), tint[row[1]]))
    table.setStyle(TableStyle(style_cmds))
    return table


def decision(n, title, lines):
    block = [P(f"{n}. {title}", "q")]
    block.extend(P(line, "choice") for line in lines)
    block.append(Spacer(1, 3))
    return KeepTogether(block)


def draw_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, PAGE_H - 12 * mm, PAGE_W, 12 * mm, fill=1, stroke=0)
    canvas.setFillColor(white)
    canvas.setFont("Kr", 8)
    canvas.drawString(16 * mm, PAGE_H - 7.6 * mm, "RailTwin  ·  하부 주행 레일 디지털 트윈")
    canvas.setFont("Kr", 8)
    canvas.drawRightString(PAGE_W - 16 * mm, PAGE_H - 7.6 * mm, "멘토 피드백용  ·  2026-09-22")
    canvas.setFillColor(TEAL)
    canvas.rect(0, 0, PAGE_W, 8 * mm, fill=1, stroke=0)
    canvas.setFillColor(white)
    canvas.setFont("Kr", 8)
    canvas.drawString(16 * mm, 3.1 * mm, "2차 평가 제출일 2026-09-30  ·  로컬 문서·코드 기준")
    canvas.drawRightString(PAGE_W - 16 * mm, 3.1 * mm, f"{doc.page}")
    canvas.restoreState()


def build():
    doc = BaseDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=18 * mm,
        bottomMargin=14 * mm,
        title="디지털 트윈·Unity 현황 보고",
        author="RailTwin",
    )
    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="body",
        showBoundary=0,
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=draw_page)])

    story = [
        P("디지털 트윈  ·  Unity", "kicker"),
        P("현황 보고", "title"),
        P("멘토 피드백용  ·  기준일 2026-09-22  ·  스마트해운물류 RailTwin", "sub"),
        HRFlowable(width="100%", thickness=0.6, color=LINE, spaceAfter=8),
        P(
            "대형 갠트리 크레인 <b>하부 주행 레일</b>의 이상 구간을 주행 위치와 함께 보여주는 디지털 트윈이고, "
            "3D는 지금 <b>레일 두 줄의 상태 색과 위치 마커</b>까지 와 있습니다. "
            "실물 주행이 그 화면에 붙는 단계는 아직입니다. "
            "Notion은 인증이 안 되어 로컬 문서와 코드를 근거로 했습니다."
        ),
        P(
            "개발보고서 초안의 Godot·RBF 서술은 2026-08-23 기준입니다. "
            "멘토님께는 2026-09-16 이후 범위를 현재 계획으로 말씀드리면 됩니다.",
            "note",
        ),
        P("1. 최종 지향 목표", "h"),
        P(
            "좌·우 ESP32-C3 Mini(MPU-6050, ADS1115, GTRIC LR18-08U, 엔코더)가 간격·기울기·위치를 MQTT로 보내고, "
            "FastAPI가 간격 기준선과 롤로 이상 구간을 규칙 판정한 뒤, WebSocket으로 웹 대시보드와 "
            "<b>Unity WebGL</b>에 같은 좌표를 그립니다."
        ),
        P(
            "3D에 들어가는 것은 레일 두 줄과 주행 위치 마커입니다. "
            "구간 색은 정상에서 이상으로 갈수록 파랑–초록–노랑–빨강입니다. "
            "결함 종류 이름(단차·침하·뒤틀림)은 보류이고, 1차 결과는 <b>어느 구간인지</b>입니다. "
            "크레인 본체 메시는 현재 화면 범위가 아닙니다. "
            "구매한 상용 크레인 모델은 라이선스 때문에 공개 저장소에 올리지 않습니다."
        ),
        P("완성 기준은 반복 주행 → 실측 저장 → 그 위치가 트윈 마커·색과 맞는 종단 연동입니다."),
        P("2. 현재 구현된 상황", "h"),
        P(
            "2026-08-23 팀 자체 판단의 “Godot 디지털 트윈 70%”는 당시 Godot 트랙 숫자입니다. "
            "지금 Unity 씬의 진척도로 쓰지 않습니다. Unity 쪽은 퍼센트를 새로 매기지 않고 상태만 적습니다."
        ),
        status_table(),
        Spacer(1, 6),
        P(
            "더미 스트리머는 약 1m 레일을 1cm씩 진행하고, 40–50cm에서 간격과 롤이 같이 어긋나게 만듭니다. "
            "임계는 시연 기본값으로 간격 편차 0.25mm, 롤 편차 2.5°이고, <b>둘 다</b> 넘을 때만 그 구간의 rail_risk가 올라갑니다. "
            "값은 구간마다 최대치로 메모리에 쌓입니다. 이 색은 합성 시연이지 실측 성능이 아닙니다."
        ),
        P(
            "좌측 노드가 끊기면 우측 페이로드를 좌측에 복사하는 옵션이 기본으로 켜져 있습니다"
            "(MIRROR_RIGHT_TO_LEFT, 기본 true). 한쪽 보드로 화면을 채우는 시연용입니다."
        ),
        KeepTogether([
            P("3. 목표 대비 남은 과제", "h"),
            P(
                "막히는 지점은 트윈이 <b>더미 좌표의 색</b>까지이고, 조립된 모형의 엔코더 위치가 아직 그 마커가 아니라는 점입니다. "
                "실물 계측이 없으면 3D를 더 그려도 내용은 더미에 남습니다."
            ),
        ]),
        bullets([
            "<b>지금 확인할 것.</b> 더미로 대시보드를 한 바퀴 돌려, 상태 문구가 Unity WebGL인지, 마커가 움직이고 40–50cm가 노랑·빨강인지 캡처합니다. 문구가 브라우저 레일 뷰이면 9월 16일 빌드가 없거나 스크립트와 어긋난 것입니다.",
            "<b>좌표를 한곳으로.</b> Unity와 화면의 100, 20, x/100을 서버의 rail_length_cm, segment_count로 바꿉니다. 길이를 나중에 실물 값으로 바꿔도 씬을 다시 짜지 않게 됩니다.",
            "<b>원본 보관.</b> Unity 프로젝트는 Library를 빼고 저장소에 올려 재빌드가 되게 합니다. 산출물만 맥에 있으면 다른 PC에서 씬을 고칠 수 없습니다.",
            "<b>실물이 붙은 뒤.</b> 엔코더 영점·회전당 펄스, 좌·우 동시 수신, 반복 주행 한 회를 저장하고 그 위치가 마커와 맞는지 봅니다.",
            "<b>증빙.</b> 운영 주소 접속 성공은 문서와 별개입니다. 멘토 시연은 로컬 더미로 범위를 말하는 것이 안전합니다.",
        ]),
        KeepTogether([
            P("4. 지금 개발 착수할 사항", "h"),
            P(
                "멘토 피드백 전에 손대도 되는 것은 앞의 확인, 좌표, 원본 보관입니다. "
            "형상 변형, 크레인 메시, 단차/침하/뒤틀림 라벨, 주행 재생은 아래 결정 뒤에 착수하는 것이 맞습니다. "
                "결정 없이 메시를 움직이기 시작하면 9월 30일 전에 상태 화면과 기하 화면이 둘 다 중간에 남습니다."
            ),
        ]),
        P("5. 의사결정할 사항", "h"),
        P("멘토님께 현재 안을 먼저 말하고, 아래 일곱 가지에서 고쳐야 할 것만 받아 오시면 됩니다."),
        decision(
            "1",
            "트윈 수준",
            [
                "현재 안은 상태 트윈입니다. 구간 색과 주행 마커만 있습니다.",
                "기하 트윈으로 올리면 세그먼트를 간격 편차만큼 내리고 롤만큼 기울입니다.",
                "설비 트윈은 구매한 크레인 모델까지 포함하며, 라이선스와 일정상 9월 30일 범위 밖입니다.",
            ],
        ),
        decision(
            "2",
            "기준 길이",
            [
                "평가까지 100cm·20구간을 고정할지, 조립 모형의 실측 길이로 바로 바꿀지.",
                "약 1.4m는 계획값이고 확정 길이는 확인 필요합니다.",
            ],
        ),
        decision(
            "3",
            "색의 의미",
            [
                "지금 색은 규칙 점수 0–1의 누적 최대값입니다.",
                "화면에 mm와 deg를 숫자로 같이 둘지는 별도 선택입니다.",
            ],
        ),
        decision(
            "4",
            "좌측 복제",
            [
                "멘토 시연에서 우측 복사 옵션을 끌지.",
                "끄면 연결 안 된 쪽은 빈 레일로 보입니다.",
            ],
        ),
        decision(
            "5",
            "시간 축",
            [
                "실시간 한 장면만 할지, 한 번 주행을 재생·정지할지는 Influx 저장이 된 뒤의 일입니다.",
                "9월 30일 전에는 실시간만 현실적입니다.",
            ],
        ),
        decision(
            "6",
            "결함 이름",
            [
                "화면은 위치만 표시하는 현재 결정을 유지할지.",
                "종류를 3D에서 나누려면 규칙만으로는 부족하고, 정상·단차·침하·뒤틀림을 모형에서 재현한 라벨이 선행입니다.",
            ],
        ),
        decision(
            "7",
            "크레인 메시",
            [
                "레일만 유지할지, 비공개 프로젝트에서만 구매 모델을 보여줄지.",
            ],
        ),
        KeepTogether([
            P("6. 한 줄 요약", "h"),
            P(
                "데이터 계약과 Unity 레일 뷰의 뼈대는 더미로 연결되어 있고, "
                "2차 평가에서 채워야 하는 것은 그 색이 실물 위치와 같다는 증빙입니다. "
                "멘토님 피드백으로 바꿀 축은 형상까지 움직일지, 색과 마커로 둘지입니다.",
                "sum",
            ),
        ]),
    ]
    doc.build(story)
    print(OUT)


if __name__ == "__main__":
    build()
