import fitz
import os

pdf_path = "voicefinance_report_pie.pdf"
doc = fitz.open(pdf_path)
page = doc[0]
pix = page.get_pixmap(dpi=150)
out_path = r"C:\Users\artem\.gemini\antigravity\brain\cb6af9ff-a0d3-4896-b676-a9079b12de68\pie_preview.png"
pix.save(out_path)
print("Preview saved to:", out_path)
