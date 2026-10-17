#!/usr/bin/env python3
"""Install missing runtime dependencies using universal wheels only, never scientific packages.

Run on LinuxONE in the existing --system-site-packages venv. Resolve dependencies
from wheel metadata while consulting the actual installed environment. No build
isolation, source distributions, compiled wheels or recursive pip installs.
"""
from importlib import metadata
import email
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import zipfile

try:
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
except ImportError:
    from setuptools._vendor.packaging.requirements import Requirement
    from setuptools._vendor.packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ('common', 'simulator', 'brain', 'attacks', 'backend')
PROTECTED = {'numpy', 'scipy', 'pandas', 'scikit-learn', 'pyyaml', 'psutil'}


def ensure(requirements, pending=None):
    """Download all missing universal wheels first; install only after validation."""
    pending = {} if pending is None else pending
    queue, checked = list(requirements), set()
    with tempfile.TemporaryDirectory(prefix='sw-pure-deps-') as temporary:
        directory = Path(temporary)
        while queue:
            req = Requirement(queue.pop(0))
            if req.marker and not req.marker.evaluate():
                continue
            name = canonicalize_name(req.name)
            if name in {canonicalize_name(x) for x in ('sw_common', 'sw_sim', 'sentinelward-brain', 'sentinelward-attacks', 'sw_api')}:
                continue
            signature = str(req)
            if signature in checked:
                continue
            checked.add(signature)
            try:
                version = metadata.version(req.name)
                if req.specifier and version not in req.specifier:
                    raise RuntimeError(f'Installed {name} does not satisfy declared requirement; provision a compatible version separately')
                # Validate the transitive requirements even for an already-installed package.
                queue.extend(metadata.requires(req.name) or [])
                continue
            except metadata.PackageNotFoundError:
                pass
            if name in PROTECTED:
                raise RuntimeError(f'Missing {name}: provision through Ubuntu apt, never pip')
            if name in pending:
                version, requirements, _ = pending[name]
                if req.specifier and version not in req.specifier:
                    raise RuntimeError(f'Conflicting requirements for {name}; no packages installed')
                continue
            wheel_dir = directory / name
            wheel_dir.mkdir()
            # --platform any rejects s390x/native wheels, including pydantic-core.
            command = [sys.executable, '-m', 'pip', 'download', '--disable-pip-version-check', '--no-deps',
                       '--only-binary=:all:', '--platform', 'any', '--dest', str(wheel_dir), str(req)]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode:
                raise RuntimeError(f'No compatible universal wheel for {name}; provision native requirements separately (no pip output printed)')
            wheels = list(wheel_dir.glob('*.whl'))
            if len(wheels) != 1 or not wheels[0].name.endswith('-none-any.whl'):
                raise RuntimeError(f'Refusing non-universal wheel for {name}')
            with zipfile.ZipFile(wheels[0]) as archive:
                names = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
                doc = email.message_from_bytes(archive.read(names[0]))
            dependencies = doc.get_all('Requires-Dist') or []
            pending[name] = (doc['Version'], dependencies, wheels[0])
            queue.extend(dependencies)
        if pending:
            # Install a validated closure in one operation, with dependency resolution disabled.
            result = subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps',
                                     *[str(entry[2]) for entry in pending.values()]],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode:
                raise RuntimeError('Universal-wheel installation failed; package output withheld to protect credentials')
            print('Installed missing universal packages: ' + ', '.join(sorted(pending)))
        else:
            print('All runtime dependencies already present')


def main():
    requirements = ['setuptools>=68', 'wheel', 'httpx>=0.28,<0.29']
    for package in PACKAGES:
        document = tomllib.loads((ROOT / package / 'pyproject.toml').read_text())
        requirements += document['project'].get('dependencies', [])
        requirements += document['build-system'].get('requires', [])
    ensure(requirements)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Dependency preflight failed: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
