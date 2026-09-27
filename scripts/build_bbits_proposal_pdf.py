#!/usr/bin/env python3
"""부산공유대학 다학제 융합 프로젝트 활동 계획서 PDF 생성."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    FrameBreak,
    Image,
    KeepTogether,
    CondPageBreak,
    ListFlowable,
    ListItem,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PHOTOS = DOCS / "hardware-photos"
OUT = DOCS / "2026_부산공유대학_다학제융합_활동계획서.pdf"

pdfmetrics.registerFont(TTFont("Kr", "/System/Library/Fonts/Supplemental/AppleGothic.ttf"))
pdfmetrics.registerFont(TTFont("Kr-Bold", "/System/Library/Fonts/Supplemental/AppleGothic.ttf"))
pdfmetrics.registerFont(TTFont("KrSerif", "/System/Library/Fonts/Supplemental/AppleMyungjo.ttf"))
pdfmetrics.registerFontFamily("Kr", normal="Kr", bold="Kr-Bold", italic="Kr", boldItalic="Kr-Bold")

NAVY = HexColor("#0B3A5B")
TEAL = HexColor("#1A7A8C")
GOLD = HexColor("#C4A35A")
INK = HexColor("#1C2430")
MUTED = HexColor("#5B6573")
LINE = HexColor("#D5DDE6")
PALE = HexColor("#F3F7FA")
PALE_TEAL = HexColor("#E7F3F5")
PALE_GOLD = HexColor("#F8F1E3")
WARN = HexColor("#8A4B12")
DONE = HexColor("#1F6B4A")
PLAN = HexColor("#1A5F8A")
MID = HexColor("#9A6B12")


def C(r, g, b):
    return Color(r / 255, g / 255, b / 255)


def styles():
    base = getSampleStyleSheet()
    s = {
        "cover_kicker": ParagraphStyle(
            "cover_kicker", fontName="Kr", fontSize=9, leading=13, textColor=GOLD,
            alignment=TA_CENTER, tracking=1,
        ),
        "cover_prog": ParagraphStyle(
            "cover_prog", fontName="Kr", fontSize=11, leading=16, textColor=white,
            alignment=TA_CENTER,
        ),
        "cover_kind": ParagraphStyle(
            "cover_kind", fontName="KrSerif", fontSize=26, leading=34, textColor=white,
            alignment=TA_CENTER,
        ),
        "cover_title": ParagraphStyle(
            "cover_title", fontName="KrSerif", fontSize=16, leading=24, textColor=NAVY,
            alignment=TA_CENTER,
        ),
        "cover_en": ParagraphStyle(
            "cover_en", fontName="Kr", fontSize=9, leading=13, textColor=MUTED,
            alignment=TA_CENTER,
        ),
        "cover_meta": ParagraphStyle(
            "cover_meta", fontName="Kr", fontSize=10, leading=16, textColor=INK,
            alignment=TA_LEFT,
        ),
        "h1": ParagraphStyle(
            "h1", fontName="Kr", fontSize=13.5, leading=20, textColor=NAVY,
            spaceBefore=4, spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "h2", fontName="Kr", fontSize=11, leading=16, textColor=TEAL,
            spaceBefore=8, spaceAfter=5, keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "body", fontName="Kr", fontSize=9.4, leading=15.2, textColor=INK,
            alignment=TA_LEFT, spaceAfter=6,
        ),
        "body_left": ParagraphStyle(
            "body_left", fontName="Kr", fontSize=9.4, leading=15.2, textColor=INK,
            alignment=TA_LEFT, spaceAfter=6,
        ),
        "note": ParagraphStyle(
            "note", fontName="Kr", fontSize=8.4, leading=13, textColor=WARN,
            alignment=TA_LEFT, spaceBefore=2, spaceAfter=8,
        ),
        "caption": ParagraphStyle(
            "caption", fontName="Kr", fontSize=8, leading=12, textColor=MUTED,
            alignment=TA_CENTER, spaceBefore=3, spaceAfter=10,
        ),
        "cell": ParagraphStyle(
            "cell", fontName="Kr", fontSize=8.2, leading=12.2, textColor=INK,
            alignment=TA_LEFT,
        ),
        "cell_c": ParagraphStyle(
            "cell_c", fontName="Kr", fontSize=8.2, leading=12.2, textColor=INK,
            alignment=TA_CENTER,
        ),
        "th": ParagraphStyle(
            "th", fontName="Kr", fontSize=8.2, leading=12, textColor=white,
            alignment=TA_CENTER,
        ),
        "footer": ParagraphStyle(
            "footer", fontName="Kr", fontSize=7.5, leading=10, textColor=MUTED,
            alignment=TA_CENTER,
        ),
        "header": ParagraphStyle(
            "header", fontName="Kr", fontSize=8, leading=11, textColor=NAVY,
        ),
        "bullet": ParagraphStyle(
            "bullet", fontName="Kr", fontSize=9.3, leading=14.8, textColor=INK,
            leftIndent=2, spaceAfter=2,
        ),
        "callout": ParagraphStyle(
            "callout", fontName="Kr", fontSize=9.2, leading=14.6, textColor=NAVY,
            alignment=TA_LEFT,
        ),
        "small": ParagraphStyle(
            "small", fontName="Kr", fontSize=8, leading=12, textColor=MUTED,
            alignment=TA_LEFT, spaceAfter=4,
        ),
    }
    return s


S = styles()


def P(text, style="body"):
    return Paragraph(text, S[style])


def bullets(items):
    flow = []
    for item in items:
        flow.append(
            ListItem(P(item, "bullet"), leftIndent=12, bulletColor=TEAL, value="•")
        )
    return ListFlowable(flow, bulletType="bullet", start="•", leftIndent=14, bulletFontName="Kr", bulletFontSize=9)


def section_title(num, title):
    bar = Table(
        [[P(f"{num}  {title}", "h1")]],
        colWidths=[174 * mm],
    )
    bar.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBEFORE", (0, 0), (0, 0), 3.2, GOLD),
            ]
        )
    )
    return KeepTogether([bar, Spacer(1, 6)])


def callout_box(text, bg=PALE_TEAL):
    t = Table([[P(text, "callout")]], colWidths=[174 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("BOX", (0, 0), (-1, -1), 0.4, TEAL),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return t


def styled_table(headers, rows, col_widths, header_bg=NAVY):
    data = [[P(h, "th") for h in headers]]
    for row in rows:
        cells = []
        for i, val in enumerate(row):
            style = "cell_c" if i == 0 or (len(row) > 3 and i == len(row) - 1 and len(str(val)) < 18) else "cell"
            if i == 0:
                style = "cell_c" if len(headers) >= 4 else "cell"
            cells.append(P(val, "cell" if i != 0 else "cell"))
        data.append(cells)
    t = Table(data, colWidths=col_widths, repeatRows=1)
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("BACKGROUND", (0, 1), (-1, -1), white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), PALE))
    t.setStyle(TableStyle(cmds))
    return t


def photo_row(paths, captions, width=33.5 * mm, height=28 * mm):
    imgs = []
    caps = []
    for path, cap in zip(paths, captions):
        img = Image(str(path), width=width, height=height, kind="proportional")
        imgs.append(img)
        caps.append(P(cap, "caption"))
    n = len(paths)
    gap = 2 * mm
    col_w = (174 * mm - gap * (n - 1)) / n
    t1 = Table([imgs], colWidths=[col_w] * n)
    t1.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 1),
                ("RIGHTPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )
    t2 = Table([caps], colWidths=[col_w] * n)
    t2.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return KeepTogether([t1, t2])


def fig(path, caption, width=174 * mm, height=62 * mm):
    img = Image(str(path), width=width, height=height, kind="proportional")
    t = Table([[img]], colWidths=[174 * mm])
    t.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("BOX", (0, 0), (-1, -1), 0.3, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return KeepTogether([t, P(caption, "caption")])


def gantt_table():
    months = ["9월", "10월", "11월", "12월", "1월", "2월"]
    rows_raw = [
        ("실물 교정·전압/거리 검증", "■", "■", "", "", "", ""),
        ("반복 주행·라벨 수집", "□", "■", "■", "□", "", ""),
        ("실측 재학습·정량 평가", "", "□", "■", "■", "□", ""),
        ("시제품 수납·배선 고도화", "", "□", "■", "■", "□", ""),
        ("웹·Godot 종단 시연 고정", "□", "□", "■", "■", "■", ""),
        ("기업 멘토링 반영", "■", "■", "■", "■", "■", "□"),
        ("특강·아이디어 구체화", "■", "■", "■", "□", "", ""),
        ("경진대회 발표·시연", "", "", "", "□", "■", "■"),
    ]
    header = [P("추진 항목", "th")] + [P(m, "th") for m in months]
    data = [header]
    for item, *marks in rows_raw:
        row = [P(item, "cell")]
        for m in marks:
            row.append(P(m if m else "", "cell_c"))
        data.append(row)
    widths = [58 * mm] + [19.3 * mm] * 6
    t = Table(data, colWidths=widths, repeatRows=1)
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, 1), (0, -1), PALE),
    ]
    fill = {
        "■": TEAL,
        "□": PALE_GOLD,
    }
    for r, row in enumerate(rows_raw, start=1):
        for c, mark in enumerate(row[1:], start=1):
            if mark in fill:
                cmds.append(("BACKGROUND", (c, r), (c, r), fill[mark]))
                cmds.append(("TEXTCOLOR", (c, r), (c, r), white if mark == "■" else WARN))
    t.setStyle(TableStyle(cmds))
    legend = P("■ 중점 수행 &nbsp;&nbsp; □ 보조·마무리 &nbsp;&nbsp; 공란은 해당 월 비집중 구간", "small")
    return KeepTogether([t, Spacer(1, 3), legend])


def header_footer(canvas, doc):
    canvas.saveState()
    w, h = A4
    if doc.page > 1:
        canvas.setFillColor(NAVY)
        canvas.rect(0, h - 12 * mm, w, 12 * mm, fill=1, stroke=0)
        canvas.setFillColor(GOLD)
        canvas.rect(0, h - 12.7 * mm, w, 1.4, fill=1, stroke=0)
        canvas.setFillColor(white)
        canvas.setFont("Kr", 8)
        canvas.drawString(18 * mm, h - 8.2 * mm, "RailTwin 활동 계획서")
        canvas.drawRightString(w - 18 * mm, h - 8.2 * mm, "제2회 2026 기업 연계 부산공유대학 다학제 융합 프로젝트")
        canvas.setFillColor(PALE)
        canvas.rect(0, 0, w, 12 * mm, fill=1, stroke=0)
        canvas.setFillColor(GOLD)
        canvas.rect(0, 12 * mm, w, 0.8, fill=1, stroke=0)
        canvas.setFillColor(MUTED)
        canvas.setFont("Kr", 7.5)
        canvas.drawString(18 * mm, 5.2 * mm, "자유 형식 활동 계획서  ·  인적사항은 지정 서식 참가신청서에 기재")
        canvas.drawRightString(w - 18 * mm, 5.2 * mm, f"- {doc.page} -")
    canvas.restoreState()


def cover_page(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setFillColor(NAVY)
    canvas.rect(0, h - 78 * mm, w, 78 * mm, fill=1, stroke=0)
    canvas.setFillColor(GOLD)
    canvas.rect(0, h - 79.4 * mm, w, 2.2, fill=1, stroke=0)
    canvas.setFillColor(TEAL)
    canvas.rect(0, 0, w, 22 * mm, fill=1, stroke=0)
    canvas.setFillColor(GOLD)
    canvas.rect(0, 22 * mm, w, 1.6, fill=1, stroke=0)
    canvas.setFillColor(white)
    canvas.setFont("Kr", 8)
    canvas.drawCentredString(w / 2, 10 * mm, "제출: ccs614@pusan.ac.kr  ·  문의 051-510-7231  ·  작성일 2026. 9. 4.")
    canvas.restoreState()


def cover_flow():
    meta = [
        [P("<b>작품명</b>", "cover_meta"), P("HP028 RailTwin (레일트윈)", "cover_meta")],
        [P("<b>활동 기간</b>", "cover_meta"), P("2026. 9. ~ 2027. 2. (프로그램 공고 기준)", "cover_meta")],
        [P("<b>팀 구성</b>", "cover_meta"), P("4명 사전 구성 · 기계 / 임베디드 / 백엔드·AI / 디지털트윈", "cover_meta")],
        [P("<b>관련 산업</b>", "cover_meta"), P("항만 갠트리 크레인 하부 주행 레일 안전관리 (부산 신항 참조)", "cover_meta")],
        [P("<b>현재 단계</b>", "cover_meta"), P("축소 모형·센서·서버·화면 파이프라인 구축 완료, 실측·재학습 착수 단계", "cover_meta")],
        [P("<b>제출 구분</b>", "cover_meta"), P("활동 계획서 (자유 형식)  ·  참가신청서는 지정 서식 별도", "cover_meta")],
    ]
    mt = Table(meta, colWidths=[32 * mm, 118 * mm])
    mt.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LINEBELOW", (0, 0), (-1, -2), 0.3, LINE),
                ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                ("BACKGROUND", (0, 0), (0, -1), PALE_GOLD),
            ]
        )
    )

    story = [
        Spacer(1, 8 * mm),
        P("BUSAN SHARED UNIVERSITY", "cover_kicker"),
        Spacer(1, 4 * mm),
        P("제2회 2026학년도 기업 연계", "cover_prog"),
        P("부산공유대학 다학제 융합 프로젝트", "cover_prog"),
        Spacer(1, 5 * mm),
        P("활 동 계 획 서", "cover_kind"),
        FrameBreak(),
        Spacer(1, 10 * mm),
        P("가변 계측–레일 변형 디지털 트윈 기반<br/>갠트리 크레인 예측 안전관리 시스템", "cover_title"),
        Spacer(1, 4 * mm),
        P("Rail Deformation Prediction for Gantry Crane Digital Twin Safety Management", "cover_en"),
        Spacer(1, 8 * mm),
        mt,
        Spacer(1, 8 * mm),
        callout_box(
            "본 팀은 2026년 6월부터 스마트해운물류×ICT 멘토링으로 축소 모형 기반 레일 변형 "
            "디지털 트윈을 구축해 왔다. 본 계획서는 그 성과를 출발점으로, 프로그램 기간 "
            "(2026. 9. ~ 2027. 2.)에 실측·기업 멘토링·시제품 고도화·경진대회 시연까지 "
            "이어 가려는 활동 계획이다."
        ),
        Spacer(1, 8 * mm),
        P(
            "핵심 예측 대상은 상부 거더 구조가 아니라, 대형 갠트리 크레인 <b>하부 주행 레일</b>의 "
            "단차·국부 침하·뒤틀림이다. 좌·우 센서 노드에서 가속도·자이로·레일 간격·위치를 수집하고, "
            "특징 공학과 RBF 대리 모델로 구간 위험도를 추론한 뒤 웹 대시보드와 Godot 3D에 표시한다.",
            "body",
        ),
    ]
    return story


def body_flow():
    story = []

    # 1
    story += [
        section_title("Ⅰ", "지원 취지"),
        P(
            "부산공유대학 다학제 융합 프로젝트는 전공이 다른 학생이 기업 연계 과제를 함께 풀고, "
            "멘토링과 시제품 제작을 거쳐 경진대회로 성과를 검증하는 프로그램이다. 본 팀은 이미 "
            "항만 크레인 레일 안전이라는 지역 산업 문제를 기계·전자·소프트웨어·AI·3D 시각화가 "
            "한 파이프라인으로 만나는 과제로 정의하고, 축소 모형과 실시간 서버·화면까지 구현해 두었다."
        ),
        P(
            "앞으로 6개월의 초점은 아이디어 착수가 아니라 <b>실측으로 파이프라인을 채우고, "
            "기업 멘토의 현장 요구를 시제품에 반영하며, 시연 가능한 완성도를 경진대회 수준으로 "
            "고정하는 일</b>이다. 프로그램의 전문가 특강·멘토링·시제품개발비·최종 경진대회가 "
            "바로 그 구간에 해당한다."
        ),
        bullets(
            [
                "지역 산업 문제: 부산 신항 계열 갠트리 크레인의 하부 주행 레일 기하 이상(단차·침하·뒤틀림)",
                "다학제 실행: 물리 모형 제작, 임베디드 계측, 실시간 백엔드, 신호처리·AI, 디지털 트윈 시각화",
                "기업 연계 방향: 항만 운영·크레인 설비·유지보수 점검의 ‘우선 점검 구간 제시’ 보조 도구",
                "프로그램 산출: 반복 주행 가능한 시제품, 실측 라벨 데이터, 종단 시연, 경진대회 발표",
            ]
        ),
        Spacer(1, 3 * mm),
    ]

    # 2
    story += [
        section_title("Ⅱ", "프로젝트 개요"),
        P("<b>2.1 한 줄 정의</b>", "h2"),
        P(
            "RailTwin은 대형 갠트리 크레인이 하부 주행 레일을 따라 이동할 때 생기는 동적 "
            "가속도·자이로·거리·위치 데이터를 수집하고, 특징 공학과 AI로 레일 단차·국부 침하·뒤틀림 "
            "징후를 구간 단위로 예측·표시하는 디지털 트윈 안전관리 시스템이다."
        ),
        P("<b>2.2 목표 흐름</b>", "h2"),
        P(
            "좌·우 ESP32-C3 Mini 센서 노드(MPU-6050, ADS1115, GTRIC LR18-08U, 로터리 엔코더) → "
            "Wi-Fi MQTT QoS 1 → FastAPI 스키마 검증·특징 공학·PyTorch RBF 추론(pred_rail_deform) → "
            "InfluxDB 저장 및 WebSocket 방송 → 웹 대시보드와 Godot 3D(distance_x, rail_risk 색상)."
        ),
        P("<b>2.3 예측 대상과 하지 않는 것</b>", "h2"),
        P(
            "예측 대상은 하부 주행 레일의 기하 이상이다. 상부 거더 구조의 변형은 본 과제의 핵심 타겟이 아니다. "
            "원시 센서값을 모델에 바로 넣지 않고, 웨이블릿 디노이징과 파고율(Crest Factor) 등 해석 가능한 "
            "특징을 거친 뒤 경량 RBF 대리 모델로 추론한다. 법적 계측기나 전 구간 정밀 측량을 대체하지 않으며, "
            "우선 점검 구간을 제시하는 보조 모니터링을 목표로 한다."
        ),
        P("<b>2.4 예상 결과물</b>", "h2"),
    ]
    story.append(KeepTogether([
        styled_table(
            ["구분", "산출물", "프로그램 종료 시 완성 기준"],
            [
                [
                    "HW",
                    "좌·우 센서 노드, 분압·보호 회로, 3D 출력 구동부 외피, 약 1.4 m급 축소 모형·레일 시험대",
                    "왕복 반복 주행이 가능하고, 단차·침하·뒤틀림 구간을 재현할 수 있을 것",
                ],
                [
                    "계측 SW",
                    "ESP32-C3 Wi-Fi MQTT 펌웨어, 좌·우 노드 프로필, 엔코더·거리 교정값",
                    "두 실물 보드가 고유 ID로 동시에 수신·로그가 남을 것",
                ],
                [
                    "분석 SW",
                    "FastAPI, 특징 공학, RBF 모델, InfluxDB, WebSocket, 더미 스트리머",
                    "실측 재학습 모델과 합성 모델을 구분해 탑재·평가할 것",
                ],
                [
                    "시각화",
                    "웹 대시보드, Godot 위치·좌우 레일 위험도 디지털 트윈",
                    "실물 주행 위치가 화면 구간 색상과 맞을 것",
                ],
                [
                    "증빙",
                    "교정표, 수신 로그, 반복 주행 절차, 시연 시나리오, 경진대회 발표 자료",
                    "완료·미검증·미실시를 섞지 않고 기록할 것",
                ],
            ],
            [22 * mm, 78 * mm, 74 * mm],
        ),
        Spacer(1, 4 * mm),
    ]))

    # 3
    story += [
        section_title("Ⅲ", "개발 배경 및 필요성"),
        P(
            "컨테이너 터미널의 레일 주행 갠트리 크레인은 반복 하중과 야외 환경에 장기간 노출된다. "
            "하부 주행 레일에 단차·국부 침하·뒤틀림이 생기면 바퀴 충격과 진동이 커지고, 주행 안정성과 "
            "유지보수 부담에 영향을 줄 수 있다. 이상이 특정 구간에 집중되는 경우에도 육안·정기 점검만으로는 "
            "운행 중에만 나타나는 동적 이상을 놓치기 쉽다."
        ),
        P(
            "참조 대상은 부산 신항의 HD현대삼호 RMG 계열 갠트리 크레인이다. 본 과제는 현장 전면 설치를 "
            "바로 주장하지 않는다. 먼저 축소 모형에서 좌·우 독립 계측, 위치 정합, 특징 공학, 디지털 트윈 "
            "시각화의 종단 흐름을 검증한 뒤, 기업 멘토링으로 현장 제약(전원, 방진, 교정 주기, 오탐)을 "
            "시제품 요구에 반영하는 경로를 택한다."
        ),
        styled_table(
            ["기존 방식의 한계", "본 과제가 보완하려는 지점"],
            [
                ["정기·육안 점검은 주기 사이·야간·우천의 동적 이상을 놓치기 쉽다.", "주행 중 가속도·자이로·간격·위치를 함께 기록한다."],
                ["정지 상태의 정적 간격만으로는 순간 충격을 포착하기 어렵다.", "파고율 등 충격 특징으로 단차 충격을 강조한다."],
                ["이상 여부만 알리면 점검 인력이 레일 전체를 훑어야 한다.", "엔코더 좌표와 좌·우 구간 색상으로 우선 지점을 좁힌다."],
                ["현장·원격·외주가 구두·사진으로 위치를 주고받는다.", "웹과 3D가 같은 데이터 계약으로 동일 화면을 본다."],
            ],
            [87 * mm, 87 * mm],
        ),
        Spacer(1, 4 * mm),
        P(
            "정량적인 사고 감소율이나 유지보수 비용 절감액은 현장 실증 전에는 주장하지 않는다. "
            "프로그램 기간의 성공 기준은 축소 모형에서 재현 가능한 레일 이상을 위치 단위로 반복 검출·표시하고, "
            "그 과정을 기업 멘토가 이해할 수 있는 시연 시나리오로 고정하는 것이다.",
            "note",
        ),
    ]

    # 4
    story += [
        section_title("Ⅳ", "다학제 융합 구성"),
        P(
            "레일 안전은 센서만의 문제도, 모델만의 문제도 아니다. 설치 방향, 전원, 바퀴 미끄러짐, "
            "엔코더 영점, 데이터 단위, 화면 좌표가 하나라도 어긋나면 위험 구간이 다른 곳에 칠해진다. "
            "이 때문에 본 팀은 처음부터 역할을 학문 영역으로 나누고, 공통 JSON 데이터 계약을 통합 언어로 썼다."
        ),
        styled_table(
            ["팀원", "학문·실무 영역", "프로그램 기간 담당", "융합 접점"],
            [
                [
                    "김정우<br/>(팀장)",
                    "기계 제작·시험<br/>프로젝트 관리",
                    "축소 모형 조립, 레일 이상 재현, 반복 주행 절차, 일정·증빙",
                    "시험 조건이 센서 교정·AI 라벨의 기준이 됨",
                ],
                [
                    "배용진",
                    "전자·임베디드",
                    "회로·전원, ESP32-C3 펌웨어, 분압·거리·엔코더 교정, 구동부 수납",
                    "실측 샘플이 백엔드 계약과 1:1로 맞음",
                ],
                [
                    "배준호",
                    "소프트웨어·AI",
                    "FastAPI·InfluxDB·WebSocket, 특징 공학, RBF 재학습·평가, 배포",
                    "특징·예측값이 웹·Godot 키와 동일함",
                ],
                [
                    "김병서",
                    "시각화·디지털 트윈",
                    "웹 대시보드, Godot 3D, 위치–구간 색상 매핑, 시연 화면 고정",
                    "현장 담당자가 보는 화면이 곧 성과 검증 창구",
                ],
            ],
            [28 * mm, 36 * mm, 58 * mm, 52 * mm],
        ),
        Spacer(1, 2 * mm),
        P("소속 대학·학과·학번은 지정 서식 참가신청서에 기재한다. 본 계획서는 역할과 학문 융합 구조를 중심으로 작성했다.", "small"),
        P("<b>4.1 융합이 일어나는 지점</b>", "h2"),
        bullets(
            [
                "기계 × 전자: 구동부 외피 안에 센서 모듈·모터·배선을 수납하고, 레일 재료가 유도형 센서 출력에 미치는 영향을 시험한다.",
                "전자 × 소프트웨어: 좌 노드 rail-left-01, 우 노드 rail-right-01이 같은 스키마로 MQTT를 보낸다.",
                "신호처리 × AI: 원시 파형이 아니라 웨이블릿·파고율·거리 편차 9개 특징이 모델 입력이 된다.",
                "AI × 디자인: 예측값은 숫자로만 남지 않고, 파랑–초록–노랑–빨강 구간 색상으로 점검 우선순위를 전달한다.",
                "항만 도메인 × 전 전공: ‘어디를 먼저 볼 것인가’라는 현장 질문에 맞춰 좌표·라벨·화면 문구를 통일한다.",
            ]
        ),
        P("<b>4.2 협업 방식</b>", "h2"),
        P(
            "Notion으로 작업과 결정 사항을 기록하고, GitHub으로 소프트웨어 이력을 관리한다. "
            "센서 보드가 준비되기 전에도 웹·Godot·AI가 멈추지 않도록 동일 데이터 계약의 더미 스트리머로 "
            "병렬 개발했다. 회의는 2주에 1회를 기본으로 하고, 프로그램 멘토링·특강 주간에는 피드백을 "
            "이슈로 분해해 담당자에게 배정한다. 구매한 상용 3D 자산과 물리 제작용 모델은 라이선스를 구분해 관리한다."
        ),
    ]

    # 5 architecture
    story += [
        section_title("Ⅴ", "목표 시스템 구성"),
        fig(
            DOCS / "system-architecture-flowchart.png",
            "그림 1. RailTwin 목표 시스템 구성도 — 좌·우 센서 노드에서 특징 공학·AI·웹·3D 디지털 트윈까지.",
            width=170 * mm,
            height=58 * mm,
        ),
        P(
            "하드웨어는 낙상 감지형 단일 센서가 아니다. 축소 갠트리의 좌·우 구동부에 동일한 노드를 "
            "각각 탑재한다. 각 노드는 ESP32-C3 Mini를 MCU로, MPU-6050으로 6축 관성, GTRIC LR18-08U로 "
            "금속 레일 간격(몸체 라벨 기준 DC 15–30 V, 0–10 V 출력, 1–8 mm), 로터리 엔코더로 주행 위치를 잰다. "
            "0–10 V 출력은 ADS1115 입력 범위에 맞추기 위해 분압·보호 회로를 거친다."
        ),
        fig(
            DOCS / "hw-architecture-flowchart.png",
            "그림 2. 하드웨어 구성 — 축소 모형·구동부·센서·ADC가 좌·우 노드로 모인다.",
            width=168 * mm,
            height=48 * mm,
        ),
        fig(
            DOCS / "position-matched-digital-twin.png",
            "그림 3. 위치 정합 — 엔코더 펄스를 distance_x로 바꿔 좌·우 레일 구간 위험도 색상에 대응시킨다.",
            width=150 * mm,
            height=78 * mm,
        ),
        P(
            "서버는 32샘플 롤링 윈도우에 sym3 웨이블릿 디노이징을 적용하고, 동적 가속도 진폭·파고율·거리 변화 등 "
            "특징을 정규화해 RBF 모델에 넣는다. 결과는 CREST, PRED_RAIL_DEFORM, 구간별 rail_risk로 저장·방송된다. "
            "센서가 잠깐 빠지더라도 시연이 멈추지 않도록 더미 스트리머가 같은 계약을 유지한다. "
            "더미·합성 결과는 파이프라인 검증용이며 실측 정확도 증거가 아니다."
        ),
    ]

    # 6 current status
    story += [
        section_title("Ⅵ", "현재 준비 현황"),
        P(
            "기준일은 팀 확인 2026-08-23과 개발보고서 원고 2026-08-25이다. 진척도(%)는 팀 자체 판단값이며, "
            "100%는 코드·구성 구현을 뜻하고 실측 성능·장기 운영 검증 완료를 뜻하지 않는다."
        ),
        styled_table(
            ["영역", "진척", "구현된 것", "아직 아닌 것"],
            [
                ["FastAPI 수집·처리", "100%", "MQTT 구독, 스키마 검증, Queue–Consumer, 오류 격리", "운영 인증서·장기 부하 시험"],
                ["특징 공학·RBF", "50%", "웨이블릿·파고율, 합성 데이터 학습·추론 경로", "실측 재학습, MAE·RMSE·재현율·오탐률"],
                ["InfluxDB·WebSocket", "100%", "시계열 저장, 화면 방송 경로 구현", "운영 WSS 실접속 재확인"],
                ["웹 대시보드", "80%", "좌·우 CREST·PRED·히트맵·연결 상태", "실물 동시 수신 화면 정리"],
                ["Godot 디지털 트윈", "70%", "위치 보간, 좌·우 구간 색상 스크립트", "최종 씬·자산 결합, 실연동 캡처"],
                ["센서 모듈", "80%", "부품·배선·펌웨어 동작 확인, 분압 회로 포함", "전압–거리 교정표, 좌·우 동시 로그"],
                ["구동부·축소 모형", "80%", "3D 출력 외피, 모터·바퀴, 강판 레일, 전체 조립", "반복 주행 시험, 이상 재현 치수 확정"],
            ],
            [36 * mm, 18 * mm, 60 * mm, 60 * mm],
        ),
        Spacer(1, 3 * mm),
        callout_box(
            "지금 시연할 수 있는 범위: 더미 스트리머로 약 1 m 레일의 40~50 cm 단차 충격을 웹·Godot에 흘려 "
            "파이프라인을 점검할 수 있다. 프로그램 기간에 채워야 할 핵심 공백은 반복 주행과 실측 데이터 저장이다. "
            "실물 교정이 끝나지 않으면 이후 재학습·시연은 더미에 남는다.",
            PALE_GOLD,
        ),
        Spacer(1, 4 * mm),
        CondPageBreak(110 * mm),
        P("<b>6.1 보유 하드웨어 (현재 구성)</b>", "h2"),
        photo_row(
            [
                PHOTOS / "13-esp32-c3-mini.jpg",
                PHOTOS / "03-mpu6050-gy521.jpg",
                PHOTOS / "02-gtric-lr18-08u.jpg",
                PHOTOS / "04-ads1115.jpg",
                PHOTOS / "01-18650-battery.jpg",
            ],
            ["ESP32-C3 Mini", "MPU-6050", "GTRIC LR18-08U", "ADS1115", "18650 전원"],
        ),
        photo_row(
            [
                PHOTOS / "07-jgb37-520-drive-wheel.jpg",
                PHOTOS / "06-l298n-driver.jpg",
                PHOTOS / "10-drive-housing-side.jpg",
                PHOTOS / "11-galvanized-steel-rail.jpg",
                PHOTOS / "12-rail-metal-strips.jpg",
            ],
            ["JGB37-520 구동륜", "L298N 드라이버", "구동부 외피", "아연도금 강판 레일", "좌·우 레일 판재"],
        ),
        P(
            "취소된 초기 프로토타입(ESP32-S3 + ADXL345 + HC-SR04)은 이력으로만 보존하며 현재 구성에 쓰지 않는다. "
            "GTRIC 0–10 V는 ADS1115에 직접 넣지 않고 분압한다. 회로값·실측 전압은 프로그램 9월 교정 단계에서 기록한다.",
            "note",
        ),
    ]

    # 7 plan - THE CORE
    story += [
        section_title("Ⅶ", "활동 기간 추진 계획 (2026. 9. ~ 2027. 2.)"),
        P(
            "프로그램 활동 기간에 맞춰 기존 스마트해운물류 2차 평가(2026-09-30)와 일정을 겹쳐 운영한다. "
            "9월은 교정·첫 반복 주행으로 두 일정을 동시에 채우고, 10월 이후는 본 프로그램 고유 목표인 "
            "시제품 고도화·기업 멘토링 반영·경진대회 시연에 집중한다."
        ),
        P("<b>7.1 월별 중점 일정</b>", "h2"),
        gantt_table(),
        Spacer(1, 3 * mm),
        CondPageBreak(95 * mm),
    ]
    story.append(KeepTogether([
        P("<b>7.2 단계별 목표와 완료 기준</b>", "h2"),
        styled_table(
            ["단계", "기간", "목표", "완료로 인정하는 증거"],
            [
                [
                    "A. 실물 계측",
                    "2026. 9. ~ 10.",
                    "좌·우 프로필 업로드, 분압·거리·엔코더 교정, 첫 왕복 주행",
                    "전압 측정표, 교정값, 동시 MQTT 수신 로그, 주행 절차서",
                ],
                [
                    "B. 라벨·재학습",
                    "2026. 10. ~ 12.",
                    "정상·단차·침하·뒤틀림 재현, 실측 저장, RBF 재학습",
                    "라벨 데이터셋, 학습 로그, 합성 수치와 분리된 평가표",
                ],
                [
                    "C. 시제품·시연",
                    "2026. 11. ~ 2027. 1.",
                    "수납·배선 보호, 웹·Godot 종단 화면, 멘토 요구 반영",
                    "시연 시나리오 3종, 실물 화면 캡처, 멘토 피드백 반영 목록",
                ],
                [
                    "D. 경진대회",
                    "2027. 1. ~ 2.",
                    "발표·시연 고정, 한계와 후속 과제를 정직하게 정리",
                    "발표 자료, 시연 체크리스트, 후속 파일럿 제안 1쪽",
                ],
            ],
            [28 * mm, 32 * mm, 54 * mm, 60 * mm],
        ),
    ]))
    story += [
        P("<b>7.3 월별 실행 내용</b>", "h2"),
        P(
            "<b>2026년 9월 — 교정과 첫 반복 주행.</b> 좌·우 ESP32-C3에 고유 프로필을 올리고 분압 전압, "
            "LR18 거리, 엔코더 방향·영점을 멀티미터와 주행으로 맞춘다. 왕복 절차를 문서로 남기고 "
            "정상 구간 데이터를 InfluxDB에 저장한다. 프로그램 오리엔테이션·1차 멘토링에서 받은 "
            "현장 질문을 요구사항 목록으로 옮긴다. 같은 달 스마트해운물류 2차 평가 자료와 증빙을 공유한다."
        ),
        P(
            "<b>2026년 10월 — 레일 이상 재현과 라벨.</b> 단차(얇은 금속 심), 국부 침하(구간 단차·간격 변화), "
            "뒤틀림(좌우 높이차)을 축소 모형에서 재현 가능한 치수로 고정한다. 조건별 왕복을 반복하고 "
            "위치·특징·라벨을 묶은 데이터셋을 만든다. 기업 멘토에게 재현 방법이 현장 이상과 어떻게 "
            "다른지 확인받고, 과대 주장 문장을 계획에서 제거한다."
        ),
        P(
            "<b>2026년 11월 — 실측 재학습과 화면 고정.</b> 실측으로 RBF를 재학습하고 MAE, RMSE, "
            "재현율, 오탐률, 추론 지연시간을 합성 결과와 같은 표에 섞지 않고 적는다. 웹 히트맵과 "
            "Godot 구간 색상이 실물 위치와 맞는지 캡처한다. 시제품은 브레드보드 노출 배선을 줄이고 "
            "구동부 내부 고정·케이블 보호를 보강한다."
        ),
        P(
            "<b>2026년 12월 — 멘토링 반영과 시제품 안정화.</b> 특강·멘토링에서 나온 전원 안정, 오탐, "
            "교정 주기, 화면 가독성 이슈를 한 달 백로그로 처리한다. 시연 시나리오를 "
            "① 정상 왕복 ② 단차 구간 통과 ③ 좌우 치우침(뒤틀림 모사) 세 가지로 잠근다. "
            "2차 합격 시 시제품개발비는 이 달의 PCB·외피·재현 치구에 우선 투입한다."
        ),
        P(
            "<b>2027년 1월 — 경진대회 시연 완성.</b> 발표 10분 안에 문제–계측–특징–위치–화면이 이어지도록 "
            "시연 대본과 실패 시 더미 전환 절차를 준비한다. 한계(축소 모형, 실측 규모, 비인증 보조 도구)를 "
            "슬라이드에 명시한다. 후속 지원을 가정한 현장 파일럿 1쪽 제안(단일 크레인, 점검 보조 범위)을 작성한다."
        ),
        P(
            "<b>2027년 2월 — 성과 발표와 인수.</b> 최종 경진대회에서 실물 주행과 화면을 함께 보여 준다. "
            "코드·교정표·데이터 사전·시연 체크리스트를 저장소와 문서에 남겨, 멘토나 후속 팀이 "
            "재현할 수 있게 한다."
        ),
        P("<b>7.4 멘토링·특강 활용 방법</b>", "h2"),
        bullets(
            [
                "항만·설비 멘토: 단차·침하·뒤틀림을 현장이 실제로 어떻게 부르는지, 점검 주기와 우선순위를 확인한다.",
                "전자·신뢰성 멘토: 분압·전원 리플, 커넥터, 진동 환경에서 배선이 풀리는 지점을 시제품에 반영한다.",
                "AI·데이터 멘토: 오탐·누락의 비용을 묻고, 알림 자동화 전에 우선 구간 제시로 범위를 제한한다.",
                "특강 후 48시간 내 팀 노션에 ‘들은 것 / 이번 스프린트에 넣을 것 / 넣지 않을 것’을 세 칸으로 기록한다.",
            ]
        ),
    ]

    # 8 company
    story += [
        section_title("Ⅷ", "기업 연계 계획"),
        P(
            "현재 시점에 확정된 기업 협약서나 현장 설치 허가는 없다. 공고가 기업 연계형 멘토링을 "
            "제공하는 만큼, 본 팀은 연계 대상을 ‘이미 있는 계약’이 아니라 "
            "<b>프로그램이 연결해 줄 항만·크레인·유지보수 전문가와 함께 시제품 요구를 다듬는 일</b>로 정의한다."
        ),
        styled_table(
            ["연계 층위", "대상 예시", "우리가 보여줄 것", "우리가 받으려는 것"],
            [
                [
                    "도메인",
                    "항만 운영·안전, 크레인 관제",
                    "축소 모형 주행 + 좌·우 위험 구간 화면",
                    "점검 담당자가 실제로 쓰는 위치 표현, 오탐 허용 범위",
                ],
                [
                    "설비",
                    "크레인 제작·레일 정비",
                    "유도형 간격 + 관성 + 엔코더 결합 방식",
                    "후장착 가능 여부, 전원·방진·교정 주기",
                ],
                [
                    "점검 서비스",
                    "외주 점검·설비진단",
                    "우선 구간을 좌표로 넘기는 대시보드",
                    "보고서 형식, 현장 동선, 도입 장벽",
                ],
            ],
            [28 * mm, 42 * mm, 52 * mm, 52 * mm],
        ),
        Spacer(1, 3 * mm),
        P(
            "상용화 주장은 프로그램 기간의 목표가 아니다. 1단계는 교육·시연용 축소 모형, "
            "2단계는 단일 크레인 후장착 파일럿, 3단계는 다중 크레인 구독형 화면이라는 경로만 제시하고, "
            "원가·단가·매출은 산출하지 않는다. 본 작품은 인증 검측 장비를 대체하지 않는다."
        ),
    ]

    # 9 outcomes
    story += [
        section_title("Ⅸ", "기대 성과와 경진대회 시연"),
        P("<b>9.1 프로그램 종료 시 팀 성과</b>", "h2"),
        bullets(
            [
                "다학제 시제품: 기계 모형 + 임베디드 노드 + 실시간 AI 파이프라인 + 3D 디지털 트윈이 한 시연으로 연결된다.",
                "실측 근거: 합성 데이터와 구분된 반복 주행 로그, 교정표, (규모가 작더라도) 실측 평가 지표.",
                "기업 언어: 멘토 피드백을 반영한 ‘우선 점검 구간’ 화면과 한계 명시.",
                "재현 가능성: 다른 전공 학생·멘토가 문서만 보고 데이터 흐름을 따라갈 수 있는 계약·절차.",
            ]
        ),
        P("<b>9.2 경진대회 시연 시나리오</b>", "h2"),
        styled_table(
            ["순서", "장면", "관객이 확인하는 것"],
            [
                ["1", "정상 구간 왕복", "좌·우 노드가 동시에 올라오고, 화면 위치가 모형과 같이 움직인다."],
                ["2", "단차 재현 구간 통과", "파고율과 예측값이 오르고, 해당 구간이 노랑·빨강으로 남는다."],
                ["3", "좌우 치우침 모사", "한쪽 레일만 위험도가 쌓여 좌·우 독립 계측의 의미가 드러난다."],
                ["4", "대시보드 인수인계", "원격 화면만 보고 ‘몇 cm 구간을 볼지’를 말할 수 있다."],
                ["5", "한계 한 장", "축소 모형·실측 규모·비인증 보조 도구임을 명시하고 후속 파일럿을 제안한다."],
            ],
            [18 * mm, 42 * mm, 114 * mm],
        ),
        P("<b>9.3 사용자 기대효과 (정성, 실증 전)</b>", "h2"),
        P(
            "점검 담당자는 레일 전체를 같은 밀도로 훑는 대신, 위험도가 누적된 좌·우 구간부터 볼 수 있다. "
            "유지보수·외주 팀은 웹 화면의 거리 좌표로 작업 지점을 공유할 수 있다. "
            "이 효과는 시연과 멘토 인터뷰로 설득력을 점검하고, 수치화는 현장 파일럿 이후로 미룬다."
        ),
    ]

    # 10 budget
    story += [
        section_title("Ⅹ", "시제품 개발비 활용 방향 (2차 합격 시)"),
        P(
            "1차 합격은 멘토링, 2차 합격은 멘토링·시제품개발비·특강·경진대회 자격이 공고에 명시되어 있다. "
            "개발비 금액이 공고에 없으므로 본 계획서는 금액이 아니라 우선순위를 적는다. "
            "이미 보유한 센서·모터·모형에 중복 구매하지 않고, 실측과 시연을 막는 항목만 보강한다."
        ),
        styled_table(
            ["우선순위", "항목", "이유"],
            [
                ["1", "분압·보호 회로의 고정 기판화(PCB 또는 프로토보드 정리), 커넥터·케이블 보호", "반복 주행 중 배선 이탈이 데이터를 망가뜨리기 때문"],
                ["2", "단차·침하·뒤틀림 재현 치구(심, 받침, 좌우 높이차 블록)와 레일 보강", "라벨 데이터의 재현 가능성을 만들기 때문"],
                ["3", "구동부 내부 수납 재출력, 방진·전선 고정, 예비 배터리·커넥터", "시연 중 전원·기구 실패를 줄이기 때문"],
                ["4", "좌·우 동시 로깅·화면 시연을 위한 소모품, 출력·가공비", "경진대회 당일 예비 부품이 필요하기 때문"],
                ["5", "현장 멘토 방문·비교 조사에 필요한 출력물·간단한 계측 도구", "요구사항 확인을 추측이 아닌 기록으로 남기기 때문"],
            ],
            [22 * mm, 88 * mm, 64 * mm],
        ),
        Spacer(1, 2 * mm),
        P("고가 상용 라이선스 3D 자산의 추가 구매, 불필요한 센서 교체, 근거 없는 클라우드 대규모 증설은 개발비 대상에서 제외한다.", "note"),
    ]

    # 11 risks
    story += [
        section_title("Ⅺ", "위험 요인 및 대응"),
        styled_table(
            ["위험", "영향", "대응"],
            [
                [
                    "실물 교정 지연",
                    "재학습·시연이 더미에 머문다",
                    "9월에 교정만으로 완료 기준을 두고, 이상이 있으면 한 쪽 노드라도 먼저 로그를 확보한다.",
                ],
                [
                    "레일 이상 재현이 현장과 다름",
                    "기업 멘토가 시연을 모형 장난으로 본다",
                    "재현 치수를 명시하고, ‘모사’와 ‘실측 성능’을 발표에서 분리한다.",
                ],
                [
                    "오탐이 많음",
                    "신뢰가 떨어진다",
                    "알림 자동화를 하지 않고, 구간 색상·우선 점검 제시에 범위를 한정한다.",
                ],
                [
                    "시연 당일 통신·전원 실패",
                    "경진대회 설득력이 무너진다",
                    "더미 스트리머 전환 절차와 로컬 녹화 백업을 시연 체크리스트에 넣는다.",
                ],
                [
                    "역할 과부하",
                    "통합 주간에 한 전공만 남는다",
                    "데이터 계약을 먼저 잠그고, 2주 회의에서 통합 시험 날짜를 고정한다.",
                ],
            ],
            [38 * mm, 48 * mm, 88 * mm],
        ),
        Spacer(1, 4 * mm),
        section_title("Ⅻ", "맺음말"),
        P(
            "본 팀은 아이디어 단계에서 지원하는 것이 아니라, 이미 돌아가는 계측–서버–AI–디지털 트윈 "
            "뼈대를 가지고 지원한다. 빈 칸은 분명하다. 반복 주행, 실측 라벨, 기업이 믿을 수 있는 "
            "시연 문장이다. 부산공유대학 다학제 융합 프로젝트의 6개월은 그 빈 칸을 메우기에 맞는 시간이다."
        ),
        P(
            "기계가 레일을 만들고, 전자가 간격을 읽고, 소프트웨어가 위치를 묶고, AI가 특징을 해석하며, "
            "시각화가 점검 지점을 가리킨다. 그 연결이 곧 다학제이고, 부산 항만의 크레인 레일이 그 연결의 현장이다. "
            "프로그램의 멘토링과 시제품 지원을 받아, 2027년 2월에는 축소 모형 위에서라도 "
            "‘이 구간을 먼저 보십시오’라고 말할 수 있는 시연을 완성하겠다."
        ),
        Spacer(1, 4 * mm),
        callout_box(
            "첨부·별도 제출: ① 지정 서식 참가신청서 ② 본 활동 계획서 PDF. "
            "팀원 인적사항·연락처는 신청서에만 기재한다. 본 문서의 기술 서술은 2026-08-23 팀 확인 및 "
            "저장소 구현을 기준으로 하며, 이후 교정값은 활동 기간 중 갱신한다."
        ),
    ]
    return story


def build():
    page_w, page_h = A4
    left = 18 * mm
    right = 18 * mm
    usable_w = page_w - left - right

    cover_top = Frame(
        left,
        page_h - 74 * mm,
        usable_w,
        54 * mm,
        id="cover_top",
        showBoundary=0,
    )
    cover_rest = Frame(
        left,
        28 * mm,
        usable_w,
        page_h - 78 * mm - 28 * mm,
        id="cover_rest",
        showBoundary=0,
    )
    body_frame = Frame(
        left,
        16 * mm,
        usable_w,
        page_h - 16 * mm - 16 * mm,
        id="body",
        showBoundary=0,
    )

    doc = BaseDocTemplate(
        str(OUT),
        pagesize=A4,
        title="제2회 2026 기업 연계 부산공유대학 다학제 융합 프로젝트 활동 계획서 — RailTwin",
        author="RailTwin 팀",
        subject="자유 형식 활동 계획서",
    )
    doc.addPageTemplates(
        [
            PageTemplate(id="cover", frames=[cover_top, cover_rest], onPage=cover_page),
            PageTemplate(id="body", frames=[body_frame], onPage=header_footer),
        ]
    )

    story = cover_flow() + [NextPageTemplate("body"), PageBreak()] + body_flow()
    doc.build(story)
    print(OUT)


if __name__ == "__main__":
    build()
