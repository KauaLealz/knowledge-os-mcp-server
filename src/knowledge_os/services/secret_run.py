"""`knowledge-mcp run`: entrega segredos a um processo filho e redige a saída dele.

O agente roda o comando e lê a saída, nunca o valor: ele vai só para o ambiente (ou o stdin)
do filho, que roda sem a chave mestra; o que o filho imprimir passa pela redação antes de
chegar ao agente. Não protege contra um comando feito para vazar (ex.: imprimir o valor ao
contrário, mandar pela rede) — o modelo de ameaça está no README.
"""

import base64
import json
import locale
import os
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import IO
from urllib.parse import quote, quote_plus

from knowledge_os.exceptions import ValidationError
from knowledge_os.services.vault import ENV_KEY

MASK = b"***"
MIN_REDACT = 4  # o set_value recusa valores menores: nunca seriam redigidos
MIN_FRAGMENT = 6  # trecho de base64 desalinhado ou linha de valor multilinha
JOIN_TIMEOUT_S = 5  # neto que herdou o pipe (daemon) não prende o `run` depois que o filho sai
# .cmd/.bat rodam pelo cmd.exe, que interpreta estes caracteres mesmo com a lista de argumentos
# (BatBadBut): `&` encadeia comando, `%VAR%` expande o segredo.
_CMD_META = re.compile(r'["%&|<>^!\r\n]')


def _encodings() -> list[str]:
    """Como o filho pode escrever o valor: UTF-8, a codepage ANSI, a OEM (Windows) e UTF-16."""
    found = ["utf-8", locale.getpreferredencoding(False)]
    if sys.platform == "win32":
        import ctypes

        found.append(f"cp{ctypes.windll.kernel32.GetOEMCP()}")
    found.append("utf-16-le")  # cmd /u, wmic, PowerShell redirecionado
    return list(dict.fromkeys(e.lower() for e in found))


def _b64_cores(raw: bytes) -> set[str]:
    """Base64 do valor em qualquer alinhamento: `Basic base64("user:" + token)` desloca os bytes.

    Para cada prefixo de 0, 1 ou 2 bytes, guarda só os caracteres que dependem apenas do
    valor (sem os das bordas, que se misturam com o que vem antes e depois).
    """
    cores = set()
    for k, start in ((0, 0), (1, 2), (2, 3)):
        total = k + len(raw)
        keep = (total // 3) * 4 + total % 3
        for enc in (base64.b64encode(b"\0" * k + raw), base64.urlsafe_b64encode(b"\0" * k + raw)):
            core = enc.decode()[start:keep]
            if len(core) >= MIN_FRAGMENT:
                cores.add(core)
    return cores


def _variants(value: str) -> set[bytes]:
    raw = value.encode()
    texts = {value, quote(value, safe=""), quote(value), quote_plus(value),
             json.dumps(value)[1:-1], json.dumps(value, ensure_ascii=False)[1:-1]}
    texts |= {re.sub(r"%[0-9A-F]{2}", lambda m: m.group(0).lower(), t)
              for t in (quote(value, safe=""), quote_plus(value))}
    for enc in (base64.b64encode(raw).decode(), base64.urlsafe_b64encode(raw).decode()):
        texts |= {enc, enc.rstrip("=")}
    texts |= _b64_cores(raw)
    # Valor de várias linhas (chave PEM, kubeconfig): a saída é redigida linha a linha.
    texts |= {ln.strip() for ln in value.splitlines() if len(ln.strip()) >= MIN_FRAGMENT}
    forms: set[bytes] = set()
    for text in texts:
        for encoding in _encodings():
            try:
                forms.add(text.encode(encoding))
            except (UnicodeEncodeError, LookupError):
                pass
    return {f for f in forms if len(f) >= MIN_REDACT}


def redactor(values: list[str]) -> Callable[[bytes], bytes]:
    """Função que troca cada valor (e as codificações comuns dele) por ***, em bytes."""
    forms = sorted({f for v in values if len(v) >= MIN_REDACT for f in _variants(v)},
                   key=len, reverse=True)

    def redact(data: bytes) -> bytes:
        for form in forms:
            data = data.replace(form, MASK)
        return data

    return redact


def resolve_executable(name: str, cwd: Path | None = None) -> str:
    """Caminho do executável, só pelo PATH absoluto — nunca pela pasta atual.

    No Windows, a busca padrão olha a pasta atual antes do PATH: um `gh.cmd` plantado num
    repositório de terceiros receberia o token. Caminho explícito (`./gradlew`) é aceito.
    """
    if os.sep in name or (os.altsep and os.altsep in name):
        return name
    here = (cwd or Path.cwd()).resolve()
    exts = [""]
    if sys.platform == "win32":
        exts = [""] if Path(name).suffix else []
        pathext = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD")
        exts += [e.lower() for e in pathext.split(";") if e]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        folder = Path(entry.strip('"'))
        if not entry or not folder.is_absolute():
            continue
        try:
            folder = folder.resolve()
        except OSError:
            continue
        if folder == here or here in folder.parents:
            continue  # pasta do projeto (ou dentro dela) no PATH: mesmo risco da pasta atual
        for ext in exts:
            candidate = folder / (name + ext)
            if candidate.is_file() and (sys.platform == "win32" or os.access(candidate, os.X_OK)):
                return str(candidate)
    raise ValidationError(f"Comando não encontrado no PATH: {name}")


def _check_cmd_args(exe: str, args: list[str]) -> None:
    if sys.platform == "win32" and Path(exe).suffix.lower() in (".cmd", ".bat"):
        bad = [a for a in args if _CMD_META.search(a)]
        if bad:
            raise ValidationError(
                f"{Path(exe).name} roda pelo cmd.exe, que interpretaria \" % & | < > ^ ! nos "
                "argumentos (e poderia expandir o segredo). Tire esses caracteres ou chame o "
                "programa por trás do .cmd (ex.: node <cli>.js)."
            )


def _pump(src: IO[bytes], dst: IO[str], redact: Callable[[bytes], bytes]) -> None:
    out = getattr(dst, "buffer", None)
    for raw in iter(src.readline, b""):
        clean = redact(raw)
        if out is not None:  # bytes do filho, como vieram (só redigidos)
            dst.flush()
            out.write(clean)
            out.flush()
        else:
            dst.write(clean.decode("utf-8", errors="replace"))
            dst.flush()
    src.close()


def run(cmd: list[str], env_values: dict[str, str], stdin_value: str | None) -> int:
    """Roda `cmd` com as variáveis e devolve o código de saída do filho."""
    exe = resolve_executable(cmd[0])
    _check_cmd_args(exe, cmd[1:])
    env = {k: v for k, v in os.environ.items() if k != ENV_KEY}
    env.update(env_values)
    redact = redactor([*env_values.values(), *([stdin_value] if stdin_value else [])])
    proc = subprocess.Popen(
        [exe, *cmd[1:]], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        stdin=subprocess.PIPE if stdin_value is not None else subprocess.DEVNULL,
    )
    pumps = [threading.Thread(target=_pump, args=(proc.stdout, sys.stdout, redact), daemon=True),
             threading.Thread(target=_pump, args=(proc.stderr, sys.stderr, redact), daemon=True)]
    for t in pumps:
        t.start()
    try:
        if stdin_value is not None:
            try:
                proc.stdin.write(stdin_value.encode())
                proc.stdin.close()
            except OSError:
                pass  # o filho saiu sem ler o stdin
        code = proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        code = proc.wait()
    for t in pumps:
        t.join(JOIN_TIMEOUT_S)
    return code
