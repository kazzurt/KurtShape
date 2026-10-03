"""Verify the extracted pinned runtime using its bundled Python."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    session = Path(os.environ['KURTSHAPE_SESSION_DIR']).resolve()
    report = args.report.resolve()
    if not report.is_relative_to(session):
        raise ValueError('Runtime probe report must be inside its isolated session')
    for name in ('FREECAD_USER_HOME', 'TEMP', 'TMP', 'APPDATA', 'LOCALAPPDATA'):
        if not Path(os.environ[name]).resolve().is_relative_to(session):
            raise ValueError('Runtime probe environment is not isolated: ' + name)
    import FreeCAD as App
    import Part
    home = Path(App.getHomePath()).resolve()
    checks = [
        {'name': 'FreeCAD 1.1.4', 'passed': App.Version()[:3] == ['1', '1', '4']},
        {'name': 'OCCT 7.8.1', 'passed': Part.OCC_VERSION == '7.8.1'},
        {'name': 'running runtime home', 'passed': home == args.home.resolve()},
        {'name': 'Assembly JointObject', 'passed': (home / 'Mod' / 'Assembly' / 'JointObject.py').is_file()},
    ]
    result = {'passed': all(check['passed'] for check in checks), 'checks': checks,
              'engine': {'freecad': App.Version(), 'occt': Part.OCC_VERSION}, 'home': str(home)}
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
