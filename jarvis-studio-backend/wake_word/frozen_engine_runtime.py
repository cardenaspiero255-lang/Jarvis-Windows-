"""PyInstaller-only hook: force local Whisper wake engine in clean FULL builds.

Deployed runtime never falls back to a pre-trained openWakeWord wake model.
This file is included only by the clean build's explicit runtime_hooks setting.
"""
import os

os.environ["JARVIS_WAKE_ENGINE"] = "whisper_local"
