# 📘 Smart Manufacturing Knowledge Engine - Complete Project Documentation

## 🎯 PROJECT OVERVIEW

### What This Project Does
This system converts **unstructured PDF manufacturing manuals** into **structured Excel test procedures** for smart manufacturing. It extracts test procedures from industrial product manuals so factory operators can follow standardized testing workflows.

**INPUT:** PDF manual with 8-10 different machine testing procedures mixed together  
**OUTPUT:** Individual Excel files for each machine containing structured test procedures

### Real-World Use Case
A factory receives a 20-page PDF manual describing functional tests for multiple voltage monitoring relay products (SPPR, SM301, SM500, MG63BF, etc.). Each product has:
- Setup instructions
- Test procedures (numbered steps)
- Expected results (LED behavior, relay timing, voltage ranges)
- Pass/fail criteria

Currently, operators manually read these PDFs. This system **automates extraction** into structured Excel sheets.

---

## 🏗️ ARCHITECTURE & WORKFLOW

### Current System Flow

```
┌─────────────────┐
│  Upload PDF     │
│  (User)         │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│  FastAPI Backend (main.py)      │
│  - Generates unique extraction  │
│    ID (ext_abc12345)            │
│  - Saves PDF to /uploads        │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  PDF Extraction                 │
│  (pdf_extractor.py)             │
│  - Uses pdfplumber (primary)    │
│  - Fallback: PyMuPDF            │
│  - Returns: List of page texts  │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Block Segmentation             │
│  (block_segmenter.py)           │
│  - Splits PDF into machine      │
│    sections using regex         │
│  - Returns: List of blocks      │
│    [{machine, header, text}]    │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  CURRENT PATH (Voltage Specs):  │
│  ├─ table_extractor.py          │
│  │  (finds TABLE 2 structures)  │
│  ├─ spec_parser.py               │
│  │  (extracts voltage params)   │
│  └─ excel_writer.py              │
│     (creates Excel with specs)  │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  TARGET PATH (Test Procedures): │
│  ├─ template_builder.py          │
│  │  (extracts numbered steps)   │
│  └─ excel_template_writer.py    │
│     (fills Excel template)       │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Output Files:                  │
│  - Excel files in /outputs      │
│  - Metadata JSON in /metadata   │
│  - (Text files DISABLED)        │
└─────────────────────────────────┘
```

---

## 📁 FILE STRUCTURE & RESPONSIBILITIES

### **Backend Directory Structure**

```
backend/
├── main.py                          # FastAPI application (entry point)
├── requirements.txt                 # Python dependencies
├── .gitignore                       # Excludes uploads/outputs from git
│
├── models/
│   └── schemas.py                   # Pydantic data models (ExtractionResult, etc.)
│
├── services/                        # Core processing modules
│   ├── pdf_extractor.py             # PDF text extraction (pdfplumber + PyMuPDF)
│   ├── block_segmenter.py           # Splits PDF into machine sections
│   ├── table_extractor.py           # Finds TABLE structures in text
│   ├── spec_parser.py               # Extracts voltage/timing parameters
│   ├── excel_writer.py              # Generates Excel (voltage specs)
│   ├── template_builder.py          # Extracts numbered test steps
│   ├── excel_template_writer.py     # Fills Excel template (test procedures)
│   └── excel_json_converter.py      # Converts Excel to JSON (if needed)
│
├── static/                          # Frontend files
│   ├── index.html                   # Main upload interface
│   ├── extraction.html              # Results viewing page
│   └── script.js                    # Frontend JavaScript
│
├── uploads/                         # Uploaded PDFs (NOT in git)
├── outputs/                         # Generated Excel files (NOT in git)
├── metadata/                        # Extraction metadata JSONs (NOT in git)
└── tests/                           # Test scripts
    ├── test_real_pdf.py
    ├── test_table_extraction.py
    └── debug_sppr_table.py
```

---

## 🔧 DETAILED FILE RESPONSIBILITIES

### **Core Application Files**

#### `main.py` (FastAPI Application)
**Purpose:** HTTP API server handling PDF uploads and orchestrating processing pipeline

**Key Endpoints:**
- `POST /api/extract` - Upload PDF, returns extraction_id
- `GET /api/extraction/{id}` - Get extraction metadata
- `GET /api/download/{id}/{filename}` - Download generated files
- `GET /api/extractions` - List all extractions
- `GET /health` - Health check

