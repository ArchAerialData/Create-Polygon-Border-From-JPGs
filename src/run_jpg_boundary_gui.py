from pathlib import Path
import sys


SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from jpg_boundary_kmz_gui import main


if __name__ == "__main__":
    main()
