"""
Runs scripts 1 to 5 of this folder in order (double-click). Script 6 (GitHub) stays separate, as in the golf project.

  1_gbs_sources.py   reference sources plus official TypoCH names -> D:\\NFA_data\\1_sources\\gbs
  2_gbs_tiles.py     habitat tiles from the Habitat Map           -> D:\\NFA_data\\4_projects\\gbs_ch\\tiles
  3_gbs_check.py     validation against an exact overlay          -> 03_Validation
  4_gbs_report.py    reports for every file in 01_Input           -> 04_Output
  5_gbs_web.py       the web platform                             -> D:\\NFA_data\\4_projects\\gbs_ch\\web
Stops at the first step that fails, so later steps never run on broken data.
Step 2 takes 1-3 hours the first time; afterwards it only redoes what changed.
"""
import runpy
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent


def steps():
    found = []
    for n in range(1, 6):
        hits = sorted(HERE.glob(f"{n}_*.py"))
        if not hits:
            sys.exit(f"No script starting with {n}_ found in {HERE}.")
        found.append(hits[0])
    return found


def main():
    todo = steps()
    print("Runs: " + ", ".join(p.name for p in todo) + "\n")
    t_all = time.time()
    for i, p in enumerate(todo, 1):
        print("=" * 70)
        print(f"STEP {i} of 5: {p.name}")
        print("=" * 70)
        t = time.time()
        try:
            runpy.run_path(str(p), run_name="gbs_step")["main"]()
        except SystemExit as e:
            if e.code not in (None, 0):
                print(f"\n{e.code}")
                print(f"\nStopped at step {i} ({p.name}). Steps after it did not run.")
                return
        except KeyboardInterrupt:
            print(f"\nStopped by you at step {i}.")
            return
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            print(f"\nStep {i} ({p.name}) failed. Steps after it did not run.")
            print("Send Claude a screenshot of this window.")
            return
        print(f"\nStep {i} done in {time.time() - t:.0f} s.\n")
    print("=" * 70)
    print(f"All 5 steps done in {(time.time() - t_all) / 60:.1f} min.")
    print("Publish: double-click 6_gbs_github.py.")


if __name__ == "__main__":
    try:
        main()
    finally:
        if sys.stdin and sys.stdin.isatty():
            input("\nPress Enter to close.")
