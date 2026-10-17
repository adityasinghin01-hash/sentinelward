"""Use the repository's immutable, strictly masked 125 Hz assembler."""
from pathlib import Path
import sys

_ML = Path(__file__).resolve().parents[2] / 'ml'
if str(_ML) not in sys.path: sys.path.insert(0,str(_ML))
from sentinelward_ml.windows import VitalsWindowAssembler

__all__ = ['VitalsWindowAssembler']
