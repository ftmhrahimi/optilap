"""Make ``optilap_crawler`` importable when running pytest from crawler/."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
