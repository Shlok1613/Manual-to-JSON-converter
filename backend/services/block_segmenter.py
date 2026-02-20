"""
Block Segmentation Service
Splits extracted PDF text into separate machine/product blocks.

Example:
    Input: Full PDF text (7 machines mixed together)
    Output: List of 7 blocks, one per machine
"""
import re
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

# Patterns that indicate a new section/machine is starting
SECTION_PATTERNS = [
    r"^Neutral\s+Open\s+SPPR",                           # "Neutral Open SPPR"
    r"^PROCESS:\s*(.+)",                                 # "PROCESS: Functional Testing"
    r"^(SM\d+)\s+(.+Testing)",                           # "SM301 AUTOMATED FUNCTIONAL TESTING"
    r"^(SM\d+)\s+Functional\s+Testing",                  # "SM500 Functional Testing"
    r"^Process:\s+Functional\s+Testing\s+(SM\d+)",       # "Process: Functional Testing SM500_A"
    r"^(SM\d+_[A-Z])\s+Functional\s+Testing",            # "SM501_B Functional Testing"
    r"^PROCESS\s*:\s*Functional\s+Testing\s+DSMR",       # "PROCESS : Functional Testing DSMR"
    r"^Functional\s+Testing\s+table\s+for\s+(\w+)",      # "Functional Testing table for Daikin"
    r"^(DMS\d+)",                                         # "DMS110", "DMS120", etc.
    r"^(MG\d+[A-Z]+)",                                    # "MG63BF", "MG53BH", etc.
    r"^PROCEDURE\s+FOR\s+(.+?):",                        # "PROCEDURE FOR DMS110:"
]
# Regex to find machine names in text
MACHINE_NAME_PATTERN = re.compile(
    r'\b(SPPR|SM\d+|DSMR|DMS\d+|DMA\d+|MAG\w+|MAC\w+|MG\d+\w+|MD\d+\w+|MB\d+\w+)\b',
    re.IGNORECASE
)


def find_machine_name(text: str, fallback: str = "UNKNOWN") -> str:
    """
    Extract machine/product name from text.
    
    Examples:
        "PROCESS: Functional Testing - Neutral Open SPPR"
        → Returns: "SPPR"
        
        "SM301 AUTOMATED FUNCTIONAL TESTING"
        → Returns: "SM301"
        
        "Functional Test for MAG03D0424"
        → Returns: "MAG03D0424"
    
    Args:
        text: Text to search
        fallback: What to return if no machine name found
    
    Returns:
        Machine name (uppercase) or fallback
    """
    match = MACHINE_NAME_PATTERN.search(text)
    if match:
        return match.group(1).upper()
    return fallback


def segment_blocks(full_text: str) -> List[Dict[str, str]]:
    """
    Split full PDF text into separate blocks for each machine/product.
    
    Improved version: Minimum block size to avoid over-segmentation.
    
    Args:
        full_text: Complete extracted text from PDF
    
    Returns:
        List of blocks
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
                # Only start new section if current block is big enough
                # OR if it's completely empty
                if len(current_block["text"].strip()) > MIN_BLOCK_SIZE or not current_block["text"].strip():
                    
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
                    # Current block too small, keep adding to it
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
    """
    Split full PDF text into separate blocks for each machine/product.
    
    How it works:
    1. Read line by line
    2. When we see a section header → start new block
    3. Add all following lines to that block
    4. Until we see next section header
    
    Args:
        full_text: Complete extracted text from PDF
    
    Returns:
        List of blocks, each block is:
        {
            "machine": "MAC04D0100",
            "header": "PROCESS: Functional Testing",
            "text": "Full text for this machine..."
        }
    
    Example:
        blocks = segment_blocks(pdf_text)
        print(f"Found {len(blocks)} machines")
        for block in blocks:
            print(f"- {block['machine']}")
    """
    lines = full_text.splitlines()
    blocks = []
    
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
                # This is a new section!
                
                # Save previous block (if it has content)
                if current_block["text"].strip():
                    blocks.append(current_block)
                    logger.info(f"Completed block: {current_block['machine']}")
                
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
        
        # If not a section header, add to current block
        if not is_new_section:
            current_block["text"] += line_stripped + "\n"
    
    # Don't forget the last block!
    if current_block["text"].strip():
        blocks.append(current_block)
        logger.info(f"Completed final block: {current_block['machine']}")
    
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
    
    Args:
        blocks: List of blocks from segment_blocks()
    
    Returns:
        Formatted string summary
    
    Example:
        summary = get_block_summary(blocks)
        print(summary)
        # Output:
        # Found 7 blocks:
        # 1. SPPR (1,234 chars)
        # 2. SM301 (567 chars)
        # ...
    """
    summary = f"Found {len(blocks)} blocks:\n"
    
    for i, block in enumerate(blocks, 1):
        text_length = len(block["text"])
        header = block["header"][:50] + "..." if len(block["header"]) > 50 else block["header"]
        
        summary += f"{i}. {block['machine']}: {header} ({text_length:,} chars)\n"
    
    return summary