**Current Flow:**
1. Generate unique extraction_id (format: `ext_abc12345`)
2. Save uploaded PDF to `/uploads/ext_abc12345_filename.pdf`
3. Extract text using `pdf_extractor.py`
4. Segment into blocks using `block_segmenter.py`
5. Extract data using either:
   - **Current:** `spec_parser.py` → voltage parameters
   - **Target:** `template_builder.py` → test procedures
6. Generate Excel files in `/outputs/`
7. Save metadata to `/metadata/ext_abc12345.json`
8. Return JSON response with download URLs

**Known Issues:**
- Currently saves useless text files (ext_abc_MACHINE.txt) - should be disabled
- Uses voltage spec extraction instead of test procedure extraction

---

### **PDF Processing Services**

#### `services/pdf_extractor.py`
**Purpose:** Extract text from PDF files

**Functions:**
- `extract_text(pdf_path)` → List[str] of page texts
- `extract_text_pdfplumber(pdf_path)` → Primary extraction method
- `extract_text_pymupdf(pdf_path)` → Fallback if pdfplumber fails

**Logic:**
1. Try pdfplumber first (better table handling)
2. If fails, fallback to PyMuPDF
3. Returns list where each element = one page's text

**Status:** ✅ Working perfectly, no changes needed

---

#### `services/block_segmenter.py`
**Purpose:** Split full PDF text into separate sections for each machine/product

**How It Works:**
Uses regex patterns to detect section headers:
```python
SECTION_PATTERNS = [
    r"^PROCESS:\s*(.+)",                    # "PROCESS: Functional Testing"
    r"^(SM\d+)\s+Functional\s+Testing",     # "SM301 Functional Testing"
    r"^Process:\s+Functional\s+Testing",    # "Process: Functional Testing SM500_A"
    r"^(DMS\d+)",                           # "DMS110", "DMS120"
    r"^(MG\d+[A-Z]+)",                      # "MG63BF", "MG73BQ"
    # ... more patterns
]
```

**Key Features:**
- `MIN_BLOCK_SIZE = 1000` chars (prevents premature splitting)
- `has_incomplete_table_reference()` - Prevents splitting before TABLE appears
- Handles duplicate machine names by numbering (MG63BF, MG63BF_2)

**Output:**
```python
[
    {
        "machine": "SPPR",
        "header": "Neutral Open SPPR",
        "text": "Full procedure text..."
    },
    {
        "machine": "SM301",
        "header": "SM301 AUTOMATED FUNCTIONAL TESTING",
        "text": "Full procedure text..."
    }
]
```

**Status:** ⚠️ 75% working
- **Working:** SPPR, SM500, SM301, DMS120, DMS12024, MG63BF
- **Issues:** Some machines not segmenting correctly (reported by user)
- **Latest Version:** `block_segmenter_SMART.py` with table-aware logic

---

#### `services/table_extractor.py`
**Purpose:** Find and extract TABLE structures from text

**Functions:**
- `extract_tables(text)` → List of table dicts
- `detect_table_headers(text)` → Finds "TABLE 1", "TABLE 2" headers
- `parse_table_rows(text, start_line)` → Extracts parameter rows

**Recognizes:**
- Numbered tables: `TABLE 2 (PRODUCT SETTINGS @ 415 VAC)`
- Unnumbered tables: `TABLE (PRODUCT SETTINGS...)`
- Multi-column formats
- Key-value formats: `Under Voltage: 85%, 347 to 357 VAC`

**Output Example:**
```python
{
    "table_id": "TABLE_2",
    "title": "PRODUCT SETTINGS & ACCEPTABLE LIMITS @ 415 VAC",
    "rows": [
        {
            "parameter": "Under Voltage",
            "setting": "85%",
            "range": "347 to 357 VAC"
        }
    ]
}
```

**Status:** ✅ Working well for voltage parameter tables

---

#### `services/spec_parser.py`
**Purpose:** Extract voltage/timing specifications using regex patterns

**Extracts:**
- Voltages: `347 VAC`, `240 to 260 VAC`
- Percentages: `85%`, `110%`
- Delays: `5s`, `4 to 6s`
- LED states: `UV LED glows ON`
- Relay states: `Relay turns OFF`

