# Cómo funciona este laboratorio

Este texto está para explicarlo en una entrevista, en voz alta. Los números de latencia son **simulados**. No hay un teléfono de verdad atrás.

## La analogía

Imaginá un restaurante que toma reservas solo por teléfono.

1. La persona del otro lado habla. El mozo espera un silencio para estar seguro de que la frase terminó. Si corta antes, anota un pedido a medias. Si espera de más, la mesa se impacienta. Eso es el **VAD** (detección de voz) y el cierre de turno.
2. Recién ahí escribe lo que entendió. A veces cambia una palabra. Eso es el **STT**.
3. Decide: reservar, decir qué mesas hay, cancelar, o pasar la llamada a una persona. No inventa un plato ni da un consejo de salud. Eso es el **LLM de cassette** más el guardia clínico.
4. Anota la reserva en el libro. Si el lápiz se traba y prueba de nuevo, no puede escribir la misma mesa dos veces. Eso es el **webhook con idempotencia**.
5. Empieza a repetir la confirmación en voz alta. Si el cliente lo interrumpe, el mozo se calla. Si se calla porque pasó un camión, cortó al pedo. Eso es el **barge-in** y el falso corte.

El laboratorio mide esos cinco tiempos con un reloj de mentira. Cada espera sale de una lognormal con semilla (los parámetros están marcados [EST] en el código). No es la latencia de un proveedor pago. La compuerta mira el presupuesto; los números son un marcador de posición.

## La cascada, en una frase

Entra audio sintético (en realidad una lista de pedacitos con duración y texto). Sale una frase de confirmación, una derivación, o una reserva. En el medio hay cinco etapas. Mirá el diagrama del README: frames → VAD → STT → cassette → guardia → webhook → TTS, y al lado el corte si la persona habla de nuevo.

No es un modelo de punta a punta que escucha y habla en un solo salto. Es a propósito una cascada, porque ahí se ve **dónde** se fue el tiempo.

## Paso a paso

1. El guion arma frames. Un frame es habla, silencio o ruido, con milisegundos y un texto. No hace falta un WAV para la lógica. Hay un WAV de silencio de 20 ms solo para mostrar que la interfaz de audio existe (`fixtures/silence_20ms.wav`).
2. El VAD, con uno de tres perfiles, decide cuándo terminó el turno.
   - **aggressive**: silencio corto (180 ms) y umbral bajo. Corta rápido. También se confunde con un ruido de 100 ms.
   - **balanced**: 400 ms de silencio y un umbral que ignora ese ruido. Es el perfil que tiene que pasar la compuerta.
   - **patient**: 800 ms. Espera más. No se apura con una pausa de 300 ms.
3. El STT falso devuelve parciales (una palabra más por vez) y un final. Si el guion pide error, cambia palabras con una semilla fija. Eso simula acento o un ASR flojo. No es un corpus de acentos reales.
4. El clasificador dobla el texto (minúsculas, sin acentos) y elige: clínico, cancelar, reservar, horarios, o no entendido. La cassette dice qué herramienta llamar y qué frase decir. Los ids del turno los pone el guion, no el "modelo". Fijate en eso antes de venderlo como comprensión de lenguaje.
5. Si la frase de salida tiene una marca de consejo clínico (por ejemplo un fármaco o "mg"), el guardia la reemplaza por una derivación y no llama herramientas. En la regresión forzada ese guardia se apaga a propósito para demostrar que la compuerta se pone roja.
6. Cada herramienta pasa por el webhook local: firma HMAC, clave de idempotencia, reintentos con tope y jitter con semilla, y una cola de cartas muertas en JSONL si se acaban los intentos.
7. El TTS parte la frase en trozos y cobra un tiempo hasta el primer byte. Si durante esa "reproducción" entra habla, y el VAD la acepta, se cancela. Si entra ruido y el perfil lo toma como habla, es un falso corte.

El reloj simulado solo avanza en esas esperas del sistema. El tiempo en que la persona está hablando no se suma al end-to-end. El end-to-end arranca cuando la persona dejó de hablar y termina en el primer byte de audio de respuesta.

## Idempotencia, con la misma analogía

El cliente dice "anotá la mesa 4" y se corta la línea. El mozo no sabe si el lápiz llegó a tocar el papel. Vuelve a decirlo con el **mismo número de pedido**. El libro responde "ya está anotado, es esta reserva" y no abre otra. Si otro cliente pide la misma mesa con otro número de pedido, la respuesta es "ocupada" y se deriva. Eso es R01 y R02 del guion.

Si el lápiz ni siquiera tocó el papel (timeout antes de escribir) y los reintentos se agotan, el pedido va a la cola de cartas muertas y la persona es derivada. No queda una reserva fantasma. Eso es R04. `python -m voice_cascade dlq-replay` vuelve a intentar esa cola cuando el libro ya responde.

## Glosario

| Palabra | Qué quiere decir acá |
| --- | --- |
| Cascada | STT, después LLM, después TTS. Tres saltos, no uno. |
| VAD | Regla que dice "esto es habla" y "ya se calló". |
| Barge-in | La persona habla mientras el sistema todavía está "hablando", y hay que cortar. |
| Falso corte | Un ruido que el VAD tomó por habla y cortó la frase al pedo. |
| TTFT / TTFB | Tiempo hasta el primer token del modelo, o hasta el primer byte de audio. En el eval son sorteos **SIMULATED** con semilla, no un reloj de pared. |
| Cassette | Respuesta fija según la intención. No es un modelo entrenado. |
| Idempotencia | Misma clave, mismo resultado, un solo efecto. |
| DLQ | Cola de lo que no se pudo confirmar después de los reintentos. |
| Invariante | Una regla de efecto ("no hay dos reservas", "no hay consejo clínico"), no la lista exacta de tool calls. |

## Límites honestos

- No mide proveedores en CI. La tabla "Measured with real providers" del README tiene una corrida pegada a mano (n=20, un proveedor, una corrida, no es un SLA). El título del archivo tiene que ser exactamente ese. Si STT o TTS son un stub local, el archivo se llama "Partially measured" y no entra en esa tabla. Si falta configuración, o si la estimación pasa `MAX_LIVE_SPEND_USD`, el proceso sale con código 2 y no manda ningún request. `unsupported_availability_claim` es un heurístico: marca una hora, una fecha ("el 20 de octubre", "el 22", `20/10`), una confirmación ("agendé", "confirmado") o un turno en inglés ("Tuesday at 10am"), y solo si ese turno no llamó una herramienta de agenda. No marca una negación ("no puedo", "I can't") ni el horario de atención ("de lunes a viernes"). Puede fallar en los dos sentidos y no reemplaza una lectura humana. `cost.estimated_usd` es tokens por el precio del entorno. `provider_reported_usd` aparece solo si `usage.cost_in_usd_ticks` es un entero (1 tick = 1e-10 USD).
- El "LLM" no elige el id del turno leyendo la frase. Lo pone el guion.
- El VAD es un umbral de energía sobre frames sintéticos, no una red neuronal.
- No hay WebRTC, ni SIP, ni consentimiento de grabación, ni varios idiomas.
- Los nombres y teléfonos son inventados y además se redactan en los logs. Redactar ficción no es cumplir una ley de datos personales.
- La regresión `make eval-regression` **tiene que fallar**. Si pasa, la compuerta está rota.
