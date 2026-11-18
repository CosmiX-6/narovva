from .errors import NarrationError
from .mix import mix_voice_and_music
from .script import Script, write_script
from .tts import Clip, build_provider, synthesize_lines
from .voices import VIEWER_STYLE, choose_voice, default_voices, style_for_tone, with_language

__all__ = [
    "NarrationError", "Script", "write_script", "build_provider", "synthesize_lines", "Clip",
    "choose_voice", "default_voices", "style_for_tone", "with_language", "mix_voice_and_music", "VIEWER_STYLE",
]
