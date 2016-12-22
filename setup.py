import os

from setuptools import setup, find_packages

# Extract version
rootpath = os.path.abspath(os.path.dirname(__file__))


def extract_version(module='cuiows'):
    version = None
    fname = os.path.join(rootpath, module, '__init__.py')
    with open(fname) as f:
        for line in f:
            if line.startswith('__version__'):
                _, version = line.split('=')
                version = version.strip()[1:-1]  # Remove quotation characters.
                break
    return version


setup(
    name='cuiows',
    version=extract_version(),
    packages=find_packages(),
    url='https://github.com/SunDwarf/curio_websocket',
    license='MIT',
    author='Isaac Dickinson',
    author_email='sun@veriny.tf',
    description='A curio websocket library',
    install_requires=[
        "curio>=0.4.0",
        "wsproto>=0.9.0"
    ],
)