**Output:**
```python
{
    "reference_voltage": {"value": 415, "unit": "VAC"},
    "voltage_parameters": {
        "under_voltage": {
            "setting": "85%",
            "range": "347 to 357 VAC"
        }
    },
    "timing_parameters": {
        "on_delay": {"setting": "5s", "range": "4 to 6s"}
    }
}
```

**Status:** ✅ Working, but NOT the main project goal

---

#### `services/template_builder.py` ⭐ TARGET
**Purpose:** Extract numbered test procedure steps (THE MAIN GOAL)

**How It Works:**
1. Detects procedure sections: `PROCEDURE:`, `UNDER VOLTAGE:`, etc.
2. Finds numbered steps: `8. Reduce the R-phase voltage...`
3. Identifies actions vs expected results
4. Groups related lines into steps

**Action Verbs Recognized:**
```python
ACTION_VERBS = (
    "TURN", "INSERT", "SET", "REDUCE", "INCREASE",
    "MAKE", "ENSURE", "RECOVER", "RESET",
    "KEEP", "VARY", "REMOVE", "STORE", "MARK"
)
```

**Output:**
```python
{
    "TestSteps": [
        {
            "Action": "Reduce the R-phase voltage till UV LED glows ON",
            "Expected Behavior": "Relay turns OFF after specified off delay time",
            "Relay Status": "OFF",
            "LED Indicator": "UV",
            "Delay": "5s",
            "Condition Type": "Under Voltage"
        }
    ]
}
```

**Status:** ✅ Code exists and works, but NOT integrated into main.py yet

---

### **Excel Generation Services**

#### `services/excel_writer.py`
**Purpose:** Generate Excel files with voltage specifications (current system)

**Creates:**
- Sheet 1: Specifications (voltage parameters, timing)
- Sheet 2: Test Procedures (placeholder)

**Styling:**
- Blue headers with white text
- Bordered cells
- Auto-sized columns

**Status:** ✅ Working, generates voltage spec Excel files

---

#### `services/excel_template_writer.py` ⭐ TARGET
**Purpose:** Fill Excel template with test procedures (target system)

**Function:**
- `fill_template_excel(template_path, output_path, ai_data)`

**ai_data Structure:**
```python
{
    "Product": "SPPR",
    "Specifications": {...},
    "TestSteps": [
        {"Action": "...", "Expected Behavior": "..."}
    ]
}
```

**Features:**
- Duplicates base sheet
- Fills structured data
- Deletes template sheets
- Safe save (handles locked files)

**Status:** ✅ Code exists, needs Excel template file

---

## 📊 CURRENT PROGRESS

### ✅ COMPLETED (100%)
1. **PDF Upload & Storage**
   - FastAPI backend with unique extraction IDs
   - File upload endpoint working
   - Metadata tracking system

2. **PDF Text Extraction**
   - pdfplumber integration (primary)
   - PyMuPDF fallback
   - Handles 20-page manufacturing PDFs

3. **Block Segmentation** (75% working)
   - Identifies 8-10 machine sections per PDF
   - Regex-based section detection
   - Smart table-aware splitting
   - **Issue:** Some machines still segment incorrectly

4. **Table Extraction**
   - Detects TABLE structures
   - Parses parameter rows
   - Handles multi-column formats

5. **Voltage Specification Extraction**
   - Extracts UV/OV/Asymmetry settings
   - Timing parameters (ON/OFF delay)
   - LED indicators
   - Generates Excel with specs

### ⚠️ IN PROGRESS (50%)
6. **Test Procedure Extraction**
   - `template_builder.py` exists and works
   - NOT integrated into main.py yet
   - Need to switch from voltage specs to test procedures

### ❌ NOT STARTED (0%)
7. **Excel Template System**
   - Need to create `test_procedure_template.xlsx`
   - Define column structure for test steps

8. **JSON Conversion**
   - Convert Excel → JSON for API consumption
   - `excel_json_converter.py` exists but unused

9. **Frontend Improvements**
   - Current UI is basic HTML
   - Need React/modern UI (mentioned by user)

10. **Database Integration**
    - Store extractions in database
    - Query historical extractions
    - Not started

---

## 🎯 MAIN PROJECT GOAL vs CURRENT STATE

### ❌ WHAT WE BUILT (WRONG FOCUS):
**Voltage Specification Tables**
- Extracted from TABLE 2 structures
- Shows UV/OV ranges, timing parameters
- **Problem:** This is reference data, not what operators need

