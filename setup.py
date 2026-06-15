from setuptools import setup, find_packages

setup(
    name="contract-cli",
    version="1.0.0",
    description="法务合同审阅管理命令行工具",
    author="Legal Tech Team",
    packages=find_packages(),
    install_requires=[
        "click>=8.0.0",
        "rich>=13.0.0",
        "python-dateutil>=2.8.0",
    ],
    entry_points={
        "console_scripts": [
            "contract-cli=contract_cli.cli:main",
        ],
    },
    python_requires=">=3.8",
)
