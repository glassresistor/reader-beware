from setuptools import find_packages, setup

setup(
    name="reader-beware",
    version="0.2.0",
    description=(
        "Command line tools for creating branching gamebooks "
        "(choose-your-own-adventure style ebooks)."
    ),
    author="Margaret Killjoy",
    url="https://github.com/glassresistor/reader-beware",
    packages=find_packages(),
    package_data={
        "beware": ["templates/*/*.j2", "files/*.css"],
    },
    python_requires=">=3.8",
    install_requires=[
        "click",
        "jinja2>=3.0",
        "pyyaml",
        "markdown2",
        "lxml",
        "ebooklib",
        "flask",
    ],
    extras_require={
        "test": [
            "pytest",
            "black",
        ],
    },
    entry_points="""
        [console_scripts]
        beware=beware.cli:cli
    """,
)
