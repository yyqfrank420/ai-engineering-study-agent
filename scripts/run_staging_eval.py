from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from eval.staging_runner import main


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