**Example Output:**
```
SPPR Specifications:
- Under Voltage: 85%, 347 to 357 VAC
- Over Voltage: 110%, 453 to 459 VAC
- ON Delay: 5s, 4 to 6s
```

### ✅ WHAT WE NEED TO BUILD (ACTUAL GOAL):
**Test Procedure Steps**
- Numbered steps operators follow
- Actions + expected results
- Pass/fail criteria

**Example Output:**
```
SPPR Test Procedure:
Step 8: Reduce the R-phase voltage till UV LED glows ON
        Expected: Relay turns OFF after 5s delay, voltage in 347-357 VAC range

Step 9: Increase R-phase voltage till UV LED turns OFF
        Expected: Relay turns ON after 5s delay
```

---

## 🚀 NEXT STEPS (PRIORITY ORDER)

### **IMMEDIATE (This Week)**

#### 1. Fix Block Segmentation Issues ⚠️ HIGH PRIORITY
**Problem:** Some machines not segmenting correctly (user reported)
**File:** `block_segmenter.py` or use `block_segmenter_SMART.py`
**Action Required:**
- Debug specific machines that fail
- Test on full PDF
- Verify all 8-10 machines segment properly

#### 2. Remove Useless Text File Generation 🗑️
**Problem:** System generates ext_abc_MACHINE.txt files (useless clutter)
**File:** `main.py` lines 165-190
**Action Required:**
```python
# Comment out entire text file generation block
# Keep only Excel generation
```

#### 3. Switch from Voltage Specs to Test Procedures ⭐ CRITICAL
**Current:** Using `spec_parser.py` → voltage specs
**Target:** Using `template_builder.py` → test procedures

**Files to Modify:**
- `main.py` line 140-163 (replace spec_parser with template_builder)
- Update Excel generation to use test procedure data

**Steps:**
a. Import `template_builder.py` instead of `spec_parser.py`
b. Call `build_template_skeleton(block)` for each block
c. Pass TestSteps to Excel writer
d. Test output format

---

### **SHORT TERM (Next 2 Weeks)**

#### 4. Create Excel Template for Test Procedures
**Need:** `templates/test_procedure_template.xlsx`
**Structure:**
```
Sheet: Product_Name
Columns:
- Step Number
- Action
- Expected Behavior
- Relay Status
- LED Indicator
- Delay (seconds)
- Pass/Fail (checkbox)
```

#### 5. Test & Validate Output
- Run on full 20-page PDF
- Verify 8-10 Excel files generated
- Check test steps are complete
- Ensure no data loss

#### 6. Convert Excel to JSON (if needed)
**File:** `excel_json_converter.py`
**Use Case:** If frontend/database needs JSON instead of Excel
**Function:** `convert_excel_to_json(excel_path)`

---

### **MEDIUM TERM (Month 1-2)**

#### 7. Frontend Improvements
**Current:** Basic HTML + vanilla JavaScript
**Target:** Modern React/Vue interface (user mentioned)

**Features Needed:**
- Drag & drop PDF upload
- Real-time extraction progress
- Preview extracted procedures
- Download individual or bulk Excel files
- Search/filter by machine name

#### 8. Database Integration
**Store:**
- Extraction metadata
- Machine names
- Timestamps
- File paths

**Benefits:**
- Query historical extractions
- Analytics (most extracted machines)
- User management (if multi-tenant)

#### 9. AI-Powered Improvements
**Ideas:**
- Use LLM to improve step extraction
- Auto-detect action vs expected result
- Handle non-standard formats
- Suggest corrections for ambiguous steps

---

### **LONG TERM (Month 3+)**

#### 10. Multi-Language Support
If manuals come in languages other than English

#### 11. Template Customization
Allow users to define their own Excel templates

#### 12. Batch Processing
Upload multiple PDFs at once

#### 13. API for External Systems
RESTful API for MES/ERP integration

---

## 🐛 KNOWN ISSUES & BUGS

### **Critical Issues**

1. **Block Segmentation Failures** 🔴
   - **Status:** User reported "some sheets not yet correct"
   - **Impact:** Some machines missing or incorrectly segmented
   - **Files:** `block_segmenter.py`, `block_segmenter_SMART.py`
   - **Next Step:** Debug with actual PDF, identify failing patterns

