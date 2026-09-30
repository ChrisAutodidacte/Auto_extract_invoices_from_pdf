#!/usr/bin/env python3
"""
Smart PDF Invoice Splitter & Auto-Renamer
------------------------------------------
Automated PDF document processing pipeline:
  Step 1 (split)  : Splits multi-invoice PDFs from inbox/ into individual draft invoices in invoices/
  Step 2 (rename) : Analyzes each draft invoice and renames it with document type, vendor, invoice #, and date.
                    Matches against auto_debit_vendors.txt to flag auto-paid invoices.

Usage: python invoice_processor.py
"""

import os
import sys
import json
import shutil
import time
import unicodedata
import re
import base64
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF
from pypdf import PdfReader, PdfWriter
from google import genai
from google.genai import types
from dotenv import load_dotenv

# --- Configuration -----------------------------------------------------------

BASE_DIR = Path(__file__).parent
INBOX_DIR = BASE_DIR / "inbox"
INVOICES_DIR = BASE_DIR / "invoices"
ANOMALIES_DIR = BASE_DIR / "anomalies"
PROCESSED_DIR = INBOX_DIR / "processed"
AUTO_DEBIT_FILE = BASE_DIR / "auto_debit_vendors.txt"

load_dotenv(BASE_DIR / ".env")
API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = "gemini-2.5-pro"


# --- Utilities ---------------------------------------------------------------

def remove_accents(text: str) -> str:
    """Replaces accented characters with their ASCII equivalents."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def safe_filename(text: str, max_len: int = 50) -> str:
    """Sanitizes a string to produce a clean, filesystem-safe filename."""
    text = remove_accents(text)
    text = re.sub(r"[^a-zA-Z0-9_\-]", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:max_len]


def load_auto_debit_vendors() -> list[str]:
    """Loads the list of auto-debit / direct debit vendors from external text file."""
    if not AUTO_DEBIT_FILE.exists():
        return []
    vendors = []
    for line in AUTO_DEBIT_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            vendors.append(line)
    return vendors


def is_auto_debit_vendor(supplier: str, auto_debit_vendors: list[str]) -> bool:
    """Checks if a vendor matches the auto-debit list (case/accent-insensitive fuzzy match)."""
    supplier_norm = remove_accents(supplier).lower().strip()
    for vendor in auto_debit_vendors:
        vendor_norm = remove_accents(vendor).lower().strip()
        if vendor_norm in supplier_norm or supplier_norm in vendor_norm:
            return True
    return False


def pdf_pages_to_base64(pdf_path: Path) -> list[dict]:
    """Converts each page of a PDF into a high-res JPEG base64 image (scale 2.0)."""
    doc = fitz.open(str(pdf_path))
    images = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("jpeg", jpg_quality=80)
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        images.append({
            "page_number": page_num + 1,
            "base64": b64,
        })
    doc.close()
    return images


def move_to_anomalies(file_path: Path, reason: str):
    """Moves an unprocessable file into the anomalies directory."""
    ANOMALIES_DIR.mkdir(exist_ok=True)
    dest = ANOMALIES_DIR / file_path.name
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        dest = ANOMALIES_DIR / f"{stem}_{datetime.now():%Y%m%d_%H%M%S}{suffix}"
    shutil.move(str(file_path), str(dest))
    print(f"  [ANOMALY] {file_path.name} -> anomalies/ ({reason})")


class GeminiServiceUnavailableError(Exception):
    """Raised when Gemini returns a 503 error after all retry attempts."""


def call_gemini_with_retry(client, parts, schema, max_retries=3):
    """Calls Gemini API with exponential backoff on rate-limits (429) or service outages (503)."""
    last_503 = False
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=types.Content(parts=parts),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
            return response
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                last_503 = False
                wait = 30 * (attempt + 1)
                print(f"  Rate limit encountered, waiting {wait}s before retry ({attempt + 1}/{max_retries})...")
                time.sleep(wait)
            elif "503" in err or "SERVICE_UNAVAILABLE" in err or "unavailable" in err.lower():
                last_503 = True
                wait = 10 * (attempt + 1)
                print(f"  Gemini service unavailable (503), waiting {wait}s before retry ({attempt + 1}/{max_retries})...")
                time.sleep(wait)
            else:
                raise
    if last_503:
        raise GeminiServiceUnavailableError(
            f"Gemini unavailable after {max_retries} attempts (503). File kept in inbox for later retry."
        )
    raise Exception(f"Gemini unavailable after {max_retries} attempts. Document moved to anomalies.")


def split_pdf(source_path: Path, start_page: int, end_page: int, output_path: Path):
    """Extracts pages start_page..end_page (1-based index) from a PDF and saves them."""
    reader = PdfReader(str(source_path))
    writer = PdfWriter()
    for i in range(start_page - 1, end_page):
        if i < len(reader.pages):
            writer.add_page(reader.pages[i])
    with open(output_path, "wb") as f:
        writer.write(f)


# --- Gemini Client -----------------------------------------------------------

def get_gemini_client():
    """Initializes the Gemini API client."""
    if not API_KEY:
        print("ERROR: GEMINI_API_KEY is missing from your .env file.")
        print("Please copy .env.example to .env and insert your API key.")
        sys.exit(1)
    return genai.Client(api_key=API_KEY)


# --- Step 1: Split -----------------------------------------------------------

PROMPT_SPLIT = """You are an expert document analysis specialist in accounting.
I have provided {nb_pages} images representing consecutive pages of a scanned PDF containing multiple accounting documents.

