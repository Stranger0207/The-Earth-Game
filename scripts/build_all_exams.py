# -*- coding: utf-8 -*-
"""
Generator for EARTH_GAME_ENTRANCE_EXAMS.md
Generates all 39 countries with 5 rigorous tests per country.
"""

import os
import sys

DESKTOP_PATH = r"C:\Users\ARASH\Desktop\EARTH_GAME_ENTRANCE_EXAMS.md"

def main():
    import scripts.exams_data.builder as b
    content = b.build_full_document()
    with open(DESKTOP_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Successfully generated {len(content)} characters in {DESKTOP_PATH}")

if __name__ == "__main__":
    main()