2. **Useless Text File Clutter** 🟡
   - **Status:** Generates ext_abc_MACHINE.txt files
   - **Impact:** Confusing users, wasting disk space
   - **Fix:** Comment out lines 165-190 in main.py

3. **Wrong Deliverable** 🟡
   - **Status:** Extracting voltage specs instead of test procedures
   - **Impact:** Not solving the actual problem
   - **Fix:** Switch to template_builder.py

### **Minor Issues**

4. **Excel Template Missing** 🟡
   - Need `test_procedure_template.xlsx` for proper output

5. **No Error Recovery** 🟡
   - If one machine fails, entire extraction fails
   - Should continue processing other machines

6. **No Progress Indication** 🟡
   - User can't see extraction progress
   - Add WebSocket or polling endpoint

---

## 💡 DESIGN DECISIONS & RATIONALE

### Why Unique Extraction IDs?
- Prevents filename collisions
- Easy to track processing history
- URL-safe identifiers for API

Format: `ext_` + 8 hex chars = `ext_abc12345`

### Why Block Segmentation?
Manufacturing PDFs contain 8-10 different products. Each product needs separate processing and Excel file.

### Why MIN_BLOCK_SIZE = 1000?
Prevents splitting too early. Some section headers appear multiple times (e.g., "MG63BF" appears in text and as header). 1000 chars ensures we capture full sections.

### Why Two Extraction Paths?
- **Voltage Specs:** Useful for engineers/designers
- **Test Procedures:** Needed by factory operators
- Both are valuable, but test procedures are PRIMARY goal

### Why Excel Output?
- Familiar to manufacturing operators
- Easy to print and bring to factory floor
- Can add checkboxes for pass/fail
- JSON is secondary (for digital systems)

---

## 🧪 TESTING INSTRUCTIONS

### Manual Testing

#### Test PDF Upload:
```bash
# Start server
cd backend
uvicorn main:app --reload

# Upload PDF via UI
# http://localhost:8000/

# Or via curl
curl -X POST "http://localhost:8000/api/extract" \
  -F "file=@test.pdf"
```

#### Test Block Segmentation:
```bash
cd backend
python tests/test_real_pdf.py
```

#### Test Table Extraction:
```bash
cd backend
python tests/test_table_extraction.py
```

#### Test Specific Machine:
```bash
cd backend
python tests/test_sppr_extraction.py
```

### Expected Results
For a 20-page PDF with 8 machines:
- 8 Excel files in `/outputs/`
- 1 metadata JSON in `/metadata/`
- No errors in console
- All machines correctly identified

---

## 📦 DEPENDENCIES

### Python Packages (requirements.txt)
```
fastapi==0.115.5
uvicorn[standard]==0.32.1
pdfplumber==0.11.4
pymupdf==1.24.13
pandas==2.2.3
openpyxl==3.1.5
python-multipart==0.0.20
python-dotenv==1.0.1
pydantic==2.10.3
```

### Why These Libraries?

**pdfplumber** - PDF text extraction (better table handling)
**pymupdf** - Fallback PDF extraction (faster, less accurate)
**pandas** - Data manipulation for specs
**openpyxl** - Excel file creation/editing
**fastapi** - Modern Python API framework
**pydantic** - Data validation & schemas

---

## 🔄 VERSION HISTORY

### Current Version: 1.0 (In Development)
- ✅ PDF upload working
- ✅ Text extraction working
- ⚠️ Block segmentation 75% working
- ✅ Voltage spec extraction working
- ❌ Test procedure extraction not integrated
- ❌ Excel template not created

### Planned Version: 2.0 (Production Ready)
- ✅ Block segmentation 100% working
- ✅ Test procedure extraction integrated
- ✅ Excel template created
- ✅ No text file clutter
- ✅ Proper error handling
- ✅ Progress indication

---

## 🎓 KEY CONCEPTS FOR NEW DEVELOPERS

### Understanding Manufacturing Test Procedures
A typical test procedure has:
1. **Setup** - Equipment needed, initial conditions
2. **Test Steps** - Numbered actions to perform
3. **Expected Results** - What should happen at each step
4. **Pass/Fail Criteria** - How to determine if test passed

Example:
```
Step 8: Reduce R-phase voltage till UV LED glows ON
Expected: Relay turns OFF after 5s, voltage = 347-357 VAC
Pass: ✓ Relay OFF, ✓ LED ON, ✓ Voltage in range
Fail: ✗ Any condition not met
```

