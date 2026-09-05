from setuptools import setup

setup(
    name="pyvcs",
    version="1.0.0",
    description="A modern, lightweight Version Control System built from scratch",
    py_modules=["objects", "diff", "packfile", "ignore", "repo", "branch", "tagger", "stash", "remote", "server", "cli"],
    entry_points={
        "console_scripts": [
            "vcs=cli:main",
        ],
    },
    python_requires=">=3.8",
)
