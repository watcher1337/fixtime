from setuptools import setup

setup(
    name="fixtime",
    version="2.0.1",
    py_modules=["fixtime"],
    install_requires=[
        "ntplib",
        "click",
        "python-dateutil",
        "requests"
    ],
    entry_points={
        "console_scripts": [
            "fixtime=fixtime:main",
        ],
    },
    author="watcher1337",
    description="Time synchronization tool for Kerberos authentication",
    url="https://github.com/watcher1337/fixtime",
    python_requires=">=3.8",
)
