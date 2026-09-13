"""
Local counterpart to .github/workflows/update_data.yml.

StockAnalysis.com's Cloudflare protection challenges GitHub Actions'
datacenter IPs (confirmed via a "Just a moment..." interstitial in place of
the real screener page), so the scheduled cloud scrape can silently fail.
This script runs the same scrape + process + enrich pipeline from a normal
residential/office connection instead, then commits and pushes the result
exactly like the GitHub Actions workflow does.

Intended to be run on a schedule via Windows Task Scheduler (see the setup
notes provided alongside this script) as a fallback alongside, not instead
of, the GitHub Actions workflow.
"""
import subprocess
import sys
import datetime
from pathlib import Path

# Windows consoles often default to a non-UTF-8 codepage (e.g. cp949),
# which crashes on the checkmark/warning characters the pipeline prints.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent
DATA_FILES = [
    "data/final_df2.csv",
    "data/dividend_from_stockanalysis.csv",
    "data/last_updated.txt",
]


def run(cmd):
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=REPO_ROOT, check=True)


def main() -> int:
    # Bring main up to date first, in case the GitHub Actions workflow (or a
    # manual push) already landed a newer update since this machine last synced.
    print("=" * 60)
    print("Syncing with origin/main before scraping...")
    print("=" * 60)
    try:
        run(["git", "pull", "--ff-only"])
    except subprocess.CalledProcessError:
        print("⚠ git pull --ff-only failed (local changes or diverged history).")
        print("  Resolve manually before this can push its results.")
        return 1

    sys.path.insert(0, str(REPO_ROOT))
    from modules.data_collector import DividendDataCollector

    DividendDataCollector().update_all_data(use_scraping=True)

    print("\n" + "=" * 60)
    print("Committing and pushing updated data...")
    print("=" * 60)
    run(["git", "add", *DATA_FILES])

    diff_check = subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=REPO_ROOT)
    if diff_check.returncode == 0:
        print("No changes to commit")
        return 0

    today = datetime.date.today().isoformat()
    run(["git", "commit", "-m", f"chore: auto-update dividend data (local) {today}"])

    try:
        run(["git", "push"])
    except subprocess.CalledProcessError:
        print("⚠ git push failed — likely a concurrent update from GitHub Actions.")
        print("  The commit is saved locally; run 'git pull --rebase && git push' by hand.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
