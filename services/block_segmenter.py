# backend/services/block_segmenter.py

"""
Block Segmentation Service - SMART TABLE-AWARE VERSION
Splits extracted PDF text into separate machine/product blocks.

KEY IMPROVEMENTS:
- Won't split a block if it references tables that haven't appeared yet
- Uses UniversalPatternLibrary for machine name detection (MAG, MAC, MG, SM, etc.)
- This prevents cutting off blocks before their TABLE sections appear
- Works generically for ANY machine with similar layout
"""
import re
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

# Patterns that indicate a new section/machine is starting
# IMPORTANT: Order matters! More specific patterns should come FIRST
SECTION_PATTERNS = [
    r"^Neutral\s+Open\s+SPPR",                           # "Neutral Open SPPR"
    r"^PROCESS:\s*(.+)",                                 # "PROCESS: Functional Testing"
    r"^(SM\d+_[A-Z])\s+Functional\s+Testing",            # "SM501_B Functional Testing" (before generic SM pattern!)
    r"^(SM\d+)\s+(.+Testing)",                           # "SM301 AUTOMATED FUNCTIONAL TESTING"
    r"^(SM\d+)\s+Functional\s+Testing",                  # "SM500 Functional Testing"
    r"^Process:\s+Functional\s+Testing\s+(SM\d+)",       # "Process: Functional Testing SM500_A"
    r"^PROCESS\s*:\s*Functional\s+Testing\s+DSMR",       # "PROCESS : Functional Testing DSMR"
    r"^Functional\s+Testing\s+table\s+for\s+(\w+)",      # "Functional Testing table for Daikin"
    r"^For\s+(MG\d+[A-Z]+)\s+product",                   # "For MG73BQ product" - section boundary for MG variants
    r"^(DMS\d+)",                                         # "DMS110", "DMS120", etc.
    r"^(MG\d+[A-Z]+)(?:\s+product|:|\s+Functional|\s+CRITICALITY|\s+\(.+Testing)",  # MG + context
    r"^PROCEDURE\s+FOR\s+(.+?):",                        # "PROCEDURE FOR DMS110:"
    # Additional patterns for broader coverage
    r"FUNCTIONAL\s+TEST\s+PROCEDURE\s+FOR\s+([A-Z0-9][A-Z0-9_]{2,})",  # "FUNCTIONAL TEST PROCEDURE FOR SPPR"
    r"^([A-Z0-9][A-Z0-9_]{2,})\s+(?:AUTOMATED\s+)?FUNCTIONAL\s+TESTING",  # "SM500 FUNCTIONAL TESTING"
    r"([A-Z]{2,})PROCESS\s*:\s*Functional",              # "SPPRPROCESS: Functional"
    r"PROCESS\s*:\s*Functional\s+Testing\s+([A-Z0-9][A-Z0-9_]{2,})",  # "PROCESS: Functional Testing SM500_A"
]

# Patterns that ALWAYS force a split, even if block is < MIN_BLOCK_SIZE
FORCE_SPLIT_PATTERNS = [
    r"^PROCESS:\s*(.+)",                                 # "PROCESS:" - top-level section
    r"^PROCEDURE\s+FOR\s+(.+?):",                        # "PROCEDURE FOR" - explicit procedure start
    r"^For\s+(MG\d+[A-Z]+)\s+product",                   # "For MG73BQ product" - always marks new product
]

# Valid machine name prefixes (filters false positives)
VALID_PREFIXES = {'SPPR', 'SM', 'MG', 'DMS', 'DMA', 'DSMR', 'MAC', 'MAG', 'MB'}

def is_valid_machine_name(name: str) -> bool:
    """Check if name matches a valid machine name pattern."""
    name = name.upper()
    return 3 <= len(name) <= 15 and any(name.startswith(p) for p in VALID_PREFIXES)

def has_table_spec(block_text: str) -> bool:
    """Check if a block contains actual test specification tables."""
    return bool(re.search(
        r'TABLE\s*\d?\s*\(PRODUCT\s*SETTINGS'
        r'|Under\s*Voltage\s*\(UV\).*?\d+\s+to\s+\d+\s+VAC',
        block_text, re.I | re.DOTALL
    ))

# Use pattern library for machine detection
MACHINE_NAME_PATTERN = re.compile(
    r'\b(SPPR|SM\d+_[A-Z]|SM\d+|DSMR|DMS\d+|DMA\d+|MAG\w+|MAC\w+|MG\d+\w+|MD\d+\w+|MB\d+\w+)\b',
    re.IGNORECASE
)

