# nlu.py
import re
from typing import List, Dict, Tuple, Any

# -------------------------------------------------
# компилируем шаблоны в regex-ы
# -------------------------------------------------
def _compile(cmds: Dict[str, List[str]]) -> List[Tuple[str, re.Pattern]]:
    compiled: List[Tuple[str, re.Pattern]] = []

    for intent, phrases in cmds.items():
        for p in phrases:
            tpl = p.lower()

            # {slot}  →  (?P<slot>.+)
            tpl = re.sub(r"{(\w+)}", r"(?P<\1>.+)", tpl)

            # запятую можно опустить
            tpl = tpl.replace(",", ",?")

            # любой пробел заменяем на \s+
            tpl = re.sub(r"\s+", r"\\s+", tpl)

            compiled.append((intent, re.compile(rf"^{tpl}$")))
    return compiled


_COMPILED: List[Tuple[str, re.Pattern]] | None = None   # кэш


# -------------------------------------------------
# главная функция
# -------------------------------------------------
def interpret(text: str, commands: Dict[str, Any]) -> Dict[str, Any]:
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = _compile(commands)

    s = re.sub(r"\s+", " ", text.lower().strip())   # нормализуем

    for intent, rx in _COMPILED:
        m = rx.fullmatch(s)
        if m:
            return {
                "intent": intent,
                "slots": {k: v.strip() for k, v in m.groupdict().items()}
            }

    return {"intent": "unknown", "slots": {}}



