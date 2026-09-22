"""
Serverless entry point (Vercel).

The project root is added to sys.path so `main` imports correctly when this
module is executed from the function's own directory.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app  # noqa: E402

# Vercel picks up either name
handler = app
