"""Install a verified official runtime inside the project on supported hosts."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.llm.preparation import install_runtime

if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(install_runtime(progress=lambda value: print(value, flush=True)))
