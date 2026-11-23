# clonacion/modelos/ — modelo F5-Spanish y vocoder (se descargan aparte)

> No se suben al repositorio (1,3 GB). Solo hacen falta para el botón Hora, que es **opcional**.
> Proceso completo: [GUIA_PARA_OTROS.md](../../GUIA_PARA_OTROS.md), paso 12.

## Dónde va cada modelo

`clonacion/entrenamiento/generar_voces_f5.py` los busca exactamente aquí:

| Modelo | Archivos | Carpeta | Origen |
|---|---|---|---|
| F5-Spanish | `model_1200000.safetensors` (1286 MB), `vocab.txt` | `clonacion/modelos/f5-spanish/` | https://huggingface.co/jpgallegoar/F5-Spanish (commit usado `4765c14ffd01075479c2fde8615831acc0adca9a`) |
| Vocoder vocos | `config.yaml`, `pytorch_model.bin` (52 MB) | `clonacion/modelos/f5-spanish/vocos-mel-24khz/` | Probablemente https://huggingface.co/charactr/vocos-mel-24khz, el que usa f5-tts por defecto (**POR VERIFICAR**) |
| Whisper `medium` | (los maneja faster-whisper) | Caché de Hugging Face del usuario, no esta carpeta | `Systran/faster-whisper-medium`, que es lo que descarga `WhisperModel("medium")` en `clonacion/pc/stt.py` |

## Cómo descargarlos (con internet, una vez, desde la carpeta del repositorio)

Los scripts de clonación ponen `HF_HUB_OFFLINE=1` y **no descargan nada solos**. Estos comandos salen de los nombres
que usa el código, pero **no se probaron**:

```
venv_f5\Scripts\python.exe -c "from huggingface_hub import hf_hub_download as d; [d('jpgallegoar/F5-Spanish', f, local_dir='clonacion/modelos/f5-spanish') for f in ('model_1200000.safetensors', 'vocab.txt')]"
venv_f5\Scripts\python.exe -c "from huggingface_hub import snapshot_download as s; s('charactr/vocos-mel-24khz', local_dir='clonacion/modelos/f5-spanish/vocos-mel-24khz')"
venv_f5\Scripts\python.exe -c "from faster_whisper import WhisperModel; WhisperModel('medium', device='cpu', compute_type='int8')"
```

**Comprobar** que quedaron los 4 archivos de la tabla en sus carpetas. Si un comando falla, busquen esos archivos
en la página de Hugging Face de cada modelo (pestaña «Files and versions») y descárguenlos a mano en la carpeta de
la tabla.

## Riesgo (POR VERIFICAR): `hablantes.json`

`clonacion/pc/voz_clonada.py:210` lee `clonacion/modelos/hablantes/hablantes.json` (la lista de integrantes del
proyecto Doby), que **no viene** en el repositorio. Si un script falla con `FileNotFoundError: …hablantes.json`,
creen `clonacion/modelos/hablantes/hablantes.json` con sus voces:

```json
{"nombres": ["ana"]}
```

Versiones de los paquetes: [`clonacion/requirements_clonacion.txt`](../requirements_clonacion.txt).
