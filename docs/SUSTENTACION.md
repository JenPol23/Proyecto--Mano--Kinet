# Sustentación: guía para operar la demo

Para quien maneje el PC durante la sustentación. Todo se ejecuta desde la carpeta del proyecto
(`C:\Users\miran\mano_pruebas_consola`).

## 1. Antes de empezar (30 min antes)

- Celular cargado, con el **punto de acceso** configurado (la misma red de `config_wifi.py` de la placa, en 2,4 GHz).
- PC cargado, **Kinect** conectado, **Bluetooth** activado.
- Fuente de **12 V** lista. El USB de la placa **desconectado**: 12 V y USB no van a la vez.
- **Thonny cerrado.** Si Thonny está abierto y conectado a la placa, pausa `main.py`: la mano deja de responder
  por Bluetooth y por WiFi.
- Ningún otro programa conectado a la mano (por ejemplo `consola_mano.py`): solo se permite un cliente Bluetooth.

## 2. Orden de encendido

1. **Celular**: encender el punto de acceso.
2. **PC**: conectarse al WiFi del celular. Bluetooth activado. Thonny cerrado.
3. **Placa**: conectar los 12 V (sin USB). Esperar unos 10 s a que arranque y se conecte al WiFi.
4. **Programa**:
   ```
   py -3.11 fusion/dibujar_fusion.py
   ```
   Tarda en cargar TrOCR. Listo cuando arriba a la izquierda dice **«Mano: conectada (version:voz-2)»** en verde.
   Si dice «sin conexión», pulsar **r**.
5. **Prueba rápida** antes de que entre el jurado: dibujar «Lina», confirmar y ver que deletrea y suena; luego
   pedir la hora (botón **Hora** o tecla **h**) y deletrear otra vez.

## 3. Durante la demo

| Gesto o tecla | Qué hace |
|---|---|
| índice | dibujar |
| mano abierta | levantar el lápiz |
| 👎 1 s | siguiente palabra (máximo 4) |
| 👍 | terminar; en la confirmación, 👍 1,5 s confirma |
| ✌️ 1 s | quitar la última palabra |
| 🤙 (shaka) | borrar la palabra actual / volver a dibujar / cerrar el menú de la hora |
| 3 dedos | cambiar el color |
| índice 1 s sobre **Hora** (arriba a la derecha), o tecla **h** | menú de voces para decir la fecha y la hora |
| en el menú: índice 1 s sobre una voz, o teclas **1–4** | suena la fecha y la hora con esa voz; vuelve a dibujar sin borrar |
| **Esc** | durante el deletreo: detener la mano; en el menú de la hora: cerrarlo; en lo demás: salir |
| **r** | reconectar la mano por Bluetooth |

La hora solo se puede pedir mientras se dibuja, nunca durante un deletreo.

## 4. Si algo falla

### La hora dice «Sin WiFi en la mano»

1. Comprobar que el punto de acceso del celular sigue encendido y que el PC está conectado a él.
2. Si la placa se encendió **antes** que el punto de acceso, ella reintenta sola cada 30 s: esperar 30 s y pedir la
   hora otra vez.
3. Si sigue igual: cerrar el programa (Esc), apagar y encender los 12 V, esperar 10 s y abrir el programa otra vez.
4. Respaldo, en otra ventana de PowerShell y **solo cuando la mano no esté deletreando**:
   ```
   py -3.11 fusion/hora.py --decir --voz lina
   ```
   Voces: `jeanpaul`, `harry`, `lina`, `paula`. Si `mano.local` no responde, prueba solo con la `IP_FIJA` de
   `secretos.py`; también se puede dar la IP: `--ip 192.168.43.228`.

El resto del programa no se afecta: si la hora no funciona, se sigue con los nombres normalmente.

### Otros mensajes

| Mensaje | Qué hacer |
|---|---|
| «La mano rechazó el TOKEN del WiFi» | El TOKEN de `secretos.py` no coincide con el de `config_wifi.py`. No se arregla en vivo: seguir sin la hora. |
| «La mano está ocupada» | Esperar a que termine el deletreo o la conexión y pedir la hora otra vez. |
| «Falta audio de la fecha …: suena solo la hora» | La fecha de hoy no está generada (solo hay del 12-11-2026 al 31-12-2026). Suena solo la hora. |
| «Mano: sin conexión (r = reintentar)» | Pulsar r. Si no conecta: Thonny cerrado, 12 V conectados, Bluetooth del PC activado; si no, apagar y encender los 12 V. |
| La mano deletrea pero no suena | Seguir: el nombre queda guardado en `fusion/salidas/`. |

### PLAN B DE AUDIO: el parlante de la mano suena con interferencia o no suena

La interferencia es de hardware (contacto o alimentación del MAX98357), no del programa: con o sin WiFi pasa a
ratos. Si aparece durante la sustentación:

1. Cerrar el programa (Esc).
2. Abrir el programa con la voz por los **parlantes del PC**:
   ```
   py -3.11 fusion/dibujar_fusion.py --voz-pc
   ```
3. Arriba debe decir **«Mano: conectada (voz-2 · voz por el PC)»**.

Con `--voz-pc` la mano deletrea igual por Bluetooth; solo cambia por dónde sale el sonido:
- los **nombres** con las mismas grabaciones originales (`fusion/audios_placa/`): la frase grabada si existe; si
  no, las palabras sueltas con 250 ms;
- la **fecha y la hora** (botón Hora o tecla h) con los mismos audios, **sin WiFi**: no importa si el punto de
  acceso está apagado;
- Esc durante el deletreo también corta la voz del PC.

Subir el volumen del PC antes de empezar. Sin `--voz-pc` todo funciona como siempre (voz por la placa).

## 5. Comandos de respaldo

Con `dibujar_fusion.py` **cerrado** (un solo programa puede usar el Bluetooth de la mano):

```
py -3.11 fusion/consola_mano.py                     consola de la mano: !version, lina, !voz lina, reset, salir
py -3.11 fusion/voz.py --texto "Lina" --deletrear   deletrea con el panel y suena
```

Con o sin `dibujar_fusion.py` abierto (va por WiFi; solo cuando la mano no esté deletreando):

```
py -3.11 fusion/hora.py --decir --voz lina
```

Plan B (por los parlantes del PC, sin WiFi ni placa):

```
py -3.11 fusion/dibujar_fusion.py --voz-pc          todo el programa, con las voces en el PC
py -3.11 fusion/hora.py --decir --voz lina --pc     solo la fecha y la hora, en el PC
```

## 6. Para explicar al jurado

- Los **nombres** suenan con la **grabación original** de cada integrante (`voces/`), nunca con voz sintética.
- La **fecha y la hora** usan la voz **clonada** de cada integrante (modelo F5 del proyecto Doby, local, sin
  internet), revisada con Whisper y escuchada antes de usarla. Es la única parte con voz clonada.
- La mano recibe las órdenes por **Bluetooth (BLE)**; el **WiFi** solo lleva el audio de la fecha y la hora, que
  suena mientras llega (la placa no tiene memoria para guardarlo entero).
- Todo funciona en local: OCR (TrOCR), voces y control, sin servicios en la nube.
