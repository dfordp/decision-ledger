from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from io import BytesIO
from datetime import datetime

def generate_tender_pdf(tender, requirements):
    """Generate a professional PDF from tender data"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, 
                           topMargin=0.75*inch, bottomMargin=0.75*inch)
    
    story = []
    styles = getSampleStyleSheet()
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1e3a8a'),
        spaceAfter=30,
        alignment=TA_CENTER
    )
    
    story.append(Paragraph(f"TENDER DOCUMENT", title_style))
    story.append(Paragraph(tender['name'], styles['Heading2']))
    story.append(Spacer(1, 0.3*inch))
    
    # Tender Info
    info_data = [
        ['Tender ID:', str(tender['id'])],
        ['Domain:', tender['domain']],
        ['Year:', str(tender['year'])],
        ['Status:', 'Open for Submission'],
    ]
    
    info_table = Table(info_data, colWidths=[2*inch, 4*inch])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f1f5f9')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0'))
    ]))
    
    story.append(info_table)
    story.append(Spacer(1, 0.5*inch))
    
    # Requirements
    story.append(Paragraph("TECHNICAL REQUIREMENTS", styles['Heading2']))
    story.append(Spacer(1, 0.2*inch))
    
    req_data = [['#', 'Requirement', 'Value', 'Unit', 'Type']]
    
    for idx, req in enumerate(requirements, 1):
        req_data.append([
            str(idx),
            req['dimension_name'],
            f"{float(req['required_value']):.2f}",
            req['dimension_unit'],
            req['strictness'].upper()
        ])
    
    req_table = Table(req_data, colWidths=[0.4*inch, 2.5*inch, 1*inch, 1*inch, 1*inch])
    req_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a8a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')])
    ]))
    
    story.append(req_table)
    
    doc.build(story)
    buffer.seek(0)
    return buffer