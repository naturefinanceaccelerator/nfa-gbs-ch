r"""
6_gbs_github.py - publishes the MSA parcel tool on GitHub (public) and serves the platform with GitHub Pages.
Script 6 of 6. Double-click. Run it again whenever code, tables, page or tiles changed (after 5_gbs_web.py).

Repository: github.com/naturefinanceaccelerator/nfa-gbs-ch (public)
  branch main      the code: numbered scripts, gbs_core.py, page\ templates, ref\ tables, README, validation
                   NOT uploaded: 00_Brief (internal), 01_Input plus 04_Output (client parcels plus results)
  branch gh-pages  the platform with its data: the web folder from 5_gbs_web.py (index.html, tiles, tables)
                   Always ONE commit (replaced on every run), so old tiles never pile up in the history.
Platform: https://naturefinanceaccelerator.github.io/nfa-gbs-ch/

First run (once):
  - installs Git plus GitHub CLI if missing (winget; Windows may ask for permission)
  - asks you to log in to GitHub in the browser (GitHub CLI shows a code to paste)
  - creates the PUBLIC repository in the NFA organisation, applies the NFA standard settings
    (Issues on; Wiki, Projects, Discussions off; squash merging only; delete head branches)
  - switches on GitHub Pages from the branch gh-pages
Git keeps its own folders in D:\NFA_data\4_projects\gbs_ch (github.git, site.git), not in OneDrive.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gbs_core as core  # noqa: E402

OWNER, REPO = "naturefinanceaccelerator", "nfa-gbs-ch"
FULL = f"{OWNER}/{REPO}"
PAGES_URL = f"https://{OWNER}.github.io/{REPO}/"
DESCRIPTION = "Swiss MSA parcel tool: GBS-consistent MSA (GLOBIO4 land-use module) per polygon from the Habitat Map of Switzerland"
HERE = Path(__file__).resolve().parent
CODE_GIT = core.WORK / "github.git"
SITE_GIT = core.WORK / "site.git"
WEB = core.WORK / "web"
CODE_RULES = """
/*
!/*.py
!/README.md
!/FolderGuide.md
!/page/
!/ref/
!/03_Validation/
"""                                                   # code only: never 00_Brief, 01_Input, 04_Output
ALWAYS_OUT = """
__pycache__/
~$*
.~lock*
*.tmp
desktop.ini
Thumbs.db
/start_local.bat
"""
MAX_MB = 95
TOOLS = {"git": ("Git.Git", [r"C:\Program Files\Git\cmd\git.exe"]),
         "gh": ("GitHub.cli", [r"C:\Program Files\GitHub CLI\gh.exe"])}


def find(name):
    exe = shutil.which(name)
    if exe:
        return exe
    for p in TOOLS[name][1]:
        if Path(p).exists():
            return p
    return None


def tool(name):
    exe = find(name)
    if exe:
        return exe
    winget = shutil.which("winget")
    if not winget:
        sys.exit(f"{name} is missing. Install it from "
                 f"{'https://git-scm.com' if name == 'git' else 'https://cli.github.com'}, then run again.")
    print(f"Installing {name} (one time) ...")
    subprocess.run([winget, "install", "--id", TOOLS[name][0], "-e", "--silent",
                    "--accept-source-agreements", "--accept-package-agreements"])
    exe = find(name)
    if not exe:
        sys.exit(f"{name} was installed but not found yet. Close this window and double-click again.")
    return exe


def run(cmd, check=True, capture=True, inp=None):
    r = subprocess.run(cmd, capture_output=capture, text=True, encoding="utf-8", errors="replace", input=inp)
    if check and r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip() if capture else ""
        sys.exit(f"Failed: {' '.join(str(c) for c in cmd[:5])} ...\n{msg}")
    return r


def init_git(git, gh, git_dir, work, rules, me):
    G = [git, f"--git-dir={git_dir}", f"--work-tree={work}"]
    if not (git_dir / "HEAD").exists():
        git_dir.parent.mkdir(parents=True, exist_ok=True)
        run(G + ["init", "-q"])
        run(G + ["config", "core.quotepath", "false"])
        run(G + ["config", "core.autocrlf", "false"])
        run(G + ["config", "http.postBuffer", "524288000"])
        run(G + ["config", "user.name", me.get("name") or me["login"]])
        run(G + ["config", "user.email", f"{me['id']}+{me['login']}@users.noreply.github.com"])
    big = []
    for root, _, files in os.walk(work):
        for f in files:
            p = Path(root) / f
            try:
                if p.stat().st_size > MAX_MB * 1e6:
                    big.append("/" + p.relative_to(work).as_posix())
            except OSError:
                pass
    (git_dir / "info").mkdir(exist_ok=True)
    (git_dir / "info" / "exclude").write_text(rules.strip() + "\n" + ALWAYS_OUT.strip() + "\n" + "\n".join(big) + "\n",
                                             encoding="utf-8")
    return G, big


def remote(G, url):
    if run(G + ["remote", "get-url", "origin"], check=False).returncode != 0:
        run(G + ["remote", "add", "origin", url])


def main():
    print(f"{Path(__file__).name} - GitHub upload for {FULL}\n")
    if not (WEB / "index.html").exists():
        sys.exit(f"No web folder in {WEB} - run 5_gbs_web.py first.")
    git, gh = tool("git"), tool("gh")

    # 1. login (once)
    if run([gh, "auth", "status"], check=False).returncode != 0:
        print("Log in to GitHub (one time). Follow the steps below; the browser opens.\n")
        run([gh, "auth", "login", "--web", "--git-protocol", "https", "--hostname", "github.com"], capture=False)
        if run([gh, "auth", "status"], check=False).returncode != 0:
            sys.exit("GitHub login did not finish. Double-click again to retry.")
    run([gh, "auth", "setup-git"], check=False)
    me = json.loads(run([gh, "api", "user"]).stdout)

    # 2. repository (once, public, in the NFA organisation) plus standard settings
    if run([gh, "repo", "view", FULL], check=False).returncode != 0:
        print(f"Creating the public repository {FULL} ...")
        r = run([gh, "repo", "create", FULL, "--public", "--description", DESCRIPTION], check=False)
        if r.returncode != 0:
            sys.exit(f"Could not create {FULL}:\n{(r.stderr or r.stdout).strip()}\n"
                     "You need owner rights in the organisation naturefinanceaccelerator.")
    settings = {"has_issues": True, "has_wiki": False, "has_projects": False, "has_discussions": False,
                "allow_merge_commit": False, "allow_rebase_merge": False, "allow_squash_merge": True,
                "delete_branch_on_merge": True, "homepage": PAGES_URL, "description": DESCRIPTION}
    run([gh, "api", "-X", "PATCH", f"repos/{FULL}", "--input", "-"], inp=json.dumps(settings))
    url = f"https://github.com/{FULL}.git"

    # 3. code -> main
    G, big = init_git(git, gh, CODE_GIT, HERE, CODE_RULES, me)
    run(G + ["add", "-A"])
    changed = run(G + ["status", "--porcelain"]).stdout.strip().splitlines()
    if changed:
        run(G + ["commit", "-q", "-m", f"Update {time.strftime('%d.%m.%Y %H:%M')}"])
    run(G + ["branch", "-M", "main"])
    remote(G, url)
    print(f"Code: {len(changed)} file(s) new or changed. Uploading ...")
    run(G + ["push", "-q", "-u", "origin", "main"])

    # 4. platform -> gh-pages, one fresh root commit (no history of old tiles)
    S, big2 = init_git(git, gh, SITE_GIT, WEB, "", me)
    run(S + ["add", "-A"])
    tree = run(S + ["write-tree"]).stdout.strip()
    old = run(S + ["rev-parse", "--verify", "-q", "gh-pages^{tree}"], check=False).stdout.strip()
    remote(S, url)
    if tree != old:
        commit = run(S + ["commit-tree", tree, "-m", f"Platform {time.strftime('%d.%m.%Y %H:%M')}"]).stdout.strip()
        run(S + ["update-ref", "refs/heads/gh-pages", commit])
        n = len(run(S + ["ls-files"]).stdout.splitlines())
        print(f"Platform: {n} files. Uploading (the first time several hundred MB - takes a while) ...")
        run(S + ["push", "-f", "-q", "origin", "gh-pages"], capture=False)
    else:
        print("Platform: nothing changed since the last upload.")

    # 5. GitHub Pages from gh-pages (once)
    if run([gh, "api", f"repos/{FULL}/pages"], check=False).returncode != 0:
        print("Switching on GitHub Pages ...")
        run([gh, "api", "-X", "POST", f"repos/{FULL}/pages", "--input", "-"],
            inp=json.dumps({"source": {"branch": "gh-pages", "path": "/"}}))
    print(f"\nDone.\n  Code:     https://github.com/{FULL}\n  Platform: {PAGES_URL}  (live 1-2 minutes after the upload)")
    for b in big + big2:
        print(f"  left out (over {MAX_MB} MB): {b}")
    print("\nOnce, by hand (no API for these): Settings > General - untick Sponsorships plus 'Preserve this repository'; "
          "repository home page > About (gear) - untick Releases, Packages, Deployments.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
    except SystemExit as e:
        if e.code not in (None, 0):
            print(e.code)
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("\nSomething went wrong - send Claude a screenshot of this window.")
    finally:
        if sys.stdin and sys.stdin.isatty():
            input("\nPress Enter to close.")
