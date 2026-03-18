"""
PDF Generation for FMEA (Failure Mode and Effects Analysis) Reports.
Generates professional FMEA worksheets, summaries, and analysis documents.
"""

from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from io import BytesIO
from datetime import datetime
from typing import List, Dict, Any, Optional

def generate_fmea_report_pdf(
    fmea: Dict[str, Any],
    product_system: Dict[str, Any],
    fmea_table: List[Dict[str, Any]],
    team_leads: Optional[List[Dict[str, Any]]] = None
) -> BytesIO:
    """
    Generate comprehensive FMEA analysis report PDF.
    Includes executive summary, FMEA worksheet, statistics, and recommendations.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        topMargin=0.5*inch,
        bottomMargin=0.5*inch,
        leftMargin=0.5*inch,
        rightMargin=0.5*inch
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    # ====== TITLE PAGE ======
    title_style = ParagraphStyle(
        'ReportTitle',
        parent=styles['Heading1'],
        fontSize=28,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    subtitle_style = ParagraphStyle(
        'ReportSubtitle',
        parent=styles['Normal'],
        fontSize=14,
        textColor=colors.HexColor('#7f8c8d'),
        spaceAfter=20,
        alignment=TA_CENTER
    )
    
    story.append(Paragraph("FAILURE MODE AND EFFECTS ANALYSIS", title_style))
    story.append(Paragraph("FMEA Report", subtitle_style))
    story.append(Spacer(1, 0.3*inch))
    
    # ====== PROJECT INFORMATION ======
    header_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=10,
        fontName='Helvetica-Bold',
        borderPadding=5,
        backColor=colors.HexColor('#ecf0f1')
    )
    
    story.append(Paragraph("PROJECT INFORMATION", header_style))
    
    # Project info table
    project_data = [
        ['Project Name:', fmea.get('project_name', 'Untitled FMEA')],
        ['System Function:', product_system.get('system_function', 'N/A')],
        ['Domain:', product_system.get('domain', 'N/A')],
        ['Scope:', fmea.get('description', 'Comprehensive failure analysis')],
        ['Prepared Date:', datetime.now().strftime('%Y-%m-%d')],
        ['Status:', fmea.get('status', 'in_progress').upper()],
        ['FMEA ID:', str(fmea.get('id', 'N/A'))],
        ['Product System ID:', str(product_system.get('id', 'N/A'))],
    ]
    
    project_table = Table(project_data, colWidths=[1.8*inch, 7*inch])
    project_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#ecf0f1')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')])
    ]))
    
    story.append(project_table)
    story.append(Spacer(1, 0.4*inch))
    
    # ====== EXECUTIVE SUMMARY ======
    story.append(PageBreak())
    story.append(Paragraph("EXECUTIVE SUMMARY", header_style))
    
    # Count statistics
    total_modes = len(fmea_table)
    high_risk = sum(1 for item in fmea_table if item.get('risk_score', {}).get('rpn', 0) > 100)
    total_actions = sum(len(item.get('actions', [])) for item in fmea_table)
    
    summary_style = ParagraphStyle(
        'Summary',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=6,
        alignment=TA_LEFT
    )
    
    story.append(Paragraph(
        f"<b>Analysis Overview:</b> This FMEA identified {total_modes} potential failure modes. "
        f"Of these, {high_risk} items ({100*high_risk//max(1,total_modes)}%) require mitigation action. "
        f"{total_actions} corrective/preventive actions have been assigned.",
        summary_style
    ))
    story.append(Spacer(1, 0.2*inch))
    
    # Statistics table
    stats_data = [
        ['Metric', 'Value', 'Status'],
        ['Total Failure Modes', str(total_modes), '✓'],
        ['High Priority (RPN > 100)', str(high_risk), '⚠️' if high_risk > 0 else '✓'],
        ['Mitigation Actions', str(total_actions), '✓'],
    ]
    
    stats_table = Table(stats_data, colWidths=[3*inch, 2*inch, 1.5*inch])
    stats_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#95a5a6')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#ecf0f1'), colors.white])
    ]))
    
    story.append(stats_table)
    story.append(Spacer(1, 0.4*inch))
    
    # ====== FMEA WORKSHEET ======
    story.append(PageBreak())
    story.append(Paragraph("FMEA WORKSHEET", header_style))
    
    # Build FMEA table
    fmea_data = [[
        'Item', 'Function', 'Failure Mode', 'Failure Cause',
        'Controls', 'S', 'O', 'D', 'RPN', 'Actions'
    ]]
    
    for idx, item in enumerate(fmea_table[:20], 1):  # First 20 items per page
        mode = item.get('failure_mode', {})
        cause = item.get('failure_cause', {})
        risk = item.get('risk_score', {})
        controls = item.get('controls', [])
        actions = item.get('actions', [])
        
        mode_text = str(mode.get('description', 'N/A'))[:40]
        cause_text = str(cause.get('cause_description', 'N/A'))[:30]
        control_text = controls[0].get('control_description', 'None')[:25] if controls else 'None'
        
        rpn = risk.get('rpn', 0)
        rpn_str = str(rpn) if rpn else '-'
        rpn_color = '#e74c3c' if rpn and rpn > 100 else '#2c3e50'
        
        fmea_data.append([
            str(idx),
            'System' if idx == 1 else '',
            mode_text,
            cause_text,
            control_text,
            str(risk.get('severity', '-')),
            str(risk.get('occurrence', '-')),
            str(risk.get('detection', '-')),
            rpn_str,
            str(len(actions))
        ])
    
    fmea_worksheet = Table(fmea_data, colWidths=[0.35*inch, 0.6*inch, 1.2*inch, 1.1*inch, 1*inch, 0.4*inch, 0.4*inch, 0.4*inch, 0.5*inch, 0.5*inch])
    fmea_worksheet.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('PADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    
    story.append(fmea_worksheet)
    story.append(Spacer(1, 0.3*inch))
    
    if total_modes > 20:
        story.append(Paragraph(
            f"<i>Table shows first 20 items. Full report contains {total_modes} total failure modes.</i>",
            ParagraphStyle('Note', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#7f8c8d'))
        ))
    
    story.append(Spacer(1, 0.4*inch))
    
    # ====== RECOMMENDATIONS ======
    story.append(PageBreak())
    story.append(Paragraph("RECOMMENDED ACTIONS", header_style))
    
    high_risk_items = [item for item in fmea_table if item.get('risk_score', {}).get('rpn', 0) > 100]
    
    if high_risk_items:
        actions_list = []
        for idx, item in enumerate(high_risk_items[:10], 1):
            mode = item.get('failure_mode', {})
            cause = item.get('failure_cause', {})
            risk = item.get('risk_score', {})
            rpn = risk.get('rpn', 0)
            
            action_text = (
                f"{idx}. <b>{mode.get('description', 'Unknown')}:</b> "
                f"Caused by {cause.get('cause_description', 'unknown cause')}. "
                f"RPN={rpn} - Requires immediate attention."
            )
            actions_list.append(Paragraph(action_text, summary_style))
            actions_list.append(Spacer(1, 0.1*inch))
        
        story.extend(actions_list)
        
        if len(high_risk_items) > 10:
            story.append(Paragraph(
                f"<i>...and {len(high_risk_items) - 10} additional high-risk items.</i>",
                summary_style
            ))
    else:
        story.append(Paragraph(
            "✓ No high-priority items identified. System appears well-controlled.",
            ParagraphStyle('Success', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#27ae60'))
        ))
    
    story.append(Spacer(1, 0.4*inch))
    
    # ====== SIGN-OFF PAGE ======
    story.append(PageBreak())
    story.append(Paragraph("APPROVAL & SIGN-OFF", header_style))
    story.append(Spacer(1, 0.3*inch))
    
    # Approval table
    approval_data = [
        ['Role', 'Name', 'Signature', 'Date'],
        ['FMEA Lead', '', '________________', '________________'],
        ['Quality Manager', '', '________________', '________________'],
        ['Engineering Lead', '', '________________', '________________'],
    ]
    
    if team_leads:
        for idx, lead in enumerate(team_leads[:3]):
            approval_data[idx+1][1] = lead.get('name', '')
    
    approval_table = Table(approval_data, colWidths=[2*inch, 2.5*inch, 2*inch, 2*inch])
    approval_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('PADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#95a5a6')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white])
    ]))
    
    story.append(approval_table)
    story.append(Spacer(1, 0.5*inch))
    
    # Footer
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor('#95a5a6'),
        alignment=TA_CENTER
    )
    
    story.append(Paragraph(
        f"<i>Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')} | FMEA Application v1.0</i>",
        footer_style
    ))
    
    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer


def generate_fmea_summary_pdf(
    fmea: Dict[str, Any],
    product_system: Dict[str, Any],
    fmea_table: List[Dict[str, Any]]
) -> BytesIO:
    """
    Generate quick 1-2 page FMEA summary report.
    Includes key metrics and high-priority items only.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=12,
        fontName='Helvetica-Bold'
    )
    
    header_style = ParagraphStyle(
        'Header',
        parent=styles['Heading2'],
        fontSize=11,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=6,
        fontName='Helvetica-Bold',
        borderPadding=4,
        backColor=colors.HexColor('#ecf0f1')
    )
    
    # Title
    story.append(Paragraph(f"FMEA Summary: {fmea.get('project_name', 'Analysis')}", title_style))
    story.append(Spacer(1, 0.15*inch))
    
    # Project info
    story.append(Paragraph("PROJECT", header_style))
    info_data = [
        ['System Function:', product_system.get('system_function', 'N/A')],
        ['Domain:', product_system.get('domain', 'N/A')],
        ['Prepared:', datetime.now().strftime('%B %d, %Y')],
    ]
    
    info_table = Table(info_data, colWidths=[2*inch, 4*inch])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
    ]))
    
    story.append(info_table)
    story.append(Spacer(1, 0.2*inch))
    
    # Statistics
    total_modes = len(fmea_table)
    high_risk = sum(1 for item in fmea_table if item.get('risk_score', {}).get('rpn', 0) > 100)
    total_actions = sum(len(item.get('actions', [])) for item in fmea_table)
    
    story.append(Paragraph("KEY METRICS", header_style))
    
    metrics_data = [
        ['Metric', 'Value'],
        ['Total Failure Modes', str(total_modes)],
        ['High Priority Items (RPN > 100)', str(high_risk)],
        ['Mitigation Actions Assigned', str(total_actions)],
    ]
    
    metrics_table = Table(metrics_data, colWidths=[3*inch, 2*inch])
    metrics_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f8f8f8'), colors.white])
    ]))
    
    story.append(metrics_table)
    story.append(Spacer(1, 0.2*inch))
    
    # High priority items
    if high_risk > 0:
        story.append(Paragraph("HIGH PRIORITY ITEMS (RPN > 100)", header_style))
        
        high_items = sorted(
            [item for item in fmea_table if item.get('risk_score', {}).get('rpn', 0) > 100],
            key=lambda x: x.get('risk_score', {}).get('rpn', 0),
            reverse=True
        )[:5]
        
        for idx, item in enumerate(high_items, 1):
            mode = item.get('failure_mode', {})
            risk = item.get('risk_score', {})
            rpn = risk.get('rpn', 0)
            
            story.append(Paragraph(
                f"<b>{idx}. {mode.get('description', 'Unknown')}</b> (RPN={rpn}) - Requires action",
                styles['Normal']
            ))
    
    story.append(Spacer(1, 0.3*inch))
    
    # Footer
    story.append(Paragraph(
        f"<i>Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>",
        ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, textColor=colors.grey, alignment=TA_CENTER)
    ))
    
    doc.build(story)
    buffer.seek(0)
    return buffer


