# server.py
import logging
import json
from pathlib import Path
from typing import Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from vosk import Model, KaldiRecognizer

from nlu import interpret
from executor import execute
from config import COMMANDS

# --------------------------------------------------
# Логирование
# --------------------------------------------------
log = logging.getLogger("server")
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s"
)

# --------------------------------------------------
# Загрузка Vosk-модели
# --------------------------------------------------
MODEL_PATH = Path(__file__).parent / "model"
if not MODEL_PATH.exists():
    raise RuntimeError(f"Не найдена Vosk-модель по пути: {MODEL_PATH}")
log.info(f"▶️  Загружаем Vosk-модель: {MODEL_PATH.resolve()}")
asr_model = Model(str(MODEL_PATH))
log.info("✅  Vosk-model загружена")

SAMPLE_RATE = 16_000

# --------------------------------------------------
# FastAPI
# --------------------------------------------------
app = FastAPI(title="BaitAssistant Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# Pydantic-схемы
# --------------------------------------------------
class CommandRequest(BaseModel):
    text: str

class CommandResponse(BaseModel):
    intent: str
    status: bool
    message: str

# --------------------------------------------------
# HTTP /command/
# --------------------------------------------------
@app.post("/command/", response_model=CommandResponse)
async def command_endpoint(req: CommandRequest):
    """
    Получаем полную фразу (обязательно с «Байт …»),
    прогоняем через NLU → executor.
    """
    text = req.text.lower().strip()

    # --- NLU ---
    nlu: Dict[str, Any] = interpret(text, COMMANDS)
    intent = nlu["intent"]
    slots  = nlu["slots"]

    log.info(f"NLU input='{text}' → intent='{intent}', slots={slots}")

    # --- выполнение ---
    ok = execute(intent, **slots)
    message = (
        f"Команда «{intent}» выполнена."
        if ok else
        "Не удалось выполнить команду."
    )

    return CommandResponse(intent=intent, status=ok, message=message)

# --------------------------------------------------
# WebSocket /asr/ws
# --------------------------------------------------
@app.websocket("/asr/ws")
async def asr_ws(websocket: WebSocket):
    await websocket.accept()
    recognizer = KaldiRecognizer(asr_model, SAMPLE_RATE)

    try:
        while True:
            data = await websocket.receive_bytes()

            if recognizer.AcceptWaveform(data):
                final = json.loads(recognizer.Result()).get("text", "")
                await websocket.send_json({"final": final})
            else:
                partial = json.loads(recognizer.PartialResult()).get("partial", "")
                await websocket.send_json({"partial": partial})

    except WebSocketDisconnect:
        log.info("WebSocket client disconnected")