# SCOPE pattern for WI-format PDFs (e.g., "SCOPE : MAG03D0424 / MAG03D0425")
SCOPE_PATTERN = re.compile(r'SCOPE\s*:\s*([\w/\s]+)', re.IGNORECASE)


def find_machine_name(text: str, fallback: str = "UNKNOWN") -> str:
    """Extract machine/product name from text.
    
    Checks:
    1. SCOPE line (WI-format) - extracts first MAG/MAC name from SCOPE
    2. Direct machine name match in text
    """
    # Check SCOPE line first (WI-format PDFs)
    scope_match = SCOPE_PATTERN.search(text)
    if scope_match:
        scope_text = scope_match.group(1)
        # Find first MAG/MAC name in scope
        machine_match = MACHINE_NAME_PATTERN.search(scope_text)
        if machine_match:
            return machine_match.group(1).upper()
    
    # Standard machine name detection
    match = MACHINE_NAME_PATTERN.search(text)
    if match:
        return match.group(1).upper()
    return fallback


def has_incomplete_table_reference(text: str) -> bool:
    """
    Check if text has VERY RECENT table references that haven't appeared yet.
    
    Only blocks splits if table was referenced in the LAST 200 CHARS.
    This is strict enough to catch "refer table below" → TABLE situations,
    but loose enough to not block splits for old/external table references.
    
    Returns:
        True if last 200 chars has table reference but no table structure anywhere
        False otherwise
    """
    # Only check the last 200 chars for very recent references
    recent_text = text[-200:] if len(text) > 200 else text
    recent_upper = recent_text.upper()
    
    # Check for table references in recent text
    has_reference = bool(
        re.search(r'REFER\s+(?:THE\s+)?(?:FOLLOWING\s+)?TABLES?', recent_upper) or
        re.search(r'(?:TABLE|TABLES)\s+(?:BELOW|GIVEN|1|2|01|02)', recent_upper) or
        re.search(r'AS\s+PER\s+TABLE', recent_upper)
    )
    
    if not has_reference:
        return False  # No very recent references, OK to split
    
    # Check if actual table structures exist in FULL text
    text_upper = text.upper()
    has_table_structure = bool(
        re.search(r'TABLE\s+\d+\s*\(', text_upper) or  # "TABLE 1 ("
        re.search(r'TABLE\s+\(', text_upper) or         # "TABLE ("
        re.search(r'TABLE\s+0\d\s*:', text_upper)       # "TABLE 01:"
    )
    
    if has_table_structure:
        return False  # Has both reference AND structure, OK to split
    
    # Has VERY RECENT reference (< 200 chars) but no structure
    logger.info(f"Block has very recent incomplete table reference (in last 200 chars) - preventing split")
    return True


