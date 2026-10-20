"""Build the experimental script mod with the game's Python bytecode version."""

import importlib.util
from pathlib import Path
import py_compile
import sys
import tempfile
import zipfile


def main():
    if sys.version_info[:2] != (3, 7):
        raise SystemExit('The installed game requires Python 3.7 bytecode.')

    root = Path(__file__).resolve().parent
    source = root / 'src'
    output = root / 'dist' / 'BanterLab.ts4script'
    output.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        with zipfile.ZipFile(str(output), 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(source.rglob('*.py')):
                relative = path.relative_to(source).with_suffix('.pyc')
                compiled = Path(temporary) / relative
                compiled.parent.mkdir(parents=True, exist_ok=True)
                py_compile.compile(str(path), cfile=str(compiled),
                                   dfile=relative.as_posix(), doraise=True)
                assert compiled.read_bytes()[:4] == importlib.util.MAGIC_NUMBER
                archive.write(str(compiled), relative.as_posix())
    print('Built {}'.format(output))
    with zipfile.ZipFile(str(output)) as archive:
        assert archive.testzip() is None
        print('Modules: {}'.format(', '.join(archive.namelist())))


if __name__ == '__main__':
    main()
