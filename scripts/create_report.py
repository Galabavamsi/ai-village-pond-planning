from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image as RLImage,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "AI_Village_Pond_Planning_Phase_2_Report.pdf"

NAVY = colors.HexColor("#12304A")
TEAL = colors.HexColor("#087E8B")
MINT = colors.HexColor("#DFF3F2")
PALE = colors.HexColor("#F4F8FA")
GOLD = colors.HexColor("#E5A93D")
INK = colors.HexColor("#1F2933")
MUTED = colors.HexColor("#52606D")
LINE = colors.HexColor("#D9E2EC")


def register_fonts() -> tuple[str, str]:
    candidates = [
        ("Aptos", r"C:\Windows\Fonts\aptos.ttf", r"C:\Windows\Fonts\aptosbd.ttf"),
        ("Arial", r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
    ]
    for name, regular, bold in candidates:
        if Path(regular).exists() and Path(bold).exists():
            pdfmetrics.registerFont(TTFont(name, regular))
            pdfmetrics.registerFont(TTFont(name + "-Bold", bold))
            return name, name + "-Bold"
    return "Helvetica", "Helvetica-Bold"


FONT, BOLD = register_fonts()


def P(text: str, style: ParagraphStyle):
    return Paragraph(text, style)


styles = getSampleStyleSheet()
styles.add(ParagraphStyle("CoverKicker", fontName=BOLD, fontSize=10, leading=13, textColor=TEAL, spaceAfter=8, tracking=1.5))
styles.add(ParagraphStyle("CoverTitle", fontName=BOLD, fontSize=30, leading=34, textColor=NAVY, spaceAfter=12))
styles.add(ParagraphStyle("CoverSub", fontName=FONT, fontSize=13, leading=19, textColor=MUTED, spaceAfter=18))
styles.add(ParagraphStyle("H1Custom", fontName=BOLD, fontSize=19, leading=23, textColor=NAVY, spaceBefore=5, spaceAfter=10))
styles.add(ParagraphStyle("H2Custom", fontName=BOLD, fontSize=12.5, leading=16, textColor=TEAL, spaceBefore=11, spaceAfter=6))
styles.add(ParagraphStyle("BodyCustom", fontName=FONT, fontSize=9.5, leading=14, textColor=INK, spaceAfter=7))
styles.add(ParagraphStyle("SmallCustom", fontName=FONT, fontSize=8, leading=11, textColor=MUTED, spaceAfter=5))
styles.add(ParagraphStyle("TinyCustom", fontName=FONT, fontSize=7, leading=9, textColor=MUTED))
styles.add(ParagraphStyle("TableHead", fontName=BOLD, fontSize=8, leading=10, textColor=colors.white))
styles.add(ParagraphStyle("TableBody", fontName=FONT, fontSize=8, leading=10.5, textColor=INK))
styles.add(ParagraphStyle("CodeCustom", fontName="Courier", fontSize=7.3, leading=10, textColor=colors.HexColor("#E6EDF3"), leftIndent=6, rightIndent=6, spaceBefore=3, spaceAfter=3))
styles.add(ParagraphStyle("Callout", fontName=FONT, fontSize=9, leading=13, textColor=NAVY, leftIndent=10, rightIndent=10, spaceBefore=7, spaceAfter=7))
styles.add(ParagraphStyle("Footer", fontName=FONT, fontSize=7.5, textColor=MUTED))


def footer(c: canvas.Canvas, doc):
    c.saveState()
    width, _ = A4
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    c.line(18 * mm, 14 * mm, width - 18 * mm, 14 * mm)
    c.setFont(FONT, 7.5)
    c.setFillColor(MUTED)
    c.drawString(18 * mm, 9 * mm, "AI Village Pond Planning | Phase 2 Technical Report")
    c.drawRightString(width - 18 * mm, 9 * mm, f"Page {doc.page}")
    c.restoreState()


def cover_footer(c: canvas.Canvas, doc):
    c.saveState()
    width, _ = A4
    c.setStrokeColor(MINT)
    c.setLineWidth(1)
    c.line(24 * mm, 24 * mm, width - 24 * mm, 24 * mm)
    c.setFont(FONT, 8)
    c.setFillColor(MUTED)
    c.drawString(24 * mm, 17 * mm, "Prepared for Phase 2 submission")
    c.drawRightString(width - 24 * mm, 17 * mm, "01 September 2026")
    c.restoreState()


def section(title: str):
    return [Paragraph(title, styles["H1Custom"]), HRFlowable(width="100%", thickness=1.2, color=TEAL, spaceAfter=10)]


def table(data, widths, header=True, row_heights=None):
    t = Table(data, colWidths=widths, rowHeights=row_heights, repeatRows=1 if header else 0, hAlign="LEFT")
    command = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
    ]
    if header:
        command.extend([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)])
        if len(data) > 1:
            command.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]))
    t.setStyle(TableStyle(command))
    return t


