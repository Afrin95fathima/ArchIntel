"""Check local build prerequisites without running customer code or pulling images."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.config import Settings
from app.transformation.sandbox import capabilities

if __name__ == '__main__':
    result = capabilities(Settings())
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['available'] else 1)
