#!/usr/bin/env python3
"""부산공유대학 다학제 융합 프로젝트 수행계획서 PDF 생성."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
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
REFS = DOCS / "ref-images"
OUT = DOCS / "2026_부산공유대학_다학제융합_수행계획서.pdf"

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
STRIKE = HexColor("#8B3A3A")


def styles():
    getSampleStyleSheet()
    return {
        "cover_kicker": ParagraphStyle(
            "cover_kicker", fontName="Kr", fontSize=9, leading=13, textColor=GOLD,
            alignment=TA_CENTER,
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
            "cover_title", fontName="KrSerif", fontSize=15.5, leading=23, textColor=NAVY,
            alignment=TA_CENTER,
        ),
        "cover_en": ParagraphStyle(
            "cover_en", fontName="Kr", fontSize=8.5, leading=13, textColor=MUTED,
            alignment=TA_CENTER,
        ),
        "cover_meta": ParagraphStyle(
            "cover_meta", fontName="Kr", fontSize=9.5, leading=15, textColor=INK,
            alignment=TA_LEFT,
        ),
        "h1": ParagraphStyle(
            "h1", fontName="Kr", fontSize=13.2, leading=19, textColor=NAVY,
            spaceBefore=2, spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "h2", fontName="Kr", fontSize=11, leading=16, textColor=TEAL,
            spaceBefore=9, spaceAfter=9,
        ),
        "h3": ParagraphStyle(
            "h3", fontName="Kr", fontSize=10, leading=14.5, textColor=NAVY,
            spaceBefore=7, spaceAfter=8,
        ),
        "body": ParagraphStyle(
            "body", fontName="Kr", fontSize=9.3, leading=15, textColor=INK,
            alignment=TA_LEFT, spaceAfter=5.5,
        ),
        "note": ParagraphStyle(
            "note", fontName="Kr", fontSize=8.2, leading=12.6, textColor=WARN,
            alignment=TA_LEFT, spaceBefore=1, spaceAfter=7,
        ),
        "caption": ParagraphStyle(
            "caption", fontName="Kr", fontSize=7.9, leading=11.6, textColor=MUTED,
            alignment=TA_CENTER, spaceBefore=2, spaceAfter=8,
        ),
        "cell": ParagraphStyle(
            "cell", fontName="Kr", fontSize=8.0, leading=12.0, textColor=INK,
            alignment=TA_LEFT,
        ),
        "cell_c": ParagraphStyle(
            "cell_c", fontName="Kr", fontSize=8.0, leading=12.0, textColor=INK,
            alignment=TA_CENTER,
        ),
        "th": ParagraphStyle(
            "th", fontName="Kr", fontSize=8.0, leading=11.6, textColor=white,
            alignment=TA_CENTER,
        ),
        "bullet": ParagraphStyle(
            "bullet", fontName="Kr", fontSize=9.2, leading=14.6, textColor=INK,
            leftIndent=2, spaceAfter=1.5,
        ),
        "callout": ParagraphStyle(
            "callout", fontName="Kr", fontSize=9.1, leading=14.4, textColor=NAVY,
            alignment=TA_LEFT,
        ),
        "small": ParagraphStyle(
            "small", fontName="Kr", fontSize=7.8, leading=11.8, textColor=MUTED,
            alignment=TA_LEFT, spaceAfter=3,
        ),
        "old": ParagraphStyle(
            "old", fontName="Kr", fontSize=7.8, leading=11.6, textColor=STRIKE,
            alignment=TA_LEFT,
        ),
        "new": ParagraphStyle(
            "new", fontName="Kr", fontSize=7.8, leading=11.6, textColor=INK,
            alignment=TA_LEFT,
        ),
        "sign": ParagraphStyle(
            "sign", fontName="Kr", fontSize=9, leading=13.5, textColor=INK,
            alignment=TA_CENTER,
        ),
        "kv": ParagraphStyle(
            "kv", fontName="Kr", fontSize=9, leading=13.5, textColor=INK,
            alignment=TA_LEFT,
        ),
    }


S = styles()


def P(text, style="body"):
    return Paragraph(text, S[style])


def bullets(items):
    flow = []
    for item in items:
        flow.append(ListItem(P(item, "bullet"), leftIndent=12, bulletColor=TEAL, value="•"))
    return ListFlowable(
        flow, bulletType="bullet", start="•", leftIndent=14, bulletFontName="Kr", bulletFontSize=9
    )


def section_title(num, title):
    bar = Table([[P(f"{num}  {title}", "h1")]], colWidths=[174 * mm])
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
    return KeepTogether([bar, Spacer(1, 5)])


def callout_box(text, bg=PALE_TEAL):
    t = Table([[P(text, "callout")]], colWidths=[174 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("BOX", (0, 0), (-1, -1), 0.4, TEAL),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return t


def styled_table(headers, rows, col_widths, header_bg=NAVY, first_center=False):
    data = [[P(h, "th") for h in headers]]
    for row in rows:
        cells = []
        for i, val in enumerate(row):
            if isinstance(val, Paragraph):
                cells.append(val)
            else:
                use = "cell_c" if (first_center and i == 0) else "cell"
                cells.append(P(str(val), use))
        data.append(cells)
    t = Table(data, colWidths=col_widths, repeatRows=1)
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("BACKGROUND", (0, 1), (-1, -1), white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4.5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), PALE))
    t.setStyle(TableStyle(cmds))
    return t


def kv_table(rows, label_w=38 * mm):
    data = []
    for k, v in rows:
        data.append([P(f"<b>{k}</b>", "kv"), P(v, "kv")])
    t = Table(data, colWidths=[label_w, 174 * mm - label_w])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), PALE_GOLD),
                ("BACKGROUND", (1, 0), (1, -1), PALE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.3, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return t


def case_with_image(title, body, img_path, caption, img_w=62 * mm, img_h=42 * mm):
    img = sized_image(img_path, img_w, img_h)
    text = [P(f"<b>{title}</b>", "h3"), P(body, "body")]
    left = Table([[x] for x in text], colWidths=[108 * mm])
    left.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    right = Table([[img], [P(caption, "caption")]], colWidths=[66 * mm])
    right.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, 0), PALE),
                ("BOX", (0, 0), (0, 0), 0.3, LINE),
                ("TOPPADDING", (0, 0), (0, 0), 3),
                ("BOTTOMPADDING", (0, 0), (0, 0), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    row = Table([[left, right]], colWidths=[108 * mm, 66 * mm])
    row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return KeepTogether([row])


def sized_image(path, width, height):
    img = Image(str(path), width=width, height=height, kind="proportional")
    iw = float(getattr(img, "imageWidth", 0) or width)
    ih = float(getattr(img, "imageHeight", 0) or height)
    ratio = ih / iw if iw else 1.0
    dw, dh = width, width * ratio
    if dh > height:
        dh = height
        dw = dh / ratio if ratio else width
    img.drawWidth = dw
    img.drawHeight = dh
    return img


def fig(path, caption, width=174 * mm, height=62 * mm):
    img = sized_image(path, width, height)
    t = Table([[img]], colWidths=[174 * mm])
    t.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("BOX", (0, 0), (-1, -1), 0.3, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return KeepTogether([t, P(caption, "caption")])


def photo_row(paths, captions, height=27 * mm):
    imgs, caps = [], []
    for path, cap in zip(paths, captions):
        imgs.append(Image(str(path), width=32 * mm, height=height, kind="proportional"))
        caps.append(P(cap, "caption"))
    n = len(paths)
    col_w = 174 * mm / n
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


def gantt_table():
    months = ["9월 초", "9월 중", "9월 말", "10월 초", "10월 중", "10월 말"]
    rows_raw = [
        ("요구 정의·부품 수급·회로/펌웨어 설계", "■", "■", "□", "", "", ""),
        ("센서 모듈·축소 모형 제작", "□", "■", "■", "□", "", ""),
        ("첫 주행·교정·라벨 수집", "", "", "■", "■", "□", ""),
        ("시제품 수납·배선 고도화", "", "□", "■", "■", "□", ""),
        ("실측 재학습·정량 평가", "", "", "", "■", "■", "□"),
        ("웹·Godot 종단 시연 고정", "", "", "□", "■", "■", "■"),
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
    fill = {"■": TEAL, "□": PALE_GOLD}
    for r, row in enumerate(rows_raw, start=1):
        for c, mark in enumerate(row[1:], start=1):
            if mark in fill:
                cmds.append(("BACKGROUND", (c, r), (c, r), fill[mark]))
                cmds.append(("TEXTCOLOR", (c, r), (c, r), white if mark == "■" else WARN))
    t.setStyle(TableStyle(cmds))
    legend = P("■ 중점 수행 &nbsp;&nbsp; □ 보조·마무리 &nbsp;&nbsp; 공란은 해당 구간 비집중. 10월 말 완성 기준.", "small")
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
        canvas.drawString(18 * mm, h - 8.2 * mm, "수행계획서")
        canvas.drawRightString(
            w - 18 * mm, h - 8.2 * mm, "2026학년도 기업 연계 부산공유대학 다학제 융합 프로젝트"
        )
        canvas.setFillColor(PALE)
        canvas.rect(0, 0, w, 12 * mm, fill=1, stroke=0)
        canvas.setFillColor(GOLD)
        canvas.rect(0, 12 * mm, w, 0.8, fill=1, stroke=0)
        canvas.setFillColor(MUTED)
        canvas.setFont("Kr", 7.4)
        canvas.drawString(18 * mm, 5.2 * mm, "수행계획서  ·  활동 기간 2026. 9. ~ 2026. 10.")
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
    canvas.drawCentredString(w / 2, 10 * mm, "작성일 2026. 9. 4.")
    canvas.restoreState()


def cover_flow():
    sign = Table(
        [
            [P("<b>구분</b>", "th"), P("<b>성명</b>", "th"), P("<b>역할</b>", "th"), P("<b>서명</b>", "th")],
            [P("팀장", "sign"), P("김정우", "sign"), P("조립·시험·프로젝트 관리", "sign"), P("", "sign")],
            [P("팀원", "sign"), P("배용진", "sign"), P("센서·ESP32·회로", "sign"), P("", "sign")],
            [P("팀원", "sign"), P("김병서", "sign"), P("Godot·웹·3D 모델", "sign"), P("", "sign")],
            [P("팀원", "sign"), P("배준호", "sign"), P("백엔드·AI·배포", "sign"), P("", "sign")],
        ],
        colWidths=[28 * mm, 32 * mm, 70 * mm, 44 * mm],
    )
    sign.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("BACKGROUND", (0, 1), (-1, -1), white),
                ("GRID", (0, 0), (-1, -1), 0.35, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("BACKGROUND", (0, 1), (0, -1), PALE),
            ]
        )
    )

    story = [
        Spacer(1, 8 * mm),
        P("BUSAN SHARED UNIVERSITY", "cover_kicker"),
        Spacer(1, 4 * mm),
        P("2026학년도 기업 연계", "cover_prog"),
        P("부산공유대학 다학제 융합 프로젝트", "cover_prog"),
        Spacer(1, 5 * mm),
        P("수 행 계 획 서", "cover_kind"),
        FrameBreak(),
        Spacer(1, 8 * mm),
        P("갠트리 크레인 하부 주행 레일 변형<br/>디지털 트윈 안전관리 시스템", "cover_title"),
        Spacer(1, 3 * mm),
        P("Gantry Crane Running-Rail Deformation Digital Twin Safety Management", "cover_en"),
        Spacer(1, 7 * mm),
        sign,
    ]
    return story


def body_flow():
    story = []

    # I
    story += [
                section_title("Ⅰ", "프로젝트 정보"),
        kv_table(
            [
                ("프로젝트명", "갠트리 크레인 하부 주행 레일 변형 디지털 트윈 안전관리 시스템"),
                ("주제영역", "스마트 항만 및 자동화  ·  인공지능 및 데이터 분석  ·  사물인터넷 및 센서 기술"),
                ("성과목표", "기술교육  ·  시제품·경진대회 시연  ·  (여건 시) 프로그램 저작권 등록 검토"),
                ("수행기간", "2026. 9. 1. ~ 2026. 10. 31."),
                ("수행 단계", "신규 착수. 본 문서는 목표 시스템과 일정·역할을 정한 계획서이다"),
            ]
        ),
                P("<b>프로젝트 소개 및 제안배경</b>", "h2"),
        P(
            "갠트리 크레인이 매일 오가는 하부 주행 레일은 컨테이너 하중과 지반·배수·온도 변화의 영향을 받는다. "
            "단차·국부 침하·뒤틀림이 생기면 바퀴와 구동부에 충격이 반복되고, 심한 경우 주행 안정성 저하로 "
            "이어질 수 있다. 스마트 야드와 자동화가 진행되는 항만·조선 현장에서도, 레일 상태 점검은 "
            "여전히 육안 순회나 일시 측량에 의존하는 경우가 많다."
        ),
        P(
            "본 프로젝트는 크레인이 레일을 주행하는 일상 과정에서 좌·우 센서 노드가 동적 데이터를 수집하고, "
            "특징 공학과 AI로 구간 위험도를 추정해 점검 우선순위를 제시하는 디지털 트윈을 제안한다. "
            "법적 계측기나 전 구간 정밀 측량을 대체하지 않는다. 본 기간의 범위는 축소 모형에서 재현한 "
            "단차·침하·뒤틀림을 위치 단위로 보여 주는 보조 모니터링이다."
        ),
                P("<b>주요 기능</b>", "h2"),
        bullets(
            [
                "(1) 데이터 수집: 좌·우 ESP32-C3 Mini가 가속도·자이로·레일 간격·주행 위치를 실시간 수집한다. "
                "점검 시간을 따로 잡지 않고 주행 중에 재며, 왼쪽과 오른쪽을 나눠 한쪽만 단차이거나 "
                "좌우가 어긋난 치우침을 구분한다.",
                "(2) 위험도 추정: 특징 공학과 RBF로 pred_rail_deform·rail_risk를 산출한다. "
                "원시 파형을 바로 넣지 않고 잡음을 줄인 뒤 파고율 등 특징으로 바꾼다. "
                "예측은 잔여수명이 아니라, 그 구간의 레일 변형 위험 지표다.",
                "(3) 점검 화면: 웹 대시보드와 Godot이 같은 좌표로 우선 점검 지점을 표시한다. "
                "엔코더 위치와 구간 색상(파랑–초록–노랑–빨강)을 맞춰, ‘몇 cm 구간을 먼저 볼지’를 "
                "웹과 3D가 같이 보여 준다.",
            ]
        ),
                P("<b>기대효과 및 활용분야</b>", "h2"),
        P(
            "본 작품의 효과는 전면 운행 중단 없이 ‘이 구간을 먼저 보십시오’라고 말할 수 있게 하는 데 있다. "
            "점검·정비·관제 담당자가 같은 웹·3D 화면으로 우선 지점을 합의하면, 레일 전체를 같은 밀도로 "
            "걷는 부담과 현장 노출을 줄일 수 있다. 활용의 1차 대상은 스마트 항만·조선소의 레일 주행 갠트리이며, "
            "같은 질문이 있는 제철소·물류 레일 설비의 교육·시연·1차 스크리닝으로도 옮길 수 있다. "
            "사고 감소율과 비용 절감액은 현장 실증 전에 주장하지 않는다. 사용자별 효과는 Ⅲ에서 구체화한다."
        ),
        KeepTogether(
            [
                P("<b>예상 결과물</b>", "h2"),
                styled_table(
                    ["구분", "산출물", "프로그램 종료 시 완성 기준"],
                    [
                        [
                            "HW",
                            "좌·우 센서 노드, 분압·보호 회로, 3D 출력 구동부 외피, 약 1.4 m급 축소 모형·강판 레일",
                            "왕복 반복 주행이 가능하고 단차·침하·뒤틀림 구간을 재현할 수 있을 것",
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
                    ],
                    [22 * mm, 80 * mm, 72 * mm],
                    first_center=True,
                ),
            ]
        ),
        Spacer(1, 3 * mm),
        KeepTogether(
            [
                P("<b>작품 구성도</b>", "h2"),
                fig(
                    DOCS / "system-architecture-flowchart.png",
                    "그림 1. 시스템 구성도 — 계측에서 화면까지의 흐름.",
                    height=70 * mm,
                ),
            ]
        ),
        P(
            "축소 모형의 왼쪽·오른쪽 구동부가 주행하면서 진동, 레일과의 간격, 위치를 잰다. "
            "그 값은 무선으로 서버에 모인다. 서버는 잡음을 줄이고 특징을 뽑은 뒤, "
            "AI로 그 구간의 레일 변형 위험도를 추정한다. "
            "결과는 저장되고, 웹과 3D 화면이 같은 주행 데이터를 받아, "
            "모형이 있는 지점과 위험도가 높게 추정된 레일 구간을 함께 보여 준다.",
            "small",
        ),
    ]

    # II-1
    story += [
                section_title("Ⅱ", "프로젝트 수행계획"),
        P("1. 프로젝트 개요", "h2"),
        P("가. 프로젝트", "h3"),
        P(
            "본 과제는 갠트리 크레인 <b>하부 주행 레일</b>의 단차·국부 침하·뒤틀림을 "
            "주행 중 동적 데이터로 감지·표시한다."
        ),
        P(
            "결함 탐지는 가속도·자이로·간격 특징으로 이상의 유무와 위치를 가리는 것이다. "
            "AI 예측은 잔여수명이나 실제 항만 레일의 파손 시점을 맞히는 것이 아니라, "
            "같은 특징으로 해당 구간의 레일 변형 위험 지표(pred_rail_deform)를 추정하는 것이다. "
            "‘사전’의 의미는 육안 점검 이전, 주행 중에 약한 충격·간격 변동이 커질 때 위험도가 먼저 오르는 것을 말한다."
        ),
                P("나. 프로젝트 추진배경 및 필요성", "h3"),
        P(
            "상용 예지보전과 야드 디지털 트윈은 모터·베어링 고장이나 장비 흐름 최적화에 가깝다. "
            "하부 주행 레일의 단차·침하·뒤틀림은 그 대상이 아니다. 좌·우 레일을 나누어 보지 않으면 "
            "한쪽만 단차이거나 좌우가 어긋난 치우침을 한 점 이상으로 남기기 어렵다."
        ),
        P(
            "본 기간에 필요한 것은 실제 항만 레일의 mm 예측기가 아니다. "
            "주행 중 동적 신호와 엔코더 위치를 묶어, 재현한 결함을 그 구간에서 잡는 파이프라인이 "
            "닫히는지를 10월 말까지 보이는 것이다. 그 증명이 없으면 웹·3D 화면은 시연용 그림에 머문다."
        ),
        KeepTogether(
            [
                P("다. 국내외 유사 프로젝트 (참고)", "h3"),
                P("아래 사진은 각 참고 사례의 공개 자료이며, 본 계획의 실물 성과가 아니다.", "small"),
                case_with_image(
                    "부산항만공사 갠트리 크레인 레일 보수 특허",
                    "BPA는 복합형 솔 플레이트(SOLE PLATE)를 이용한 레일 보수 특허를 등록했다. "
                    "솔 플레이트는 레일 하면에 설치하는 강판으로, 볼트 구멍·여유 폭을 키워 하부 그라우트 제거 없이 "
                    "측방·상하 조정이 가능하도록 한 보수 공법이다. "
                    "출처: https://n.news.naver.com/mnews/article/079/0003593699",
                    REFS / "01-bpa-sole-plate.jpg",
                    "그림. 복합형 솔 플레이트 설치 모습. 부산항만공사 제공(보도 전재).",
                ),
            ]
        ),
        case_with_image(
            "독일 함부르크 스마트 크레인",
            "함부르크 HHLA 터미널(CTA)은 크레인·야드 장비에 센서를 붙여 상태를 모니터링하고, "
            "자동화·디지털 트윈으로 가동 효율을 높이려는 사례가 보고되어 있다. "
            "본 과제와 방향은 같으나, 본 팀은 장비 전반이 아니라 <b>하부 주행 레일 기하 이상</b>과 "
            "위치 정합에 초점을 둔다.",
            REFS / "02-hamburg-cta.jpg",
            "그림. HHLA Container Terminal Altenwerder. Wikimedia Commons (F. Grunwald).",
        ),
        case_with_image(
            "부산 신항 디지털 트윈 기반 항만 운영",
            "장비·물류 흐름·야드 상태를 가상 공간에 올려 운영 최적화와 충돌 위험 분석에 쓰는 "
            "통합관제 흐름이 추진되고 있다. 본 과제는 항만 전체 관제가 아니라 "
            "단일 크레인 레일의 점검 보조 화면을 축소 모형에서 검증하는 하위 모듈에 해당한다.",
            REFS / "03-pnit-dt-b.png",
            "그림. 부산 신항 PNIT 디지털 트윈 예시. Eom et al., JMSE 2023 (CC BY 4.0).",
        ),
        case_with_image(
            "ABB 스마트센서",
            "항만 크레인 모터·베어링·구동축의 진동·온도·전력·회전을 무선 센서로 분석하는 "
            "상용 예지보전이다. 본 과제는 구동계 고장이 아니라 레일 단차·침하·뒤틀림의 동적 징후와 "
            "엔코더 좌표를 결합하는 점에서 대상이 다르다.",
            REFS / "04-abb-smart-sensor.jpg",
            "그림. ABB Ability Smart Sensor(베어링 장착형). ABB 보도 자료.",
        ),
                P("라. 추진 프로젝트만의 차별성", "h3"),
        P(
            "참고 사례는 레일 보수 공법, 야드 전체 디지털 트윈, 구동계 예지보전에 가깝다. "
            "본 과제는 하부 주행 레일의 기하 이상과 위치를 한 화면에 묶는 점검 보조에 초점을 둔다."
        ),
        styled_table(
            ["구분", "내용"],
            [
                [
                    "계측",
                    "정지 간격 측정이 아니라 주행 중 좌·우 독립 노드에서 가속도·자이로·유도형 간격·엔코더 위치를 동시에 수집한다.",
                ],
                [
                    "신호·AI",
                    "원시 파형을 블랙박스에 넣지 않고, 웨이블릿 디노이징과 파고율 등 해석 가능한 특징을 거친 뒤 경량 RBF 대리 모델로 추론한다.",
                ],
                [
                    "위치 정합",
                    "이상 여부만 알리지 않고, distance_x와 좌·우 구간 색상(파랑–초록–노랑–빨강)으로 우선 점검 지점을 특정한다.",
                ],
                [
                    "경제성",
                    "지하 매립·대규모 토목 없이 기존 구동부 외피에 수납하는 후장착 모듈과 오픈소스 서버(FastAPI·MQTT·InfluxDB·Godot)로 구성한다.",
                ],
                [
                    "실시간성",
                    "MQTT QoS 1 업링크와 WebSocket 다운링크로 웹·3D가 같은 계약을 보며, 센서 미연결 시에도 더미 스트리머로 파이프라인을 유지한다.",
                ],
            ],
            [28 * mm, 146 * mm],
            first_center=True,
        ),
        Spacer(1, 2 * mm),
        P(
            "프로그램 기간의 목표는 축소 모형에서 재현 가능한 레일 이상을 위치 단위로 검출·표시하는 것이다. "
            "축소 모형의 추론값은 실제 항만 레일 수치로 확대하지 않는다. 학습은 공개 이종 데이터셋이 아니라, "
            "본 팀이 재현한 정상·단차·침하·뒤틀림 주행의 라벨 데이터를 기준으로 한다. "
            "합성 데이터는 파이프라인 연동 검증용이며 실측 성능으로 쓰지 않는다.",
            "note",
        ),
    ]

    # tech stack
    stack_rows = [
        ["항목", "구성"],
        ["MCU", "좌·우 ESP32-C3 Mini (rail-left-01 / rail-right-01)"],
        ["간격 센서", "GTRIC LR18-08U M18 아날로그 유도형 (0–10 V, 1–8 mm)"],
        ["관성 센서", "MPU-6050 6축 가속도·자이로 (100 Hz)"],
        ["ADC·보호", "ADS1115 16 bit + 0–10 V 분압·입력 보호"],
        ["위치", "쿼드러처 휠 엔코더 → position_mm / distance_x"],
        ["엣지 처리", "정지 노이즈 임계값 + 10샘플 JSON 배치"],
        ["서버", "Python FastAPI, asyncio Queue, MQTT 구독"],
        ["저장", "InfluxDB + Flux"],
        ["화면 전송", "MQTT QoS 1 업링크 + WebSocket 다운링크"],
        ["신호처리", "sym3 웨이블릿 디노이징, 파고율(Crest Factor) 등 9개 특징"],
        ["AI 모델", "PyTorch RBF 대리 모델 (64 중심, pred_rail_deform)"],
        ["3D 엔진", "Godot (rail_risk 구간 색상, distance_x 위치)"],
        ["웹", "HTML · Vanilla JS · Tailwind 대시보드"],
        ["구동·레일", "JGB37-520 + L298N, 아연도금 강판 레일, 하드보드 축소 모형"],
    ]
    data = [[P(c, "th") for c in stack_rows[0]]]
    for row in stack_rows[1:]:
        data.append([P(row[0], "cell_c"), P(row[1], "cell")])
    ct = Table(data, colWidths=[36 * mm, 138 * mm], repeatRows=1)
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.3, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, 1), (0, -1), PALE),
        ("BACKGROUND", (1, 1), (1, -1), white),
    ]
    for i in range(2, len(data), 2):
        cmds.append(("BACKGROUND", (1, i), (1, i), PALE))
    ct.setStyle(TableStyle(cmds))
    story += [
        KeepTogether(
            [
                P("<b>마. 기술스택</b>", "h3"),
                P("축소 모형에서 좌·우 독립 계측과 실시간 화면 연동이 가능하도록 아래 구성을 사용한다."),
            ]
        ),
        ct,
        Spacer(1, 4 * mm),
    ]

    # II-2 scenario
    story += [
                P("2. 프로젝트 내용", "h2"),
        P("가. 예상 시나리오 (사용자 중심)", "h3"),
        P(
            "별도의 점검 시간을 할당하지 않고, 갠트리 크레인이 레일 위를 주행하는 과정에서 "
            "센서 모듈이 자동으로 데이터를 수집한다. 축소 모형 시연은 같은 흐름을 약 1.4 m급 레일에서 재현한다."
        ),
        styled_table(
            ["단계", "내용"],
            [
                [
                    "1. 간격 계측",
                    "좌·우 GTRIC LR18-08U가 금속 레일과의 간격 변화를 0–10 V 연속값으로 출력한다. "
                    "ADS1115가 분압 후 16 bit로 변환한다. 단차·국부 침하에 따른 거리 변동을 본다.",
                ],
                [
                    "2. 충격·자세",
                    "MPU-6050이 3축 가속도·3축 자이로를 100 Hz로 계측한다. 단차 충격과 좌우 치우침(뒤틀림 모사)의 "
                    "동적 특징을 파고율·RMS로 추출한다.",
                ],
                [
                    "3. 위치 매핑",
                    "로터리 엔코더로 산출한 position_mm을 distance_x(cm)로 바꿔, 어느 레일 몇 cm 구간인지 묶는다.",
                ],
                [
                    "4. 전송",
                    "ESP32-C3가 정지 노이즈를 억제한 10샘플 JSON 배치를 Wi-Fi MQTT QoS 1로 발행한다. "
                    "좌 노드 rail-left-01, 우 노드 rail-right-01.",
                ],
                [
                    "5. 서버 처리",
                    "FastAPI가 스키마 검증 후 32샘플 롤링 윈도우에 sym3 웨이블릿 디노이징을 적용하고 "
                    "9개 특징을 정규화하여 RBF에 입력한다.",
                ],
                [
                    "6. 화면",
                    "InfluxDB에 저장하고 WebSocket으로 방송한다. 웹은 CREST·PRED_RAIL_DEFORM·히트맵을, "
                    "Godot는 크레인 위치와 좌·우 레일 색상을 갱신한다.",
                ],
            ],
            [32 * mm, 142 * mm],
            first_center=True,
        ),
        Spacer(1, 2 * mm),
        P(
            "<b>디지털 트윈 색상.</b> 정상(파랑–초록): 설계 오차 범위 내. 주의(노랑): 미세 충격·간격 변동으로 "
            "정밀 모니터링. 위험(빨강): 한계치를 넘어 해당 구간을 우선 점검. "
            "급격한 파고율 상승 시 해당 위치를 강조한다. 크레인 속도 자동 제어와 관리자 푸시 앱은 "
            "본 기간의 필수 범위가 아니다."
        ),
                P("나. 필요 기자재", "h3"),
        P("축소 모형 시연에 쓰는 구성만 적는다. 상용 3D 자산은 공개 저장소에 올리지 않는다."),
        styled_table(
            ["구분", "품목", "활용계획"],
            [
                [
                    "모형",
                    "하드보드 평판 구조 축소 갠트리, 아연도금 강판 레일, 3D 출력 구동부 외피·브래킷",
                    "약 1.4 m급 분해·재조립 모형. 디지털 상용 모델과 물리 모형을 구분한다.",
                ],
                [
                    "구동",
                    "JGB37-520 기어드 모터, L298N, 구동륜·보조륜, 바퀴 외경 53 mm",
                    "좌·우 주행과 엔코더 위치 원천으로 사용한다.",
                ],
                [
                    "센서",
                    "ESP32-C3 Mini 2대, MPU-6050, ADS1115, GTRIC LR18-08U, 엔코더, 분압 저항",
                    "좌·우 독립 노드. GTRIC는 DC 15–30 V 별도 전원, 0–10 V는 분압 후 ADC.",
                ],
                [
                    "전원·서버",
                    "18650, MT3608, Docker, InfluxDB, Mosquitto, Python",
                    "MCU·모터·유도형 센서 전원을 역할별로 분리하고, 시연 실패 대비 더미 스트리머를 둔다.",
                ],
            ],
            [22 * mm, 78 * mm, 74 * mm],
            first_center=True,
        ),
        Spacer(1, 3 * mm),
                P("다. 성과목표", "h3"),
        bullets(
            [
                "2026. 10. 31.까지 축소 모형에서 좌·우 계측–특징 공학–RBF–웹·Godot 종단 시연을 고정한다.",
                "합성 데이터와 실측 라벨을 구분해 평가하고, 근거 없는 성능 수치를 쓰지 않는다.",
            ]
        ),
        Spacer(1, 4 * mm),
    ]

    # II-3 methods
    story += [
                P("3. 프로젝트 수행방법", "h2"),
        P("가. 프로젝트 추진일정", "h3"),
        P("프로젝트 기간: 2026. 9. 1. ~ 2026. 10. 31. 설계부터 시연 고정까지 이 기간에 완성한다."),
        gantt_table(),
        Spacer(1, 2 * mm),
        styled_table(
            ["단계", "기간", "목표", "완료로 인정하는 증거"],
            [
                [
                    "A. 설계·제작",
                    "2026. 9.",
                    "부품 수급, 회로·펌웨어 설계, 좌·우 센서 모듈과 축소 모형 제작",
                    "회로도, 부품 목록, 펌웨어, 조립 사진",
                ],
                [
                    "B. 주행·라벨·재학습",
                    "2026. 9. 말 ~ 10. 중",
                    "첫 왕복, 교정, 정상·단차·침하·뒤틀림 재현, 실측 RBF 재학습",
                    "수신 로그, 라벨 데이터셋, 학습 로그, 합성과 분리된 평가표",
                ],
                [
                    "C. 시제품·시연 고정",
                    "2026. 10.",
                    "수납·배선 보호, 웹·Godot 종단, 시연 3종 고정",
                    "시연 시나리오 3종, 실물 화면 캡처, 종단 동작 확인",
                ],
            ],
            [28 * mm, 32 * mm, 52 * mm, 62 * mm],
            first_center=True,
        ),
                P("나. 팀원의 세부목표 수립 및 협업", "h3"),
        styled_table(
        ["팀원", "역할", "프로젝트 세부목표"],
        [
            [
                "김정우<br/>(조장)",
                "전체 기획·로드맵<br/>자원·일정 조율<br/>조립·시험",
                "핵심 아이디어 구체화와 일정 관리. 축소 모형 조립, 레일 이상 재현, 반복 주행 절차와 증빙. "
                "시험 조건이 센서 교정·AI 라벨의 기준이 되게 한다.",
            ],
            [
                "배용진",
                "센서 모듈 및<br/>테스트 설계",
                "회로·전원, ESP32-C3 펌웨어, 분압·거리·엔코더 교정, 구동부 수납. "
                "하드웨어 신뢰성 시나리오와 시운전 디버깅. 실측 샘플이 백엔드 계약과 1:1로 맞게 한다.",
            ],
            [
                "배준호",
                "백엔드 개발 및<br/>데이터 처리·AI",
                "FastAPI·InfluxDB·WebSocket, 특징 공학, RBF 재학습·평가, 배포. "
                "데이터 계약을 잠그고 합성/실측을 구분한 평가표를 만든다.",
            ],
            [
                "김병서",
                "프론트엔드<br/>(디지털 트윈)",
                "웹 대시보드와 Godot 3D. distance_x·좌우 레일 색상 매핑, 시연 화면 고정. "
                "현장 담당자가 보는 화면이 성과 검증 창구가 되게 한다.",
            ],
        ],
        [28 * mm, 40 * mm, 106 * mm],
        ),
        Spacer(1, 2 * mm),
        P(
            "융합 접점: 기계×전자(외피 수납·레일 재료와 유도형 출력), 전자×소프트웨어(좌우 MQTT 스키마), "
            "신호처리×AI(9개 특징), AI×시각화(구간 색상), 항만 도메인×전 전공(‘어디를 먼저 볼 것인가’)."
        ),
                P("다. 프로젝트 수행 협업 방안", "h3"),
        bullets(
            [
                "메신저 및 오프라인 미팅으로 일상 소통. 정기 회의 외에도 필요 시 강의실 미팅.",
                "Notion으로 작업 진척·결정 사항을 기록하고, GitHub으로 소프트웨어 이력을 관리한다.",
            ]
        ),
                P("라. 프로젝트 기본원칙 (Ground Rule)", "h3"),
        bullets(
            [
                "합성 데이터·더미 스트리머 결과를 실측 성능처럼 적지 않는다. 완료·미검증·미실시를 섞어 쓰지 않는다.",
                "근거 없는 정확도·사고 예방 효과·회로 확정치를 만들지 않는다. 모르면 확인 필요로 남긴다.",
            ]
        ),
    ]

    # III
    story += [
                section_title("Ⅲ", "기대효과 및 활용분야"),
        P("1. 작품의 활용분야", "h2"),
        P(
            "본 작품은 인증 검측기를 대체하는 제품이 아니라, 기존 육안·정기 점검 앞에 붙는 "
            "1차 스크리닝 계층이다. 크레인이 움직이는 동안 데이터가 쌓이므로, 별도의 전면 운행 중단을 "
            "전제하지 않고도 우선 점검 구간을 좁힐 수 있다."
        ),
        bullets(
                [
                    "항만·조선소 안전·설비 점검: 정기 점검 주기 사이에 커진 단차·침하·뒤틀림 징후를 "
                    "주행 로그로 보완한다. 야간·우천·분진처럼 육안이 약한 조건에서도 다음날 볼 지점을 "
                    "전날에 정리할 수 있다. 좌·우를 나누어 보면 한쪽만 이상인 구간부터 동선을 잡을 수 있다.",
                    "자동화·무인 야드 운영 보조: 무인 크레인일수록 사람이 레일을 매번 걷기 어렵다. "
                    "엔코더 좌표와 구간 색상이 같은 계약으로 웹·3D에 남으면, 원격 사무실과 현장·외주 팀이 "
                    "‘몇 cm 구간을 볼지’를 같은 화면으로 합의할 수 있다.",
                    "교육·시연과 인접 레일 설비: 축소 모형과 대시보드는 계측–추론–시각화의 종단을 가르치는 "
                    "실습 플랫폼이 된다. 같은 관성·간격·위치 결합은 조선소 골리앗, 제철소·물류창고의 "
                    "레일 주행 설비에도 질문을 옮길 수 있다. 철도 본선 검측을 대체한다고 보지 않는다.",
                ]
            ),
                P("2. 작품 개발에 따른 기대효과", "h2"),
        P(
            "점검 담당자에게는 레일 전체를 같은 밀도로 훑는 대신, 위험도가 누적된 구간을 먼저 확인하는 "
            "출발점이 생긴다. 정비 담당자는 웹의 좌·우 파고율·예측값과 히트맵을 현장 도착 전에 공유해 "
            "공구·차단 범위를 해당 구간에 맞출 수 있다. 관제·운전 측은 운행 중 느꼈던 이음을 "
            "이후 화면의 위험 구간과 대조하는 보조 자료로 쓸 수 있다."
        ),
        P(
            "교대 인수인계와 외주 요청에서 구두 위치 설명을 줄이면, 정보 누락과 전 선로 작업 중단을 "
            "피할 여지가 있다. 반복 주행 기록이 쌓이면 일회성 이물질 충격과 지속 기하 이상을 구분하는 "
            "추세 자료로 InfluxDB 시계열을 쓸 수 있다. 이는 사고 예방 효과를 숫자로 단정하는 근거가 아니라, "
            "점검 합의를 빠르게 만드는 효과다."
        ),
        P(
            "팀에게는 기계 모형, 임베디드 계측, 실시간 서버, 신호처리·AI, 3D 디지털 트윈을 한 시연으로 "
            "잇는 다학제 수행 경험이 남는다. 학부 이론 수업만으로는 다루기 어려운 전원·오탐·교정·화면 가독성을 "
            "시제품 제약으로 맞닥뜨리게 된다. 사고 감소율·점검 시간 단축분·유지보수 비용 절감액은 "
            "현장 실증 후 평가한다."
        ),
                P("3. 시연으로 확인하는 것", "h2"),
        P(
            "10월 말 시연은 실제 항만 레일 예측이 아니라, 재현한 결함을 위치와 함께 보여주는지를 확인한다."
        ),
        styled_table(
            ["순서", "장면", "확인하는 것"],
            [
                ["1", "정상 구간 왕복", "좌·우 노드가 동시에 올라오고, 화면 위치가 모형과 같이 움직인다."],
                ["2", "단차 재현 구간 통과", "파고율과 예측값이 오르고, 해당 구간이 노랑·빨강으로 남는다."],
                ["3", "좌우 치우침 모사", "한쪽 레일만 위험도가 쌓여 좌·우 독립 계측의 의미가 드러난다."],
                ["4", "대시보드 인수인계", "원격 화면만 보고 ‘몇 cm 구간을 볼지’를 말할 수 있다."],
                [
                    "5",
                    "한계 한 장",
                    "축소 모형에서 재현한 결함의 탐지·위험도 추정임을 명시하고, "
                    "실제 항만 레일 예측·인증 계측 대체가 아님을 밝힌다.",
                ],
            ],
            [16 * mm, 42 * mm, 116 * mm],
            first_center=True,
        ),
        Spacer(1, 3 * mm),
                P("4. 위험 요인 및 대응", "h2"),
        styled_table(
        ["위험", "영향", "대응"],
        [
            [
                "실물 교정 지연",
                "재학습·시연이 더미에 머문다",
                "9월에 한쪽 노드 로그라도 먼저 확보한다.",
            ],
            [
                "재현이 현장과 다름",
                "시연이 모형으로만 읽힌다",
                "증명 범위를 ‘재현한 결함을 이 파이프라인이 그 위치에서 잡는가’로 한정한다.",
            ],
            [
                "오탐",
                "신뢰가 떨어진다",
                "자동 알림을 하지 않고 우선 점검 제시에 한정한다.",
            ],
        ],
        [38 * mm, 48 * mm, 88 * mm],
        ),
    ]
    return story


def build():
    doc = BaseDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title="2026학년도 기업 연계 부산공유대학 다학제 융합 프로젝트 수행계획서",
        author="다학제 융합 프로젝트 팀",
        subject="갠트리 크레인 하부 주행 레일 변형 디지털 트윈 안전관리 시스템 수행계획서",
    )
    cover_top = Frame(
        18 * mm, A4[1] - 78 * mm, 174 * mm, 56 * mm, id="cover_top", showBoundary=0
    )
    cover_rest = Frame(
        18 * mm, 28 * mm, 174 * mm, A4[1] - 78 * mm - 22 * mm, id="cover_rest", showBoundary=0
    )
    body = Frame(
        18 * mm, 16 * mm, 174 * mm, A4[1] - 32 * mm, id="body", showBoundary=0
    )
    doc.addPageTemplates(
        [
            PageTemplate(id="cover", frames=[cover_top, cover_rest], onPage=cover_page),
            PageTemplate(id="body", frames=[body], onPage=header_footer),
        ]
    )
    story = cover_flow() + [NextPageTemplate("body"), PageBreak()] + body_flow()
    doc.build(story)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    build()
