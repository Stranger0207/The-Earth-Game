"""
اجرای بیلد و کش داده‌های سازنده تجهیزات نظامی در data/equipment_origins.json
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.build_equipment_origins import OUTPUT_FILE, build_origins
import json

def main():
    origins = build_origins()
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(origins, f, ensure_ascii=False, indent=2)
    print(f"✅ Successfully mapped {len(origins)} equipment origins to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
