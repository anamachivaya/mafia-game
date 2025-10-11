import importlib.util
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DIR = Path(__file__).resolve().parent


def run_test_file(path):
    print(f"== Running {path.name} ==")
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        print(f"ERROR: Failed to import {path.name}: {e}")
        traceback.print_exc()
        return 1
    failures = 0
    for name in dir(mod):
        if name.startswith('test_') and callable(getattr(mod, name)):
            fn = getattr(mod, name)
            try:
                fn()
                print(f" PASS {name}")
            except AssertionError as ae:
                failures += 1
                print(f" FAIL {name}: {ae}")
                traceback.print_exc()
            except Exception as e:
                failures += 1
                print(f" ERROR {name}: {e}")
                traceback.print_exc()
    return failures


def main():
    total_fail = 0
    for f in sorted(TEST_DIR.glob('test_*.py')):
        total_fail += run_test_file(f)
    if total_fail == 0:
        print('\nALL TESTS PASSED')
        sys.exit(0)
    else:
        print(f"\nTESTS FAILED: {total_fail} failures")
        sys.exit(2)

if __name__ == '__main__':
    main()
