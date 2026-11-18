from __future__ import annotations

import argparse

from app.database import initialize_database, replace_readings


def main() -> None:
    parser = argparse.ArgumentParser(description="Load or replace the EcoMetrics sample readings.")
    parser.add_argument("--replace", action="store_true", help="Replace all stored hourly readings with the shipped CSV")
    args = parser.parse_args()
    if args.replace:
        replace_readings()
        print("Hourly readings were replaced from the packaged dataset.")
    else:
        initialize_database()
        print("Database schema is ready. Existing readings were preserved.")


if __name__ == "__main__":
    main()
