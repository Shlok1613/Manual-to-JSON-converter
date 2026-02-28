"""
Block Segmentation Service - SMART TABLE-AWARE VERSION
Splits extracted PDF text into separate machine/product blocks.

KEY IMPROVEMENT:
- Won't split a block if it references tables that haven't appeared yet
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
    r"^(MG\d+[A-Z]+)(?:\s+product|:|\s+Functional|\s+CRITICALITY|\s+\(.+Testing)",  # MG + context (NOT bare "MG73BQ" table rows!)
    r"^PROCEDURE\s+FOR\s+(.+?):",                        # "PROCEDURE FOR DMS110:"
]

# Patterns that ALWAYS force a split, even if block is < MIN_BLOCK_SIZE
# These clearly indicate a new machine/procedure is starting
FORCE_SPLIT_PATTERNS = [
    r"^PROCESS:\s*(.+)",                                 # "PROCESS:" - top-level section
    r"^PROCEDURE\s+FOR\s+(.+?):",                        # "PROCEDURE FOR" - explicit procedure start
    r"^For\s+(MG\d+[A-Z]+)\s+product",                   # "For MG73BQ product" - always marks new product
]

# Regex to find machine names in text
MACHINE_NAME_PATTERN = re.compile(
    r'\b(SPPR|SM\d+_[A-Z]|SM\d+|DSMR|DMS\d+|DMA\d+|MAG\w+|MAC\w+|MG\d+\w+|MD\d+\w+|MB\d+\w+)\b',
    re.IGNORECASE
)


def find_machine_name(text: str, fallback: str = "UNKNOWN") -> str:
    """Extract machine/product name from text."""
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


def segment_blocks(full_text: str) -> List[Dict[str, str]]:
    """
    Split full PDF text into separate blocks for each machine/product.
    
    SMART LOGIC:
    1. Uses minimum block size (1000 chars) to avoid tiny fragments
    2. Checks for incomplete table references before splitting
    3. Won't split if block references tables that haven't appeared yet
    
    This ensures tables are always included in their machine's block,
    regardless of where they appear in the text.
    
    Args:
        full_text: Complete extracted text from PDF
    
    Returns:
        List of blocks, each containing one machine's complete text
    """
    lines = full_text.splitlines()
    blocks = []
    
    # Minimum characters for a valid block (to avoid tiny fragments)
    MIN_BLOCK_SIZE = 1000
    
    # Start with first block
    current_block = {
        "machine": "MACHINE_1",
        "header": "",
        "text": ""
    }
    
    for line in lines:
        line_stripped = line.strip()
        
        # Skip empty lines but preserve them in text
        if not line_stripped:
            current_block["text"] += "\n"
            continue
        
        # Check if this line is a section header
        is_new_section = False
        for pattern in SECTION_PATTERNS:
            match = re.search(pattern, line_stripped, flags=re.IGNORECASE)
            if match:
                # Check if we should start new section
                block_size = len(current_block["text"].strip())
                
                # Check if this is a FORCE SPLIT pattern (always splits)
                is_force_split = any(
                    re.search(force_pattern, line_stripped, flags=re.IGNORECASE)
                    for force_pattern in FORCE_SPLIT_PATTERNS
                )
                
                # Conditions to ALLOW split:
                # 1. Current block is empty (always start first block)
                # 2. Block is large enough AND doesn't have incomplete table references
                # 3. OR this is a FORCE SPLIT pattern (ignores size check!)
                
                allow_split = (
                    not current_block["text"].strip() or  # Empty block
                    is_force_split or  # FORCE SPLIT patterns always allowed!
                    (
                        block_size > MIN_BLOCK_SIZE and  # Large enough
                        not has_incomplete_table_reference(current_block["text"])  # No incomplete refs
                    )
                )
                
                if allow_split:
                    # Save previous block (if it has content)
                    if current_block["text"].strip():
                        blocks.append(current_block)
                        logger.info(f"Completed block: {current_block['machine']} ({len(current_block['text'])} chars)")
                    
                    # Start new block
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
                    logger.info(f"New section detected: {machine_name}")
                    break
                else:
                    # Don't split - current block too small or has incomplete table refs
                    if block_size <= MIN_BLOCK_SIZE:
                        logger.debug(f"Block too small ({block_size} chars), continuing...")
                    else:
                        logger.info(f"Block has incomplete table reference, continuing...")
                    break
        
        # If not a section header, add to current block
        if not is_new_section:
            current_block["text"] += line_stripped + "\n"
    
    # Don't forget the last block!
    if current_block["text"].strip():
        blocks.append(current_block)
        logger.info(f"Completed final block: {current_block['machine']} ({len(current_block['text'])} chars)")
    
    # Clean up machine names (remove duplicates, number them)
    machine_counts = {}
    for block in blocks:
        machine = block["machine"]
        
        # Count occurrences
        machine_counts[machine] = machine_counts.get(machine, 0) + 1
        
        # If duplicate, add number
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