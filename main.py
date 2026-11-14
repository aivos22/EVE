import sys
import os
from PySide6.QtWidgets import QApplication, QLabel
from dotenv import load_dotenv
from paths import BASE_DIR

load_dotenv(BASE_DIR / ".env")

app = QApplication(sys.argv)
key_ok = "✅" if os.getenv("GEMINI_API_KEY") else "❌"
label = QLabel(f"E.V.E. online. Gemini key loaded: {key_ok}")
label.resize(400, 100)
label.show()
sys.exit(app.exec())