def code_block(text: str):
    t = Table([[Paragraph(text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>"), styles["CodeCustom"])]], colWidths=[174 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1E293B")), ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#334155")), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def callout(text: str):
    t = Table([[Paragraph(text, styles["Callout"])]], colWidths=[174 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), MINT), ("BOX", (0, 0), (-1, -1), 0.6, TEAL), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7)]))
    return t


def visual_figure(filename: str, caption: str, max_height=145 * mm):
    path = ROOT / "output" / "screenshots" / filename
    reader = ImageReader(str(path))
    source_width, source_height = reader.getSize()
    width = 174 * mm
    height = width * source_height / source_width
    if height > max_height:
        height = max_height
        width = height * source_width / source_height
    return [
        RLImage(str(path), width=width, height=height),
        Paragraph(caption, styles["SmallCustom"]),
        Spacer(1, 3 * mm),
    ]


def architecture_diagram():
    rows = [
        [P("1. Upload", styles["TableHead"]), P("2. Parse", styles["TableHead"]), P("3. Analyze", styles["TableHead"]), P("4. Return", styles["TableHead"])],
        [P("KML / KMZ file", styles["TableBody"]), P("Contour geometry<br/>+ elevations", styles["TableBody"]), P("Metric grid<br/>+ D8 flow", styles["TableBody"]), P("JSON + GeoJSON<br/>recommendations", styles["TableBody"])],
    ]
    t = Table(rows, colWidths=[43.5 * mm] * 4, rowHeights=[10 * mm, 18 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), TEAL), ("BACKGROUND", (0, 1), (-1, 1), PALE), ("BOX", (0, 0), (-1, -1), 0.7, TEAL), ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
    return t


