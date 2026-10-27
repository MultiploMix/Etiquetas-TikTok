import os, traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parent
os.chdir(ROOT)
try:
    import tiktok_conversor
    tiktok_conversor.main()
except BaseException:
    err=traceback.format_exc()
    try:
        (ROOT/"ERRO_INICIALIZACAO.txt").write_text(err,encoding="utf-8")
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0,"Falha ao abrir TikTok. Consulte ERRO_INICIALIZACAO.txt.\\n\\n"+err[-1200:],"Conversor TikTok - erro",0x10)
    except Exception:
        print(err)