def segment_blocks(full_text: str, user_names: list = None) -> List[Dict[str, str]]:

    # Validate user names against actual PDF text
    if user_names:
        user_names = [
            n for n in user_names
            if re.search(rf'\b{re.escape(n)}\b', full_text, re.IGNORECASE)
        ]
        if not user_names:
            user_names = None

    # Always use proven SECTION_PATTERNS for splitting — never dynamic patterns
    lines = full_text.splitlines()
    blocks = []
    MIN_BLOCK_SIZE = 1000
    current_block = {"machine": "MACHINE_1", "header": "", "text": ""}

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            current_block["text"] += "\n"
            continue

        is_new_section = False
        for pattern in SECTION_PATTERNS:
            match = re.search(pattern, line_stripped, flags=re.IGNORECASE)
            if match:
                block_size = len(current_block["text"].strip())
                is_force_split = any(
                    re.search(fp, line_stripped, flags=re.IGNORECASE)
                    for fp in FORCE_SPLIT_PATTERNS
                )
                allow_split = (
                    not current_block["text"].strip() or
                    is_force_split or
                    (block_size > MIN_BLOCK_SIZE and
                     not has_incomplete_table_reference(current_block["text"]))
                )
                if allow_split:
                    if current_block["text"].strip():
                        blocks.append(current_block)
                    header_text = match.group(0)
                    machine_name = find_machine_name(
                        header_text,
                        fallback=f"MACHINE_{len(blocks) + 1}"
                    )
                    current_block = {
                        "machine": machine_name,
                        "header": header_text,
                        "text": line_stripped + "\n"
                    }
                    is_new_section = True
                    break
                else:
                    break

        if not is_new_section:
            current_block["text"] += line_stripped + "\n"

    if current_block["text"].strip():
        blocks.append(current_block)

    # POST-PROCESSING Step 0: Merge short blocks
    MIN_MERGE_LENGTH = 1500
    merged = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if (len(block["text"]) < MIN_MERGE_LENGTH and
                not has_table_spec(block["text"]) and
                i + 1 < len(blocks)):
            next_block = blocks[i + 1]
            merged.append({
                "machine": block["machine"],
                "header": block.get("header", ""),
                "text": block["text"] + next_block["text"]
            })
            i += 2
        else:
            merged.append(block)
            i += 1
    blocks = merged

    # POST-PROCESSING Step 1: Rename MACHINE_X blocks from block text
    for block in blocks:
        if block["machine"].startswith("MACHINE_"):
            real_name = find_machine_name(block["text"], fallback=block["machine"])
            if real_name != block["machine"]:
                block["machine"] = real_name

    # POST-PROCESSING Step 2: If user gave names, filter AND merge by machine name
    if user_names:
        user_names_upper = [n.upper() for n in user_names]

        # Keep only blocks whose auto-detected name matches a user-provided name
        matching = [
            b for b in blocks
            if b["machine"].upper() in user_names_upper
        ]

        # Merge all blocks with the same machine name into one block
        merged_by_name = {}
        for block in matching:
            name = block["machine"].upper()
            if name not in merged_by_name:
                merged_by_name[name] = {
                    "machine": name,
                    "header": block["header"],
                    "text": block["text"]
                }
            else:
                merged_by_name[name]["text"] += "\n" + block["text"]

        # Preserve user-input order
        blocks = [
            merged_by_name[n] for n in user_names_upper
            if n in merged_by_name
        ]
        logger.info(f"After user-name filter+merge: {[b['machine'] for b in blocks]}")

    # POST-PROCESSING Step 3: SCOPE-based documents (auto-detect only)
    else:
        from collections import Counter
        name_counts = Counter(b["machine"] for b in blocks)
        most_common_name, most_common_count = name_counts.most_common(1)[0]
        if len(blocks) > 3 and most_common_count / len(blocks) >= 0.7:
            combined_text = "\n".join(b["text"] for b in blocks)
            scope_match = SCOPE_PATTERN.search(combined_text)
            if scope_match:
                scope_text = scope_match.group(1)
                scope_products = re.findall(
                    r'(MAG\d+[A-Z0-9]+|MAC\d+[A-Z0-9]+|SM\d+_[A-Z]|SM\d+|MG\d+[A-Z]+)',
                    scope_text, re.IGNORECASE
                )
                scope_products = list(dict.fromkeys(p.upper() for p in scope_products))
                if len(scope_products) > 1:
                    blocks = [
                        {"machine": prod, "header": f"SCOPE: {prod}", "text": combined_text}
                        for prod in scope_products
                    ]
                    return blocks

    # POST-PROCESSING Step 4: Deduplicate names (auto-detect only)
    if user_names is None:
        machine_counts = {}
        for block in blocks:
            machine = block["machine"]
            machine_counts[machine] = machine_counts.get(machine, 0) + 1
            if machine_counts[machine] > 1:
                block["machine"] = f"{machine}_{machine_counts[machine]}"
    
    # POST-PROCESSING Step 3: Clean up duplicate names (non-SCOPE documents)
    machine_counts = {}
    for block in blocks:
        machine = block["machine"]
        machine_counts[machine] = machine_counts.get(machine, 0) + 1
        if machine_counts[machine] > 1:
            block["machine"] = f"{machine}_{machine_counts[machine]}"
    
    logger.info(f"Segmentation complete: {len(blocks)} blocks found")
    
    return blocks


def get_block_summary(blocks: List[Dict[str, str]]) -> str:
    """
    Create a human-readable summary of all blocks.
    
    Useful for debugging and showing user what was found.
    """
    summary = f"Found {len(blocks)} blocks:\n"
    
    for i, block in enumerate(blocks, 1):
        text_length = len(block["text"])
        header = block["header"][:50] + "..." if len(block["header"]) > 50 else block["header"]
        
        summary += f"{i}. {block['machine']}: {header} ({text_length:,} chars)\n"
    
    return summary