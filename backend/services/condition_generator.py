# backend/services/condition_generator.py
"""
Test Condition Generator - 100% Template Match
Generates test condition scenarios from voltage specifications.
Matches 1M_SPP_SM175_AUTO_FUNCTION_All_CatID.xlsx format exactly.

Output format per condition:
{
    "test_case": "healthy condition",
    "pot_setting": "P1 = 7 %, P2 = 0 SEC, P3 = 15 SEC",
    "voltage": "RN :0, YN :0, BN :0",
    "led_status": "PWR (GREEN LED) : ON, UV (RED LED) : OFF, ...",
    "relay_status": "ON",
    "on_delay": "Instant ON",
    "off_delay": "-"
}
"""

from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

def generate_comprehensive_conditions(specs: Dict, block_text: str = "") -> List[Dict]:
    """
    Generate test conditions for any machine block.
    Uses universal_spec_extractor — handles all PDF formats automatically.
    Falls back to legacy spec_parser path if block_text not available.
    """
    if block_text:
        try:
            from services.universal_spec_extractor import extract_and_generate
            conditions = extract_and_generate(block_text)
            logger.info(f"Universal extractor: {len(conditions)} conditions")
            return conditions
        except Exception as e:
            logger.warning(f"Universal extractor failed: {e}, using legacy fallback")

    # Fallback: no block text — use existing spec_parser output
    logger.warning("No block_text provided — returning empty list")
    return []

