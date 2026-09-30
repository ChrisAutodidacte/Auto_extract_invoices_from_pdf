# 📑 Smart PDF Invoice Splitter & Auto-Renamer (Gemini AI + Python)

> 🇫🇷 **Vous cherchez la version française ?** Consultez le dépôt français : [decoupe-factures-pdf-ia](https://github.com/ChrisAutodidacte/decoupe-factures-pdf-ia)

> 🤖 **Automate the painful chore of sorting and renaming phone-scanned invoice batches.**  
> Uses **Google Gemini Multimodal AI** to automatically detect document boundaries inside a multi-page PDF, split it into individual invoices, and rename them with vendor name, invoice number, date, and payment status tags.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![Google Gemini API](https://img.shields.io/badge/Gemini-2.5_Flash/Pro-orange.svg)](https://aistudio.google.com)

---

## 🎬 Video Walkthrough

> 📺 **Watch the Video Walkthrough**:  
> Available on the YouTube channel: **[Chris Figures It Out](https://www.youtube.com/@ChrisFiguresItOut)**

---

## 💡 The Real-World Problem

If you run a small business, manage bookkeeping, or work as a freelancer, you probably scan paper receipts and invoices using your smartphone (Apple Notes, Google Drive, Genius Scan, CamScanner...).

The result? **One single massive 10, 20, or 30-page PDF file** with all your documents concatenated together:
- Some invoices are **1 page**, others span **2 or 3 pages**.
- Counting pages and splitting them manually in Adobe Acrobat is a tedious, mind-numbing waste of time.
- Manually renaming every single file (`Invoice_Vendor_Number_Date.pdf`) is error-prone.
- **The double-payment nightmare:** It is easy to accidentally pay an invoice manually when it was already scheduled for **automatic direct debit (ACH / SEPA)**.

This lightweight tool automates the entire pipeline in seconds.

---

## 🧠 How It Works: The 2-Pass Vision Pipeline

Traditional OCR tools fail at multi-page invoice separation because they lack spatial understanding. Instead, this tool leverages **Google Gemini Vision** in two clean passes:

```
                        ┌──────────────────────────────────────┐
                        │   1 Massive Scanned PDF (inbox/)     │
                        └──────────────────┬───────────────────┘
                                           │
                                           ▼
      [STEP 1: SPLIT]         🧠 Gemini Vision (Pass 1)
                              Detects boundaries of each invoice
                                           │
                                           ▼
                              ✂️ Splitting with pypdf
                              Produces clean drafts in invoices/
                                           │
                                           ▼
      [STEP 2: RENAME]        🧠 Gemini Vision (Pass 2)
                              Extracts: Type, Vendor, Invoice #, Date
                                           │
                                           ▼
                              🏷️ Auto-Debit Check (auto_debit_vendors.txt)
                              Tags [AUTO-DEBIT] or [MANUAL]
                                           │
                                           ▼
                        ┌──────────────────────────────────────┐
                        │   Final Renamed, Organized PDFs      │
                        │   Invoice_[AUTO-DEBIT]_Vendor_#_Date │
                        └──────────────────────────────────────┘
```

1. **Step 1 (Boundary Detection & Splitting):** Each page is rendered as a crisp high-resolution image. Gemini reviews the sequence, detects where each invoice starts and ends (regardless of page length), and splits the master scan into drafts. The master scan is archived into `inbox/processed/`.
2. **Step 2 (Metadata Extraction & Verification):** Gemini inspects each individual draft to extract the exact issuing company name, document reference number, and document date.
3. **The Business Auto-Debit Rule:** The vendor is checked against `auto_debit_vendors.txt`. If the vendor is on your auto-pay list, the file receives the `[AUTO-DEBIT]` tag; otherwise, it gets tagged `[MANUAL]` so you know what needs manual payment.

---

## 📁 Repository Structure

```text
├── inbox/                      # 📥 Place your incoming scanned PDF files here
│   ├── Phone_Scan_...pdf       # Sample 7-page multi-invoice scan included
│   └── processed/              # 📦 Original scans automatically archived here
├── invoices/                   # 📄 Final separated and renamed invoices
├── anomalies/                  # ⚠️ Unreadable or corrupted files flagged for manual review
├── samples/                    # 🧪 Original individual test invoices
├── auto_debit_vendors.txt      # ⚙️ List of vendors paid via direct debit / ACH
├── Run Invoice Splitter.bat    # ⚡ 1-Click Windows launcher (no command prompt needed)
├── invoice_processor.py        # 🐍 Main Python automation script
├── requirements.txt            # 📦 Python package dependencies
├── .env.example                # 🔑 API key template
├── LICENSE                     # ⚖️ MIT License
└── README.md
```

---

## 🚀 Quickstart Installation

### 1. Prerequisites
- **Python 3.10 or higher** installed on your system.
- A **Google Gemini API key** (free tier available at [Google AI Studio](https://aistudio.google.com/)).

### 2. Clone the Repository
```bash
git clone https://github.com/ChrisAutodidacte/smart-pdf-invoice-splitter.git
cd smart-pdf-invoice-splitter
```

### 3. Install Dependencies
```bash
python -m venv venv

# On Windows:
venv\Scripts\activate

# On Linux / macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 4. Configure Your API Key
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Open `.env` and paste your Gemini API key:
```env
GEMINI_API_KEY=your_actual_api_key_here
```

---

## ⚡ How to Use (Double-Click Simplicity)

1. A sample 7-page multi-invoice scan (`Phone_Scan_Invoices_Batch.pdf`) is already preloaded inside **`inbox/`**.
2. Customize **`auto_debit_vendors.txt`** with your own vendor names if needed.
3. **Run the tool:**
   - **On Windows (Recommended for non-tech users):** Simply double-click **`Run Invoice Splitter.bat`** (no terminal commands to type).
   - **Via Command Line:**
     ```bash
     python invoice_processor.py
     ```
4. Open the **`invoices/`** folder: your invoices are now neatly separated, labeled, and tagged!

---

## 🛡️ Privacy & Security

- Your files are processed locally. Only image pages are securely transmitted to Google's Gemini API over TLS for inference.
- Your `.env` file containing your secret API key is strictly ignored by `.gitignore`.

---

## 👤 Author & Philosophy

Built by **Chris** from **[Chris Figures It Out](https://www.youtube.com/@ChrisFiguresItOut)** — Pragmatic, real-world tech and automation for entrepreneurs, makers, and small business owners.
- Website: [chrisautodidacte.com/en](https://chrisautodidacte.com/en)
- French Channel: [Chris l'Autodidacte](https://www.youtube.com/@ChrisAutodidacte)

License: [MIT](LICENSE)