def build_story():
    story = []

    # Cover
    story.extend([Spacer(1, 35 * mm), Paragraph("PHASE 2 | TECHNICAL REPORT", styles["CoverKicker"]), Paragraph("AI-based Village Pond Planning System", styles["CoverTitle"]), Paragraph("Contour-map backend API for terrain-derived pond-site and catchment estimation", styles["CoverSub"]), Spacer(1, 9 * mm)])
    cover_table = Table([
        [P("SUBMISSION STATUS", styles["SmallCustom"]), P("LOCAL VALIDATION", styles["SmallCustom"])],
        [P("Backend implementation complete", styles["H2Custom"]), P("4 automated tests passed", styles["H2Custom"])],
        [P("KML and KMZ upload support", styles["SmallCustom"]), P("Sample map analyzed successfully", styles["SmallCustom"])],
    ], colWidths=[83 * mm, 83 * mm])
    cover_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PALE), ("BOX", (0, 0), (-1, -1), 0.8, LINE), ("LINEBEFORE", (1, 0), (1, -1), 0.8, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story.extend([cover_table, Spacer(1, 22 * mm), Paragraph("Repository URL", styles["SmallCustom"]), Paragraph("[GitHub repository URL - add after repository creation]", styles["BodyCustom"]), Paragraph("Working API URL", styles["SmallCustom"]), Paragraph("Local: http://127.0.0.1:8000/analyzeContour", styles["BodyCustom"]), Paragraph("Public: [deployed API URL - add after remote deployment]", styles["BodyCustom"]), PageBreak()])

    # Executive summary
    story.extend(section("1. Executive summary"))
    story.append(Paragraph("This phase delivers a backend API that accepts a contour map in KML or KMZ format and derives terrain-based pond planning information. The service parses contour elevations, builds a local metric elevation grid, routes surface flow using D8 downhill routing, and returns ranked pond candidates with catchment area and GeoJSON geometries.", styles["BodyCustom"]))
    story.append(callout("The implementation is generalized: no sample-specific coordinates, locations, or result values are embedded in the code. The supplied contour map is used only as a test input."))
    story.append(Spacer(1, 5 * mm))
    story.extend([Paragraph("Phase 2 objectives", styles["H2Custom"]), architecture_diagram(), Spacer(1, 4 * mm)])
    story.append(Paragraph("The API is intentionally structured as an independent analysis service so later phases can add rainfall, government-land availability, soil, satellite imagery, and a frontend map without replacing the core route.", styles["BodyCustom"]))

    # Requirements
    story.extend(section("2. Requirements traceability"))
    req_rows = [[P("Requirement", styles["TableHead"]), P("Implementation evidence", styles["TableHead"]), P("Status", styles["TableHead"])],
                [P("Backend route", styles["TableBody"]), P("<b>POST /analyzeContour</b>; compatibility alias <b>/findCatchment</b>.", styles["TableBody"]), P("Complete", styles["TableBody"])],
                [P("Upload contour map", styles["TableBody"]), P("Multipart upload field <b>file</b>; supports .kml and .kmz.", styles["TableBody"]), P("Complete", styles["TableBody"])],
                [P("Analyze terrain", styles["TableBody"]), P("Contour parsing, interpolation to an elevation grid, and D8 flow routing.", styles["TableBody"]), P("Complete", styles["TableBody"])],
                [P("Identify pond region", styles["TableBody"]), P("Ranks interior cells with high terrain-derived contributing flow and returns a pond footprint.", styles["TableBody"]), P("Complete", styles["TableBody"])],
                [P("Estimate catchment", styles["TableBody"]), P("Upstream contributing cells are merged into a GeoJSON Polygon or MultiPolygon with area metrics.", styles["TableBody"]), P("Complete", styles["TableBody"])],
                [P("No hard-coding", styles["TableBody"]), P("Coordinates and recommendations are calculated from each uploaded input.", styles["TableBody"]), P("Complete", styles["TableBody"])],
                [P("Documentation/demo", styles["TableBody"]), P("README, this report, OpenAPI docs, automated tests, and sample-map results.", styles["TableBody"]), P("Complete", styles["TableBody"])]]
    story.append(table(req_rows, [43 * mm, 102 * mm, 29 * mm]))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("The public GitHub and deployed API fields on the cover must be filled after the remote repository and hosting setup are completed.", styles["SmallCustom"]))

    # Methodology
    story.extend(section("3. Catchment estimation methodology"))
    steps = [[P("Step", styles["TableHead"]), P("Operation", styles["TableHead"]), P("Output", styles["TableHead"])],
             [P("1", styles["TableBody"]), P("Parse KML/KMZ", styles["TableBody"]), P("Contour lines and elevation values", styles["TableBody"])],
             [P("2", styles["TableBody"]), P("Convert coordinates", styles["TableBody"]), P("Local equirectangular metre-based coordinates", styles["TableBody"])],
             [P("3", styles["TableBody"]), P("Interpolate terrain", styles["TableBody"]), P("Regular elevation grid", styles["TableBody"])],
             [P("4", styles["TableBody"]), P("Route flow", styles["TableBody"]), P("Each cell flows to its steepest lower neighbour", styles["TableBody"])],
             [P("5", styles["TableBody"]), P("Accumulate area", styles["TableBody"]), P("Upstream cell count and square-metre area", styles["TableBody"])],
             [P("6", styles["TableBody"]), P("Rank candidates", styles["TableBody"]), P("Interior high-contributing pond regions", styles["TableBody"])],
             [P("7", styles["TableBody"]), P("Export geometry", styles["TableBody"]), P("WGS84 GeoJSON location, pond region, and catchment", styles["TableBody"])]]
    story.append(table(steps, [17 * mm, 55 * mm, 102 * mm]))
    story.extend([Spacer(1, 4 * mm), Paragraph("Coordinate handling", styles["H2Custom"]), Paragraph("Input coordinates are assumed to be standard WGS84 longitude/latitude as normally stored in KML. The analysis temporarily uses a local equirectangular approximation centered on the input extent so cell areas and flow distances are measured in metres. Returned geometries are converted back to WGS84 GeoJSON for direct map rendering.", styles["BodyCustom"]), Paragraph("Design rationale", styles["H2Custom"]), Paragraph("A D8 flow model is transparent, reproducible, and extensible for this phase. It gives the frontend a meaningful catchment boundary while keeping later additions independent: rainfall can become a runoff-weighting layer, land ownership can become a constraint mask, and detailed hydrology can replace or refine the routing engine.", styles["BodyCustom"]), PageBreak()])

    # API
    story.extend(section("4. API documentation"))
    story.append(Paragraph("Endpoint", styles["H2Custom"]))
    story.append(code_block("POST /analyzeContour\nContent-Type: multipart/form-data\nField: file=<contour-map.kml|contour-map.kmz>"))
    story.append(Paragraph("Query parameters", styles["H2Custom"]))
    params = [[P("Parameter", styles["TableHead"]), P("Type / default", styles["TableHead"]), P("Description", styles["TableHead"])],
              [P("grid_size", styles["TableBody"]), P("integer / 100", styles["TableBody"]), P("Cells along the longer map dimension; range 40-220.", styles["TableBody"])],
              [P("max_candidates", styles["TableBody"]), P("integer / 3", styles["TableBody"]), P("Number of ranked pond recommendations; range 1-5.", styles["TableBody"])]]
    story.append(table(params, [35 * mm, 38 * mm, 101 * mm]))
    story.append(Paragraph("Success response", styles["H2Custom"]))
    story.append(Paragraph("The JSON response contains analysis status, input contour statistics, terrain-grid metadata, and a list of recommendations. Each recommendation includes a WGS84 point, pond region, elevation, depth/storage estimate, and a catchment object with area in square metres/hectares and GeoJSON geometry.", styles["BodyCustom"]))
    story.append(code_block('{\n  "analysis": {"status": "completed", "algorithm_version": "terrain-d8-v1"},\n  "input": {"contour_features": 2710, "contour_interval_m": 1.0},\n  "recommendations": [{\n    "site_id": "pond-1",\n    "location": {"type": "Point", "coordinates": [81.2899372847, 21.2499875606]},\n    "catchment": {"area_hectares": 16.0327, "geometry": {"type": "MultiPolygon"}}\n  }]\n}'))
    story.append(Paragraph("Additional routes", styles["H2Custom"]))
    story.append(Paragraph("<b>GET /health</b> returns service status. <b>GET /docs</b> opens the interactive Swagger UI. <b>POST /findCatchment</b> is a compatibility alias for the main analysis route.", styles["BodyCustom"]))

    # Demonstration
    story.extend(section("5. Demonstration using the supplied contour map"))
    story.append(Paragraph("Test input: <b>contour-maps/contours_1m.kml</b> (approximately 6.7 MB). The endpoint was exercised locally through HTTP and returned status 200.", styles["BodyCustom"]))
    demo = [[P("Observed metric", styles["TableHead"]), P("Result", styles["TableHead"])],
            [P("Contour features", styles["TableBody"]), P("2,710", styles["TableBody"])],
            [P("Elevation range", styles["TableBody"]), P("267-298 m", styles["TableBody"])],
            [P("Contour interval", styles["TableBody"]), P("1 m", styles["TableBody"])],
            [P("First recommended point", styles["TableBody"]), P("81.2899372847, 21.2499875606", styles["TableBody"])],
            [P("First estimated catchment", styles["TableBody"]), P("16.0327 hectares", styles["TableBody"])],
            [P("First storage estimate", styles["TableBody"]), P("4,233.98 m3", styles["TableBody"])]]
    story.append(table(demo, [68 * mm, 106 * mm]))
    story.extend([Spacer(1, 4 * mm), Paragraph("Reproduce locally", styles["H2Custom"]), code_block('python run.py\n\n# In another PowerShell window\ncurl.exe -X POST "http://127.0.0.1:8000/analyzeContour?grid_size=100&max_candidates=3" `\n  -F "file=@contour-maps/contours_1m.kml"'), Paragraph("The interactive alternative is http://127.0.0.1:8000/docs: expand POST /analyzeContour, select Try it out, upload the KML, and execute the request.", styles["BodyCustom"])])

    # Visual evidence captured from the running local Swagger UI.
    story.extend(section("6. Interactive Swagger UI evidence"))
    story.append(Paragraph("The following screenshots document the complete local demonstration flow. They show the available routes, the selected sample file, and the successful HTTP 200 response returned by the analysis endpoint.", styles["BodyCustom"]))
    story.append(Paragraph("Usage sequence", styles["H2Custom"]))
    story.append(Paragraph("Start the service with <b>python run.py</b>, open <b>http://127.0.0.1:8000/docs</b>, expand <b>POST /analyzeContour</b>, choose <b>Try it out</b>, upload <b>contours_1m.kml</b>, and press <b>Execute</b>. The response appears under Server response with status 200.", styles["BodyCustom"]))
    story.extend(visual_figure("01_swagger_api_overview.png", "Figure 1. Swagger UI overview showing the health check and contour-analysis routes.", max_height=92 * mm))
    story.append(PageBreak())
    story.extend(visual_figure("02_swagger_upload_form.png", "Figure 2. Expanded POST /analyzeContour form with the sample KML selected and Execute button ready.", max_height=150 * mm))
    story.append(PageBreak())
    story.extend(visual_figure("03_swagger_success_response.png", "Figure 3. Successful HTTP 200 response showing completed analysis, contour statistics, terrain grid, and recommendation JSON.", max_height=68 * mm))
    story.append(Paragraph("The response can be consumed directly by a frontend map because pond and catchment geometries are returned as WGS84 GeoJSON.", styles["BodyCustom"]))

    # Validation and deployment
    story.extend(section("7. Validation and deployment"))
    story.append(Paragraph("Automated validation", styles["H2Custom"]))
    validation = [[P("Test", styles["TableHead"]), P("Purpose", styles["TableHead"]), P("Result", styles["TableHead"])],
                  [P("Health route", styles["TableBody"]), P("Confirms service responds", styles["TableBody"]), P("Passed", styles["TableBody"])],
                  [P("Sample KML analysis", styles["TableBody"]), P("Confirms full terrain pipeline", styles["TableBody"]), P("Passed", styles["TableBody"])],
                  [P("Unsupported extension", styles["TableBody"]), P("Confirms upload validation", styles["TableBody"]), P("Passed", styles["TableBody"])],
                  [P("Sample KMZ analysis", styles["TableBody"]), P("Confirms archive extraction", styles["TableBody"]), P("Passed", styles["TableBody"])]]
    story.append(table(validation, [43 * mm, 93 * mm, 38 * mm]))
    story.append(Paragraph("Remote deployment", styles["H2Custom"]))
    story.append(code_block('git clone <GitHub repository URL>\ncd <repository-directory>\npython3 -m venv .venv\nsource .venv/bin/activate\npip install -r requirements.txt\ntmux new -s pond-api\nuvicorn app.main:app --host 0.0.0.0 --port 8000'))
    story.append(Paragraph("After starting Uvicorn, detach from tmux with Ctrl-b then d. Reattach with tmux attach -t pond-api. A reverse proxy or secure tunnel should expose the service using the remote host's public URL. SSH credentials and tokens must remain outside the repository.", styles["BodyCustom"]))

    # Limits/future
    story.append(PageBreak())
    story.extend(section("8. Limitations and future phases"))
    story.append(Paragraph("The current result is a terrain-only planning estimate, not a final civil-engineering design. The reported storage estimate uses a conservative compact footprint and depth approximation derived from contour interval. It does not yet model rainfall intensity, runoff coefficient, infiltration, evaporation, land ownership, soil, structures, or field constraints.", styles["BodyCustom"]))
    future = [[P("Future layer", styles["TableHead"]), P("Planned extension", styles["TableHead"])],
              [P("Rainfall", styles["TableBody"]), P("Apply rainfall and runoff coefficients to convert catchment area into seasonal volume scenarios.", styles["TableBody"])],
              [P("Government land", styles["TableBody"]), P("Intersect candidate pond/catchment geometries with land-ownership boundaries.", styles["TableBody"])],
              [P("Satellite data", styles["TableBody"]), P("Add land cover, drainage, vegetation, and water-body constraints.", styles["TableBody"])],
              [P("Hydraulic design", styles["TableBody"]), P("Replace the approximate footprint/depth estimate with a stage-area-volume model.", styles["TableBody"])],
              [P("Frontend map", styles["TableBody"]), P("Render returned GeoJSON on an interactive map and expose analysis parameters.", styles["TableBody"])]]
    story.append(table(future, [45 * mm, 129 * mm]))
    return story


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(str(OUTPUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=20 * mm, title="AI Village Pond Planning - Phase 2 Technical Report", author="AI Village Pond Planning Team")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    cover = PageTemplate(id="cover", frames=frame, onPage=cover_footer)
    regular = PageTemplate(id="regular", frames=frame, onPage=footer)
    doc.addPageTemplates([cover, regular])
    story = build_story()
    # First page uses the cover template; switch to the regular template after
    # the first explicit PageBreak.
    story.insert(0, NextPageTemplate("regular"))
    doc.build(story)
    print(OUTPUT)


if __name__ == "__main__":
    main()
