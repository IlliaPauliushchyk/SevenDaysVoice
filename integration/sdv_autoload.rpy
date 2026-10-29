# Этот файл лежит в проекте и копируется в игру только install_integration.bat.
# Код совместим с Python 2.7 внутри Ren'Py 7.4.

init -999 python:
    import os

    def _sdv_read_audio_root():
        env_root = os.environ.get("SDV_AUDIO", "").strip()
        if env_root and os.path.isdir(env_root):
            return env_root
        path_file = os.path.join(renpy.config.gamedir, "sdv_voice_path.txt")
        if os.path.isfile(path_file):
            handle = open(path_file, "rb")
            try:
                text = handle.read().decode("utf-8").strip()
            finally:
                handle.close()
            if text and os.path.isdir(text):
                return text
        return None

    _sdv_root = _sdv_read_audio_root()
    if _sdv_root and _sdv_root not in renpy.config.searchpath:
        renpy.config.searchpath.append(_sdv_root)

    def _sdv_auto_voice(ident):
        if not ident:
            return None
        shard = ident[:2]
        fn = "voice/" + shard + "/" + ident + ".ogg"
        if renpy.loadable(fn):
            return fn
        return None

    renpy.config.auto_voice = _sdv_auto_voice
    renpy.config.has_voice = True