### Block Segmentation Challenge
PDFs mix multiple products. Example:
```
Page 1-3: SPPR Testing (Product A)
Page 4-6: SM301 Testing (Product B)
Page 7-9: SM500 Testing (Product C)
...
```

Must split correctly without losing data.

### Table vs Procedure Data
**Tables (TABLE 2):**
- Reference specifications
- Voltage ranges
- Timing parameters
- Used by: Engineers

**Procedures (PROCEDURE section):**
- Step-by-step instructions
- What operator does
- What operator expects to see
- Used by: Factory operators

**THIS PROJECT'S GOAL: Extract PROCEDURES, not just tables**

---

## 📞 HANDOFF NOTES

### If Handing Off to Another Developer:

1. **Start Here:**
   - Read this README fully
   - Look at `main.py` to understand flow
   - Run `test_real_pdf.py` to see current output

2. **First Task:**
   - Fix block segmentation issues
   - Test with full PDF
   - Ensure all machines segment correctly

3. **Second Task:**
   - Remove text file generation
   - Keep only Excel output

4. **Third Task:**
   - Switch from voltage specs to test procedures
   - Integrate `template_builder.py` into main pipeline

5. **Key Files to Understand:**
   - `main.py` - Orchestrates everything
   - `block_segmenter.py` - Splits PDF (CRITICAL)
   - `template_builder.py` - Extracts procedures (TARGET)
   - `excel_template_writer.py` - Creates final output

6. **Don't Touch (Working Fine):**
   - `pdf_extractor.py`
   - `schemas.py`
   - Frontend files (for now)

---

## 🔑 CRITICAL SUCCESS FACTORS

For this project to succeed:

1. **Block Segmentation MUST work 100%**
   - If machines mix together, entire output is garbage
   - This is the foundation

2. **Test Procedure Extraction is the Real Goal**
   - Not voltage specs
   - Not table data
   - ONLY numbered test steps matter

3. **Excel Output Must be Operator-Friendly**
   - Clear columns
   - Easy to print
   - Checkboxes for pass/fail

4. **No Useless Outputs**
   - No text files
   - No intermediate data
   - Only final Excel files

---

## 📚 RELATED DOCUMENTATION

### For More Details See:
- `/backend/services/` - Each file has docstrings
- `/backend/tests/` - Example usage
- `requirements.txt` - Library documentation links

### External Resources:
- **pdfplumber docs:** https://github.com/jsvine/pdfplumber
- **FastAPI docs:** https://fastapi.tiangolo.com/
- **openpyxl docs:** https://openpyxl.readthedocs.io/

---

## ✅ QUICK START FOR NEW CHATBOT

**Copy-Paste This When Starting New Chat:**

```
I'm working on a manufacturing PDF extraction system. Here's what it does:

INPUT: 20-page PDF with test procedures for 8-10 different voltage relay products
OUTPUT: Individual Excel files for each product containing structured test steps

CURRENT STATUS:
- PDF extraction: ✅ Working
- Block segmentation: ⚠️ 75% working (some machines fail)
- Main issue: Currently extracting voltage specs, need to extract TEST PROCEDURES instead

KEY FILES:
- main.py: FastAPI backend (orchestrates everything)
- block_segmenter.py: Splits PDF into machine sections (HAS BUGS)
- template_builder.py: Extracts test procedures (NOT INTEGRATED)
- excel_template_writer.py: Creates Excel output

IMMEDIATE PROBLEMS:
1. Block segmentation failing for some machines
2. Generating useless text files (need to remove)
3. Using spec_parser.py but should use template_builder.py

GOAL:
Extract numbered test steps like:
"8. Reduce R-phase voltage till UV LED glows ON"
"Expected: Relay turns OFF after 5s delay"
```

## 🏁 FINAL NOTES

This project is **75% complete**. The core extraction pipeline works, but needs:
1. Bug fixes in block segmentation
2. Switch from voltage specs to test procedures
3. Excel template creation

Once these 3 items are done, the system will be **production-ready** for manufacturing use.

The biggest misalignment was building voltage spec extraction when the actual goal is test procedure extraction. `template_builder.py` already solves this but isn't integrated yet.

**Estimated time to production: 1-2 weeks** with focused effort on the 3 items above.
