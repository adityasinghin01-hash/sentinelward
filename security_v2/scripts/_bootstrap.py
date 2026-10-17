"""Allow scripts to run from a copied checkout without an editable installation."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
