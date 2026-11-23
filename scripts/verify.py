"""Run a scoped Discord regression suite or the complete offline Python gate."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SUITES = {
    "members": ("test_staff_boundaries", "test_role_authorization", "test_private_notification_center"),
    "assembly": ("test_plan_assembly_state", "test_plan_assembly_delivery", "test_plan_assembly_ui",
                 "test_unified_squad_flow", "test_plan_response_deadline"),
    "plans": ("test_plan_services", "test_plan_delivery", "test_squad_plans", "test_squad_interest",
              "test_squad_integration", "test_unified_squad_flow"),
    "growth": ("test_community_levels", "test_level_membership", "test_level_audit", "test_title_roles"),
    "locale": ("test_language_preferences", "test_stage3_wording"),
    "runtime": ("test_round_readiness", "test_runtime_backup", "test_audit_readable", "test_audit_recovery_privacy",
                "test_member_role_log", "test_role_audit_reason"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=("all", "static", *SUITES), nargs="?", default="all")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 11):
        parser.exit(1, "Use the Python 3.11 interpreter with requirements.txt installed.\n")

    with tempfile.TemporaryDirectory(prefix="con9sole-check-") as data_dir:
        # Start clean: children must not inherit bot tokens, database paths or feature overrides.
        env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "LD_LIBRARY_PATH", "LANG")
               if k in os.environ}
        env.update(DRINK_DATA_DIR=data_dir, PYTHONPATH=str(ROOT / "tests"), PYTHONNOUSERSITE="1")

        def run(*arguments):
            subprocess.run([sys.executable, *arguments], check=True, cwd=ROOT, env=env)

        if args.suite in ("all", "static"):
            # Limit compilation to project files, including newly staged Python modules.
            files = subprocess.check_output(["git", "ls-files", "-z", "--", "*.py"], cwd=ROOT)
            paths = [os.fsdecode(path) for path in files.split(b"\0") if path]
            if not paths:
                parser.exit(1, "No tracked Python sources found.\n")
            run("-W", "error::SyntaxWarning", "-m", "compileall", "-f", "-q", *paths)
            run("scripts/validate_codex_agents.py")
            for name, modules in SUITES.items():
                for module in modules:
                    if not (ROOT / "tests" / (module + ".py")).is_file():
                        parser.exit(1, f"{name}: missing tests/{module}.py\n")
        if args.suite == "all":
            run("-m", "unittest", "discover", "-s", "tests", "-v")
        elif args.suite != "static":
            run("-m", "unittest", "-v", *SUITES[args.suite])


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
