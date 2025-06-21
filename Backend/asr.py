# asr.py
import queue
import sounddevice as sd
from vosk import Model, KaldiRecognizer

q = queue.Queue()

def audio_callback(indata, frames, time, status):
    if status:
        print(status)
    q.put(bytes(indata))

def recognize(model_path='model', sample_rate=16000):
    model = Model(model_path)
    rec = KaldiRecognizer(model, sample_rate)
    with sd.RawInputStream(
            samplerate=sample_rate,
            blocksize=8000,
            dtype='int16',
            channels=1,
            callback=audio_callback
        ):
        print('Начинаю слушать...')
        while True:
            data = q.get()
            if rec.AcceptWaveform(data):
                yield rec.Result()
            else:
                yield rec.PartialResult()