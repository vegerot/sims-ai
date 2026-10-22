"""Build the script mod with the game's Python 3.7 bytecode and deploy to Mods/BanterLab."""

import importlib.util
from pathlib import Path
import py_compile
import shutil
import sys
import tempfile
import zipfile

DEFAULT_DEPLOY_DIR = Path(r'C:\Users\Max\OneDrive\Documents\Electronic Arts\The Sims 4\Mods\BanterLab')


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

    if DEFAULT_DEPLOY_DIR.parent.exists():
        DEFAULT_DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
        for asset in (output, root / 'companion.py', root / 'prompt.txt'):
            dest = DEFAULT_DEPLOY_DIR / asset.name
            shutil.copy2(str(asset), str(dest))
            print('Deployed {}'.format(dest))


if __name__ == '__main__':
    main()
