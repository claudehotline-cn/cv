
import sys
import os

# Create dummy db module if needed or just set path
sys.path.append(os.getcwd())

try:
    from app.routes import audit
    print("Import Successful")
except Exception as e:
    print(f"Import Failed: {e}")
except ImportError as e:
    print(f"Import Error: {e}")
