"""Read-only Phase B selection from independently scored Pre-Watch JSON."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from .market_schedule import plan_awatch_market_checks


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--lookahead-minutes", type=int, default=10)
    args = p.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("meetings"), list):
        raise SystemExit("BLOCKED: verified Pre-Watch meetings list required")
    result = plan_awatch_market_checks(data["meetings"],
                                      now=datetime.now(timezone.utc),
                                      lookahead_minutes=args.lookahead_minutes)
    result["market_collection_status"] = "NOT_COLLECTED"
    result["bet_authorized"] = False
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
