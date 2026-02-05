from typing import List, Dict

def segment_functional_test_blocks(pages: List[str]) -> List[Dict]:
    """
    Segments extracted PDF text into functional test blocks.
    Each block corresponds to one PROCESS: Functional Testing section.
    """
    full_text = "\n".join(pages)
    lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]

    blocks = []
    current_block = None

    for line in lines:
        if "PROCESS:" in line and "Functional Testing" in line:
            # Save previous block
            if current_block:
                blocks.append(current_block)

            # Extract title
            raw = line.replace("PROCESS:", " PROCESS:")
            parts = raw.split(" PROCESS:")
            title = parts[0].strip() if parts[0].strip() else "UNNAMED_BLOCK"

            current_block = {
                "block_id": f"BLOCK_{len(blocks) + 1}",
                "title": title,
                "text_lines": []
            }

        if current_block:
            current_block["text_lines"].append(line)

    if current_block:
        blocks.append(current_block)

    for block in blocks:
        block["text"] = "\n".join(block["text_lines"])
        del block["text_lines"]

    return blocks
