"""Prueba minima F5-Spanish (venv_f5): una frase con un clip de referencia, sin conexion."""
import os, subprocess, sys, time
os.environ["HF_HUB_OFFLINE"] = "1"
import numpy as np
import soundfile as sf
import torch
import torchaudio

# torchaudio.load (torchaudio 2.11) necesita FFmpeg via torchcodec: se lee con soundfile (WAV/FLAC)
def _cargar(ruta, *a, **k):
    x, sr = sf.read(str(ruta), dtype="float32", always_2d=True)
    return torch.from_numpy(x.T.copy()), sr
torchaudio.load = _cargar

from importlib.resources import files
from omegaconf import OmegaConf
from f5_tts.infer.utils_infer import load_model, load_vocoder, preprocess_ref_audio_text, infer_process
from f5_tts.model import DiT

R = r"C:\Users\miran\proyectoDoby"
MODELO = os.path.join(R, "modelos", "f5-spanish")
REF = os.path.join(R, "voz_comparacion_f5", "referencias", "lina", "lina_refC1.wav")
SALIDA = os.path.join(R, "voz_comparacion_f5", "_prueba")
os.makedirs(SALIDA, exist_ok=True)


def gpu():
    uso = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout.strip()
    return "GPU usada {} MiB (torch pico {:.0f} MiB)".format(uso, torch.cuda.max_memory_allocated() / 2**20)


print("torch", torch.__version__, "| cuda", torch.cuda.is_available(), torch.cuda.get_device_name(0))
arch = OmegaConf.load(str(files("f5_tts").joinpath("configs/F5TTS_Base.yaml"))).model.arch
t = time.perf_counter()
vocoder = load_vocoder("vocos", is_local=True, local_path=os.path.join(MODELO, "vocos-mel-24khz"))
modelo = load_model(DiT, OmegaConf.to_container(arch), os.path.join(MODELO, "model_1200000.safetensors"),
                    mel_spec_type="vocos", vocab_file=os.path.join(MODELO, "vocab.txt"))
print("Modelo y vocoder cargados en {:.1f} s; {}".format(time.perf_counter() - t, gpu()))

ref_texto = open(REF.replace(".wav", ".txt"), encoding="utf-8").read().strip()
ref_audio, ref_texto = preprocess_ref_audio_text(REF, ref_texto)
texto = "Hola amo, ¿qué vamos a hacer hoy?"
for intento in (1, 2):
    t = time.perf_counter()
    wav, sr, _ = infer_process(ref_audio, ref_texto, texto, modelo, vocoder, mel_spec_type="vocos", show_info=lambda *a: None)
    seg = time.perf_counter() - t
    ruta = os.path.join(SALIDA, "lina_refC1_saludo_1_prueba{}.wav".format(intento))
    sf.write(ruta, np.asarray(wav, dtype=np.float32), sr)
    print("Generacion {}: {:.2f} s de audio a {} Hz en {:.2f} s -> {}".format(intento, len(wav) / sr, sr, seg, ruta))
print(gpu())
