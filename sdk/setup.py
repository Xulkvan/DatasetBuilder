"""[STAGE1:sdk-setup] Setup for DatasetBuilder SDK.

Установка:  pip install ./sdk
"""
from setuptools import setup, find_packages

setup(
    name="datasetbuilder-sdk",
    version="13.4.0",
    description="Async Python SDK for DatasetBuilder B2B API v2",
    author="Xulkvan",
    license="PolyForm Noncommercial 1.0.0",
    packages=find_packages(),
    install_requires=["httpx>=0.27.0"],
    python_requires=">=3.10",
)
