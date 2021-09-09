from setuptools import setup

setup(
    name="pipimi",
    version="0.0",
    author="Aarni Koskela",
    author_email="akx@iki.fi",
    license="MIT",
    install_requires=open("./requirements.txt").readlines(),
    python_requires=">=3.6",
    py_modules=["pipimi"],
)
