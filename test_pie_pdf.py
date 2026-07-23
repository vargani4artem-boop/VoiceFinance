import os
import sqlite3
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.legends import Legend

CYR_FONT = 'Helvetica'
font_candidates = [
    'C:/Windows/Fonts/arial.ttf',
    'C:/Windows/Fonts/segoeui.ttf',
    'C:/Windows/Fonts/calibri.ttf'
]
for font_path in font_candidates:
    if os.path.exists(font_path):
        try:
            pdfmetrics.registerFont(TTFont('CyrillicFont', font_path))
            CYR_FONT = 'CyrillicFont'
            break
        except Exception:
            pass

DB_FILE = os.path.join(os.path.dirname(__file__), "finance.db")

def get_analytics():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT type, SUM(amount) FROM transactions GROUP BY type")
    rows = dict(cursor.fetchall())
    
    cursor.execute("SELECT category, SUM(amount) as total FROM transactions WHERE type='expense' GROUP BY category ORDER BY total DESC")
    cat_rows = cursor.fetchall()
    conn.close()
    
    income = rows.get('income', 0.0) or 0.0
    expense = rows.get('expense', 0.0) or 0.0
    balance = income - expense
    return income, expense, balance, cat_rows

def generate_pdf_report_with_pie(filename="voicefinance_report_pie.pdf"):
    income, expense, balance, cat_rows = get_analytics()
    ratio = round(income / expense, 2) if expense > 0 else (income if income > 0 else 0)

    doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleStyle', fontName=CYR_FONT, fontSize=18, leading=22, textColor=colors.HexColor('#6366F1'))
    heading_style = ParagraphStyle('HeadStyle', fontName=CYR_FONT, fontSize=13, leading=16, textColor=colors.HexColor('#1E293B'))
    meta_style = ParagraphStyle('MetaStyle', fontName=CYR_FONT, fontSize=9, textColor=colors.HexColor('#64748B'))
    cell_style = ParagraphStyle('CellStyle', fontName=CYR_FONT, fontSize=9, leading=11, textColor=colors.HexColor('#1E293B'))
    cell_header_style = ParagraphStyle('CellHeadStyle', fontName=CYR_FONT, fontSize=9, leading=11, textColor=colors.white)

    story = []
    story.append(Paragraph("<b>VoiceFinance AI — Анализ Расходов и Диаграмма</b>", title_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"Дата формирования: {datetime.now().strftime('%Y-%m-%d %H:%M')}", meta_style))
    story.append(Spacer(1, 15))

    # Summary Table
    summary_data = [
        [
            Paragraph("<b>Общий Доход</b>", cell_style),
            Paragraph("<b>Общий Расход</b>", cell_style),
            Paragraph("<b>Чистый Баланс</b>", cell_style),
            Paragraph("<b>Коэффициент</b>", cell_style)
        ],
        [
            Paragraph(f"<b>${income:,.2f}</b>", cell_style),
            Paragraph(f"<b>${expense:,.2f}</b>", cell_style),
            Paragraph(f"<b>${balance:,.2f}</b>", cell_style),
            Paragraph(f"<b>{ratio}x</b>", cell_style)
        ]
    ]
    sum_table = Table(summary_data, colWidths=[130, 130, 130, 130])
    sum_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F1F5F9')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#CBD5E1')),
    ]))
    story.append(sum_table)
    story.append(Spacer(1, 15))

    # Pie Chart Section
    story.append(Paragraph("<b>Распределение расходов по категориям (%):</b>", heading_style))
    story.append(Spacer(1, 8))

    if cat_rows and expense > 0:
        d = Drawing(400, 180)
        pc = Pie()
        pc.x = 20
        pc.y = 15
        pc.width = 150
        pc.height = 150
        pc.data = [amt for cat, amt in cat_rows]
        pc.labels = [f"{round((amt/expense)*100, 1)}%" for cat, amt in cat_rows]
        
        # Color palette
        palette = [
            colors.HexColor('#6366F1'), colors.HexColor('#EC4899'),
            colors.HexColor('#10B981'), colors.HexColor('#F59E0B'),
            colors.HexColor('#3B82F6'), colors.HexColor('#8B5CF6')
        ]
        for i in range(len(cat_rows)):
            pc.slices[i].fillColor = palette[i % len(palette)]
            pc.slices[i].strokeColor = colors.white
            pc.slices[i].strokeWidth = 1.5

        d.add(pc)

        # Legend
        leg = Legend()
        leg.x = 200
        leg.y = 140
        leg.dx = 10
        leg.dy = 10
        leg.fontName = CYR_FONT
        leg.fontSize = 9
        leg.boxAnchor = 'nw'
        leg.colorNamePairs = [(palette[i % len(palette)], f"{cat_rows[i][0]}: ${cat_rows[i][1]} ({round((cat_rows[i][1]/expense)*100, 1)}%)") for i in range(len(cat_rows))]
        d.add(leg)

        story.append(d)
        story.append(Spacer(1, 15))

    # Detailed Category Table
    story.append(Paragraph("<b>Детализация по категориям:</b>", heading_style))
    story.append(Spacer(1, 8))

    cat_table_data = [[
        Paragraph("<b>Категория</b>", cell_header_style),
        Paragraph("<b>Сумма</b>", cell_header_style),
        Paragraph("<b>Доля от общих расходов</b>", cell_header_style)
    ]]

    for cat, amt in cat_rows:
        pct = round((amt / expense) * 100, 1) if expense > 0 else 0
        cat_table_data.append([
            Paragraph(str(cat), cell_style),
            Paragraph(f"${amt:,.2f}", cell_style),
            Paragraph(f"<b>{pct}%</b> от ${expense:,.2f}", cell_style)
        ])

    cat_table = Table(cat_table_data, colWidths=[150, 150, 220])
    cat_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6366F1')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
    ]))
    story.append(cat_table)

    doc.build(story)
    return filename

if __name__ == '__main__':
    generate_pdf_report_with_pie()
    print("Pie chart PDF generated successfully!")
