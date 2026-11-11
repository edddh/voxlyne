"""
Voxlyne - RAG text extraction from raw source bytes/HTML.

One function per format the admin upload endpoint accepts. Kept separate
from chunking.py (format-specific extraction vs format-agnostic
splitting) and from crawler.py (network fetching vs text extraction -
the crawler calls extract_html_text() on each page it fetches).
"""

import io
import logging

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def extract_html_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def extract_pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            logger.exception("Failed to extract text from a PDF page, skipping it")
    return "\n\n".join(pages)


def extract_docx_text(data: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(data))
    return "\n\n".join(p.text for p in document.paragraphs if p.text.strip())


def extract_upload_text(filename: str, data: bytes) -> str:
    """Dispatches on file extension. Raises ValueError for unsupported types."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return extract_pdf_text(data)
    if lower.endswith(".docx"):
        return extract_docx_text(data)
    if lower.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="replace")
    if lower.endswith((".html", ".htm")):
        return extract_html_text(data.decode("utf-8", errors="replace"))
    raise ValueError(f"Unsupported file type: {filename} (accepted: .pdf, .docx, .txt, .md, .html)")