Your mission:
1. Identify the boundaries of each individual document. Some are single-page documents, others span multiple pages (e.g. page 1 items, page 2 terms/totals).
2. Group consecutive pages that belong to the exact same document.
3. For each document identified, extract:
   - docType: "invoice", "credit_note", or "receipt"
     * "invoice" = standard vendor invoice with header, invoice number, line items, and totals
     * "credit_note" = credit memo, refund, or adjustment
     * "receipt" = point-of-sale receipt or slip with items and totals
   - supplier: Name of the issuing company or vendor
   - invoiceNumber: Unique document identifier or reference
   - date: Document date formatted as YYYY-MM-DD

Return the results as a JSON array."""

SPLIT_SCHEMA = types.Schema(
    type=types.Type.ARRAY,
    items=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "startPage": types.Schema(type=types.Type.INTEGER, description="Index of the first page (1-based)."),
            "endPage": types.Schema(type=types.Type.INTEGER, description="Index of the last page (1-based)."),
            "docType": types.Schema(type=types.Type.STRING, description="Type: invoice, credit_note, or receipt."),
            "supplier": types.Schema(type=types.Type.STRING, description="Name of the issuing vendor / company."),
            "invoiceNumber": types.Schema(type=types.Type.STRING, description="Unique invoice or document number."),
            "date": types.Schema(type=types.Type.STRING, description="Document date formatted as YYYY-MM-DD."),
        },
        required=["startPage", "endPage", "docType", "supplier", "invoiceNumber", "date"],
    ),
)


def step_split(client):
    """Step 1: Scans inbox/, analyzes boundaries with Gemini, splits into individual draft PDFs."""
    print("\n" + "=" * 60)
    print("STEP 1: PDF BOUNDARY DETECTION & SPLITTING")
    print("=" * 60)

    INBOX_DIR.mkdir(exist_ok=True)
    INVOICES_DIR.mkdir(exist_ok=True)
    PROCESSED_DIR.mkdir(exist_ok=True)

    pdf_files = sorted(INBOX_DIR.glob("*.pdf"))
    if not pdf_files:
        print("No PDF files found in inbox/")
        return

    print(f"{len(pdf_files)} PDF file(s) to process.\n")

    for pdf_path in pdf_files:
        print(f"--- Processing: {pdf_path.name} ---")
        try:
            images = pdf_pages_to_base64(pdf_path)
            print(f"  {len(images)} page(s) converted to high-res images.")

            parts = []
            for img in images:
                parts.append(types.Part.from_bytes(
                    data=base64.b64decode(img["base64"]),
                    mime_type="image/jpeg",
                ))
            parts.append(types.Part.from_text(text=PROMPT_SPLIT.format(nb_pages=len(images))))

            print("  Analyzing document boundaries with Gemini Vision...")
            response = call_gemini_with_retry(client, parts, SPLIT_SCHEMA)

            if not response.text:
                move_to_anomalies(pdf_path, "No response from Gemini")
                continue

            invoices = json.loads(response.text)
            if not invoices:
                move_to_anomalies(pdf_path, "No documents detected by Gemini")
                continue

            print(f"  {len(invoices)} document(s) detected.")

            # Validate page boundaries
            nb_pages = len(images)
            valid = True
            for inv in invoices:
                if inv["startPage"] < 1 or inv["endPage"] > nb_pages or inv["startPage"] > inv["endPage"]:
                    valid = False
                    break
            if not valid:
                move_to_anomalies(pdf_path, "Invalid page ranges returned by model")
                continue

            # Split the PDF into drafts
            now = datetime.now()
            for idx, inv in enumerate(invoices, 1):
                filename = f"draft_invoice_{now:%Y%m%d_%H%M%S}_{idx:03d}.pdf"
                output_path = INVOICES_DIR / filename
                split_pdf(pdf_path, inv["startPage"], inv["endPage"], output_path)
                doc_type = inv.get("docType", "invoice")
                print(f"  -> {filename} (pages {inv['startPage']}-{inv['endPage']}, {doc_type}, {inv.get('supplier', '?')})")

            # Move original scanned file into processed/
            dest = PROCESSED_DIR / pdf_path.name
            if dest.exists():
                dest = PROCESSED_DIR / f"{pdf_path.stem}_{now:%Y%m%d_%H%M%S}{pdf_path.suffix}"
            shutil.move(str(pdf_path), str(dest))
            print(f"  Original PDF moved to inbox/processed/")

        except GeminiServiceUnavailableError as e:
            print(f"  [503] {e}")
            print(f"  File remains in inbox/ for subsequent retry.")
        except Exception as e:
            print(f"  ERROR: {e}")
            move_to_anomalies(pdf_path, str(e))


# --- Step 2: Rename ----------------------------------------------------------

PROMPT_RENAME = """You are an expert document analysis specialist in accounting.
These images represent an accounting document (possibly spanning multiple pages).

