# config.py
import json
from pathlib import Path

COMMANDS_FILE = Path(__file__).parent / 'commands.json'
with open(COMMANDS_FILE, encoding='utf-8') as f:
    COMMANDS = json.load(f)

APP_MAP = {}