
import sys
from pypdf import PdfReader

try:
    reader = PdfReader("d:\\Desktop\\QuantAgent\\工作周报.pdf")
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    print(text)
except Exception as e:
    print(f"Error reading PDF: {e}")