def generate_risk_matrix_pdf(fmea_table: List[Dict[str, Any]]) -> BytesIO:
    """
    Generate risk matrix visualization showing S/O/D distribution.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    story.append(Paragraph("RISK MATRIX", styles['Heading1']))
    story.append(Spacer(1, 0.2*inch))
    
    # Create risk matrix 10x10
    matrix = [[0]*10 for _ in range(10)]
    
    for item in fmea_table:
        risk = item.get('risk_score', {})
        s = int(risk.get('severity', 5)) - 1
        o = int(risk.get('occurrence', 5)) - 1
        
        if 0 <= s < 10 and 0 <= o < 10:
            matrix[s][o] += 1
    
    # Build table for risk matrix
    matrix_data = [['S\\O'] + [str(i+1) for i in range(10)]]
    
    for s in range(9, -1, -1):
        row = [str(s+1)]
        for o in range(10):
            count = matrix[s][o]
            row.append(str(count) if count > 0 else '')
        matrix_data.append(row)
    
    matrix_table = Table(matrix_data, colWidths=[0.5*inch] * 11)
    
    # Color-code cells
    style_commands = [
        ('BACKGROUND', (0, 0), (10, 10), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ]
    
    # Background colors based on RPN ranges
    for s in range(10):
        for o in range(10):
            rpn = (10 - s) * (o + 1)
            if rpn > 100:
                bg_color = colors.HexColor('#f8d7da')  # Red
            elif rpn > 50:
                bg_color = colors.HexColor('#fff3cd')  # Yellow
            else:
                bg_color = colors.HexColor('#d4edda')  # Green
            
            style_commands.append(
                ('BACKGROUND', (s+1, 10-o), (s+1, 10-o), bg_color)
            )
    
    matrix_table.setStyle(TableStyle(style_commands))
    story.append(matrix_table)
    
    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph("Legend:", styles['Normal']))
    story.append(Paragraph("🟢 Low Risk (RPN ≤ 50)", ParagraphStyle('Legend', parent=styles['Normal'], textColor=colors.HexColor('#155724'))))
    story.append(Paragraph("🟡 Medium Risk (RPN 51-100)", ParagraphStyle('Legend', parent=styles['Normal'], textColor=colors.HexColor('#856404'))))
    story.append(Paragraph("🔴 High Risk (RPN > 100)", ParagraphStyle('Legend', parent=styles['Normal'], textColor=colors.HexColor('#721c24'))))
    
    doc.build(story)
    buffer.seek(0)
    return buffer