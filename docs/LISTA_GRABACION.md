# Lista de grabación

Cada integrante graba sus audios **con su propia voz**. Son **18 en total**:
- **Jean Paul, Lina y Paula: 5 cada uno.** Graban 3 palabras sueltas (sus dos nombres y su apellido) y 2 frases
  (primer nombre + apellido, y el nombre completo).
- **Harry: 3.** Graba «Harry», «Raigozo» y la frase «Harry Raigozo».

Solo se usa el **primer apellido**. Si en `voces/` aparece un segundo apellido (como `Rivera.mp3`), se ignora.

> **Nota para Harry: escribe y graba solo «Harry», nunca «Jean».** «Jean» es solo de Jean Paul Miranda. Si
> alguien dibuja «Jean Harry», el programa lo toma como una mezcla de dos personas y no lo acepta.

> **Regla: cada audio debe durar al menos 1 segundo**, con un poco de silencio (unos 0,3–0,5 s) **antes y
> después** de hablar. El programa **no recorta ni agrega nada**: usa el audio tal como llega. Los audios de
> menos de 1 s, cortados justo en la voz, se oían incompletos (Harry, Lina y Paula se retiraron por eso).

Los archivos van en **`voces/`** (en la raíz del proyecto, la única carpeta de entrada) con el **nombre exacto**
de la columna «Archivo». La extensión puede ser cualquiera de `.mp3 .mp4 .m4a .wav .ogg .mpeg`, en mayúsculas o
minúsculas. Lo que llega por WhatsApp sirve tal cual, aunque traiga doble extensión (`Camila.mp3.mpeg` cuenta como
`Camila`). El programa los convierte solo
(a `fusion/cache_audio/` y `fusion/audios_placa/`) y no toca los originales. No hay que editar ningún otro
archivo.

| Persona | Nombres | Apellido |
|---|---|---|
| Jean Paul | Jean, Paul | Miranda |
| Harry | Harry (nunca «Jean») | Raigozo |
| Lina | Lina, Tatiana | Maldonado |
| Paula | Paula, Camila | Enríquez |

## Qué suena

- Si lo dibujado es **exactamente una de las frases** y existe su grabación, suena solo esa grabación
  (por ejemplo, «Lina Maldonado» → `Lina_Maldonado`).
- Si no, se unen las palabras sueltas con 250 ms de pausa (por ejemplo, «Tatiana Maldonado» → `Tatiana` +
  `Maldonado`). También pasa esto si la frase todavía no está grabada.

## Los 18 audios

| # | Quién graba | Dice | Archivo (en `voces/`) | Estado |
|---|---|---|---|---|
| 1 | Jean Paul | Jean | `JEAN.mp4` | ✔ ya existe (también suena con «Jean» solo) |
| 2 | Jean Paul | Paul | `Paul.mp4` | ✔ ya existe |
| 3 | Jean Paul | Miranda | `Miranda.*` | falta |
| 4 | Jean Paul | Jean Miranda | `Jean_Miranda.*` | falta |
| 5 | Jean Paul | Jean Paul Miranda | `Jean_Paul_Miranda.*` | falta |
| 6 | Harry | Harry | `Harry.*` | falta (el anterior duraba 0,47 s: grabar de nuevo) |
| 7 | Harry | Raigozo | `Raigozo.*` | falta |
| 8 | Harry | Harry Raigozo | `Harry_Raigozo.*` | falta |
| 9 | Lina | Lina | `Lina.mp3.mpeg` | ✔ ya existe (grabación nueva, 1,73 s) |
| 10 | Lina | Tatiana | `Tatiana.mp3` | ✔ ya existe (grabación nueva) |
| 11 | Lina | Maldonado | `Maldonado.mp3` | ✔ ya existe |
| 12 | Lina | Lina Maldonado | `Lina_Maldonado.mp3.mpeg` | ✔ ya existe |
| 13 | Lina | Lina Tatiana Maldonado | `Lina_Tatiana_Maldonado.*` | falta |
| 14 | Paula | Paula | `Paula.*` | falta (el anterior duraba 0,52 s: grabar de nuevo) |
| 15 | Paula | Camila | `Camila.*` | falta |
| 16 | Paula | Enríquez | `Enriquez.*` | falta (sin tilde en el archivo) |
| 17 | Paula | Paula Enríquez | `Paula_Enriquez.*` | falta |
| 18 | Paula | Paula Camila Enríquez | `Paula_Camila_Enriquez.*` | falta |

Existen 6 y faltan 12. `*` = cualquier extensión de la lista (`.m4a` es lo que suele grabar el celular).

**Faltan 12, por persona** (nombre exacto del archivo; cada uno de **al menos 1 s**, con silencio antes y después):
- **Jean Paul (3):** `Miranda`, `Jean_Miranda`, `Jean_Paul_Miranda`.
- **Harry (3, todos):** `Harry`, `Raigozo`, `Harry_Raigozo`. Solo «Harry», nunca «Jean».
- **Lina (1):** `Lina_Tatiana_Maldonado`.
- **Paula (5, todos):** `Paula`, `Camila`, `Enriquez`, `Paula_Enriquez`, `Paula_Camila_Enriquez`.

**Regla para los nombres de archivo:** las palabras **sin tildes, sin espacios y sin ñ** (ñ → n), unidas con
guion bajo.

**No se usan:** `Jean.wav`, `0-000.wav` ni `output.wav`, aunque estén en `voces/`.

## Cómo grabar (para que suenen parejo con los que ya existen)

- **Un audio por archivo**, dicho una sola vez, con el tono normal con el que se dice el nombre propio. En las
  frases, sin pausas largas entre las palabras.
- Lugar silencioso, sin ventilador, con el celular a unos 20–30 cm de la boca, siempre a la misma distancia.
- **Al menos 1 segundo en total**, con un poco de silencio antes y después de hablar (empezar a grabar, esperar
  medio segundo, decir el nombre, esperar medio segundo y parar). El programa no recorta nada; solo empareja el
  volumen. Tampoco puede quitar ruido de fondo ni ecos.
- No hace falta que todos usen la misma app ni el mismo formato.
- Pronunciación: «Enríquez» con su acento normal. El archivo va sin tilde, pero la voz no cambia.

## Cómo comprobar

Cuando llegue un audio: se guarda en `voces/` (con el nombre de la tabla) y se corre
`py -3.11 fusion/voz.py --preparar`. Lista los 18 audios con su duración, dice cuáles faltan o tienen mal el
nombre, y deja los WAV para la placa en `fusion/audios_placa/` (después se suben a `/voz` con Thonny). Los que
faltan no rompen nada: solo al dibujar un nombre sin audio, la pantalla muestra **«Falta audio: <palabra>»** y no
suena nada.
