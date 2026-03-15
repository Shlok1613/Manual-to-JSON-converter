# backend/services/pattern_library.py
"""
Universal Pattern Library
Central repository of ALL regex patterns for machine detection and test extraction.
Zero hardcoding — everything dynamic and extensible.
"""
import re
from typing import List, Dict, Optional, Tuple


class UniversalPatternLibrary:
    """Comprehensive patterns for all machine types and test sections."""

    # ========================================================================
    # MACHINE NAMING PATTERNS (checked in order — specific before general)
    # ========================================================================
    MACHINE_PATTERNS = [
        # GIC Products (MAG / MAC)
        r'\b(MAG\d{2}[A-Z]\d{4}(?:EG|RS|\d{2})?)\b',
        r'\b(MAC\d{2}[A-Z]\d{4})\b',
        # MG / MD / MB series
        r'\b(MG\d{2}[A-Z]{2,3})\b',
        r'\b(MD\d{2}[A-Z]{2})\b',
        r'\b(MB\d{2}[A-Z]{2})\b',
        # SM Series (variants before base)
        r'\b(SM\d{3}_[A-Z])\b',
        r'\b(SM\d{3})\b',
        # Special products
        r'\b(SPPR)\b',
        r'\b(DSMR)\b',
        # DMS / DMA series
        r'\b(DMS\d{3,5})\b',
        r'\b(DMA\d{3,5})\b',
    ]

    COMPILED_MACHINE_PATTERNS = [re.compile(p, re.IGNORECASE) for p in MACHINE_PATTERNS]

    # Unified machine name extractor
    MACHINE_NAME_REGEX = re.compile(
        r'\b('
        r'MAG\d{2}[A-Z]\d{4}(?:EG|RS|\d{2})?|'
        r'MAC\d{2}[A-Z]\d{4}|'
        r'MG\d{2}[A-Z]{2,3}|'
        r'MD\d{2}[A-Z]{2}|'
        r'MB\d{2}[A-Z]{2}|'
        r'SM\d{3}_[A-Z]|SM\d{3}|'
        r'SPPR|DSMR|'
        r'DMS\d{3,5}|DMA\d{3,5}'
        r')\b',
        re.IGNORECASE
    )

    # ========================================================================
    # SECTION HEADER PATTERNS (for block segmentation)
    # ========================================================================
    SECTION_PATTERNS = [
        r"^Neutral\s+Open\s+SPPR",
        r"^PROCESS:\s*(.+)",
        r"Functional\s+Testing\s+of\s+(\S+)\s+product",
        r"Functional Testing\s+FOR\s+(\S+)\s+PRODUCT",
        r"^FOR\s+(%s)\s+PRODUCT" % r'MG\d+\w+|SM\d+_[A-Z]|SM\d+|DMS\d+|SPPR|DSMR',
        r"^PROCEDURE\s+FOR\s+(.+?):",
        # MAG/MAC patterns
        r'\bSCOPE\s*:\s*(MAG\d+[A-Z0-9/\s]+)',
    ]

    # ========================================================================
    # TEST SECTION DETECTION
    # ========================================================================
    PHASE_FAIL_PATTERNS = [
        re.compile(r'PHASE\s+FAIL(?:URE)?\s+VERIFICATION\s*:', re.IGNORECASE),
        re.compile(r'PHASE\s+LOSS\s+(?:TEST|VERIFICATION)\s*:', re.IGNORECASE),
    ]

    PHASE_REVERSE_PATTERNS = [
        re.compile(r'PHASE\s+REVERSE(?:AL)?\s+VERIFICATION\s*:', re.IGNORECASE),
        re.compile(r'PHASE\s+SEQUENCE\s+(?:TEST|VERIFICATION)\s*:', re.IGNORECASE),
    ]

    NEUTRAL_FAIL_PATTERNS = [
        re.compile(r'(?:SYSTEM\s+)?N(?:E)?UTRAL\s+FAIL(?:URE)?\s+VERIFICATION\s*:', re.IGNORECASE),
        re.compile(r'VIRTUAL\s+N(?:E)?UTRAL\s+FAIL\s+VERIFICATION\s*:', re.IGNORECASE),
        re.compile(r'Neutral\s+Fail(?:ure)?\s*\(', re.IGNORECASE),
    ]

    # Numbered step pattern
    STEP_PATTERN = re.compile(r'^\s*(\d+)\.\s+(.+?)$', re.MULTILINE)

    # Value extraction patterns
    RELAY_PATTERN = re.compile(
        r'relay\s+turns?\s*(ON|OFF)(?:\s+(?:after|in|within)\s+(?:specified\s+)?(\w+\s*\w*?))?',
        re.IGNORECASE
    )
    LED_BLINK_PATTERN = re.compile(r"'?(\w+)'?\s+(?:LED\s+)?(?:indication\s+)?(?:starts?\s+)?(?:flash|blink)", re.IGNORECASE)
    LED_ON_PATTERN = re.compile(r"'?(\w+)'?\s+(?:LED\s+|indication\s+)?turns?\s+ON", re.IGNORECASE)
    PHASE_DETECT = re.compile(r'([RYB])-?phase', re.IGNORECASE)
    DELAY_MS_PATTERN = re.compile(r'(\d+)\s*ms', re.IGNORECASE)
    DELAY_SEC_PATTERN = re.compile(r'(\d+(?:\.\d+)?)\s*(?:to|-)\s*(\d+(?:\.\d+)?)\s*(?:sec|s)\b', re.IGNORECASE)
    VOLTAGE_RANGE = re.compile(r'(\d+)\s*(?:to|-)\s*(\d+)\s*V', re.IGNORECASE)

    @classmethod
    def find_machine_name(cls, text: str) -> Optional[str]:
        """Find the most specific machine name in text."""
        # Try each pattern in priority order
        for pattern in cls.COMPILED_MACHINE_PATTERNS:
            m = pattern.search(text)
            if m:
                return m.group(1).upper()
        return None

    @classmethod
    def find_all_machines(cls, text: str) -> List[str]:
        """Find all unique machine names."""
        found = set()
        for pattern in cls.COMPILED_MACHINE_PATTERNS:
            for m in pattern.finditer(text):
                found.add(m.group(1).upper())
        return sorted(found, key=lambda x: (len(x), x), reverse=True)

    @classmethod
    def find_section_content(cls, text: str, patterns: List[re.Pattern]) -> List[str]:
        """Find all sections matching patterns, return content after each header."""
        sections = []
        for pat in patterns:
            for m in pat.finditer(text):
                start = m.end()
                # Find end: next uppercase section header or next numbered process
                end_match = re.search(
                    r'\n(?:[A-Z][A-Z\s]{8,}:|PROCEDURE\s+FOR|\d+\.\s+PROCESS:)',
                    text[start:]
                )
                end = start + end_match.start() if end_match else min(start + 2000, len(text))
                sections.append(text[start:end].strip())
        return sections
