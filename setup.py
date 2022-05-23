import pathlib
from setuptools import find_packages, setup


_here = pathlib.Path(__file__).resolve().parent
_version_file = _here / 'VERSION'
with _version_file.open('r') as f:
    _version = f.read().strip()

# this is a hack, but it works for now and keeps the version number in a single file
_libmuscle_version_file = _here / 'libmuscle' / 'python' / 'libmuscle' / 'version.py'
with _libmuscle_version_file.open('w') as f:
    f.write('__version__ = \'{}\'\n'.format(_version))

_muscle3_packages = [
        p for p in find_packages() + find_packages('libmuscle/python')
        if p != 'integration_test']

setup(
    name='muscle3',
    version=_version,
    description='Version 3 of the MUltiScale Coupling Library and Environment',
    author='Lourens Veen',
    author_email='l.veen@esciencecenter.nl',
    url='https://github.com/multiscale/muscle3',
    license='Apache License 2.0',
    keywords=['multiscale', 'coupling', 'MUSCLE'],
    classifiers=[
        'Development Status :: 1 - Planning',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8'],

    packages=_muscle3_packages,
    package_dir={
        'muscle3': 'muscle3',
        'libmuscle': 'libmuscle/python/libmuscle'
    },
    entry_points={
        'console_scripts': [
            'muscle_manager=muscle3.muscle_manager:manage_simulation',
            'muscle3=muscle3.muscle3:muscle3']
    },
    python_requires='>=3.5, <4',
    install_requires=[
        'click>=6',
        'msgpack',
        'netifaces',
        'numpy>=1.12,<1.23',
        'qcg-pilotjob==0.13',
        'typing_extensions<4',
        'ymmsl @ git+https://github.com/multiscale/ymmsl-python.git@develop#egg=ymmsl'          # Also in CI, update there as well
    ],
    extras_require={
        'dev': [
            'sphinx<3.2',
            'sphinx_rtd_theme',
            'sphinx-fortran',
            'yapf',
            'isort'
        ]
    },
)