Extract the following information:
- docType:
  * "invoice" = standard vendor invoice with header, invoice number, and totals
  * "credit_note" = credit memo, refund, or adjustment
  * "receipt" = point-of-sale receipt or slip with items and totals
- supplier: Name of the issuing company / vendor
- invoiceNumber: Unique invoice or document number
- date: Document date in YYYY-MM-DD format

Be accurate and return JSON format."""

RENAME_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "docType": types.Schema(type=types.Type.STRING, description="Type: invoice, credit_note, or receipt."),
        "supplier": types.Schema(type=types.Type.STRING, description="Name of the issuing vendor / company."),
        "invoiceNumber": types.Schema(type=types.Type.STRING, description="Unique document / invoice identifier."),
        "date": types.Schema(type=types.Type.STRING, description="Document date YYYY-MM-DD."),
    },
    required=["docType", "supplier", "invoiceNumber", "date"],
)

DOC_TYPE_PREFIX = {
    "invoice": "Invoice",
    "credit_note": "CreditNote",
    "receipt": "Receipt",
}


def step_rename(client):
    """Step 2: Reads each draft invoice, extracts verified metadata, renames with auto-debit tag."""
    print("\n" + "=" * 60)
    print("STEP 2: METADATA EXTRACTION & SMART RENAMING")
    print("=" * 60)

    # Load auto-debit vendors
    auto_debit_vendors = load_auto_debit_vendors()
    if auto_debit_vendors:
        print(f"Auto-debit vendors loaded: {', '.join(auto_debit_vendors)}")
    else:
        print("No auto-debit vendors configured (file auto_debit_vendors.txt)")
    print()

    drafts = sorted(INVOICES_DIR.glob("draft_invoice_*.pdf"))
    if not drafts:
        print("No draft invoices to process in invoices/")
        return

    print(f"{len(drafts)} draft invoice(s) to process.\n")

    for pdf_path in drafts:
        print(f"--- Processing Draft: {pdf_path.name} ---")
        try:
            images = pdf_pages_to_base64(pdf_path)

            parts = []
            for img in images:
                parts.append(types.Part.from_bytes(
                    data=base64.b64decode(img["base64"]),
                    mime_type="image/jpeg",
                ))
            parts.append(types.Part.from_text(text=PROMPT_RENAME))

            print("  Extracting metadata via Gemini Vision...")
            response = call_gemini_with_retry(client, parts, RENAME_SCHEMA)

            if not response.text:
                move_to_anomalies(pdf_path, "No response from Gemini")
                continue

            data = json.loads(response.text)

            doc_type = data.get("docType", "invoice").strip().lower()
            supplier = data.get("supplier", "").strip()
            invoice_number = data.get("invoiceNumber", "").strip()
            date_str = data.get("date", "").strip()

            # Validation
            if not supplier or supplier.lower() in ("unknown", "inconnu", ""):
                move_to_anomalies(pdf_path, "Vendor name could not be identified")
                continue

            if not invoice_number:
                move_to_anomalies(pdf_path, "Invoice number could not be identified")
                continue

            if not date_str:
                move_to_anomalies(pdf_path, "Invoice date could not be identified")
                continue

            # Format date YYYY-MM-DD -> YYYYMMDD
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                date_formatted = dt.strftime("%Y%m%d")
            except ValueError:
                for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y%m%d"):
                    try:
                        dt = datetime.strptime(date_str, fmt)
                        date_formatted = dt.strftime("%Y%m%d")
                        break
                    except ValueError:
                        continue
                else:
                    move_to_anomalies(pdf_path, f"Invalid date format: {date_str}")
                    continue

            # Determine prefix and check auto-debit match
            prefix = DOC_TYPE_PREFIX.get(doc_type, "Invoice")
            is_auto_debit = is_auto_debit_vendor(supplier, auto_debit_vendors)
            if is_auto_debit:
                prefix = f"{prefix}_[AUTO-DEBIT]"          

            # Construct safe sanitized filename
            safe_supplier = safe_filename(supplier)
            safe_number = safe_filename(invoice_number, max_len=30)
            new_name = f"{prefix}_{safe_supplier}_{safe_number}_{date_formatted}.pdf"

            new_path = INVOICES_DIR / new_name
            if new_path.exists():
                new_name = f"{prefix}_{safe_supplier}_{safe_number}_{date_formatted}_{datetime.now():%H%M%S}.pdf"
                new_path = INVOICES_DIR / new_name

            pdf_path.rename(new_path)
            debit_status = " [AUTO-DEBIT]" if is_auto_debit else ""
            print(f"  -> Renamed: {new_name}")
            print(f"     Type: {doc_type}{debit_status} | Vendor: {supplier} | #: {invoice_number} | Date: {date_formatted}")

        except GeminiServiceUnavailableError as e:
            print(f"  [503] {e}")
            print(f"  Draft remains in invoices/ for subsequent retry.")
        except Exception as e:
            print(f"  ERROR: {e}")
            move_to_anomalies(pdf_path, str(e))


# --- Main --------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  SMART PDF INVOICE SPLITTER & RENAMER")
    print(f"  {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 60)

    client = get_gemini_client()

    step_split(client)
    step_rename(client)

    print("\n" + "=" * 60)
    print("PROCESSING COMPLETE")
    print("=" * 60)

    final_invoices = [f for f in INVOICES_DIR.glob("*.pdf") if not f.name.startswith("draft_invoice_")]
    anomalies = list(ANOMALIES_DIR.glob("*.pdf")) if ANOMALIES_DIR.exists() else []
    remaining_drafts = list(INVOICES_DIR.glob("draft_invoice_*.pdf"))

    print(f"  Invoices Processed : {len(final_invoices)}")
    print(f"  Anomalies          : {len(anomalies)}")
    if remaining_drafts:
        print(f"  Remaining Drafts   : {len(remaining_drafts)}")


if __name__ == "__main__":
    main()
