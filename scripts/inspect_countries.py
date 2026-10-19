import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
with open("data/countries.json", encoding="utf-8") as f:
    data = json.load(f)["countries"]

print(f"Total countries: {len(data)}")
for i, c in enumerate(data, 1):
    print(f"{i:2d}. {c.get('flag')} {c.get('name_fa')} ({c.get('name_en')}) - VIP: {c.get('is_vip', False)} - Region: {c.get('region')}")
