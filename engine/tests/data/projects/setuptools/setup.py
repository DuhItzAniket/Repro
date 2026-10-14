from setuptools import setup

setup(
    name="calc",
    version="0.1.0",
    packages=["calc"],
    install_requires=["iniconfig==2.0.0"],
    extras_require={"test": ["pytest==8.3.3"]},
)
