import csv

with open("output_reports/final_picks_latest.csv", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        sym = r["Symbol"]
        g = r.get("EPS_Growth(%)", "?")
        s = r.get("Surprise(%)", "?")
        print(f"{sym}: Surprise={s}% | Growth={g}%")

print("\n=== daily_scan LITE row ===")
with open("output_reports/daily_scan_latest.csv", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r["Symbol"] == "LITE":
            print(f"LITE: Surprise={r['Surprise(%)']}% | Growth={r['EPS_Growth(%)']}%")
            print(f"GrowthReason: {r['GrowthReason']}")

print("\n✅ Growth 수정 확인 완료")
