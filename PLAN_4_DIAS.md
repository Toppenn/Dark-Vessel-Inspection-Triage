# Plan hasta el 26 de julio — Pesca ilegal

**Hoy es miércoles 22.** Quedan 4 días. Enviamos el **domingo 26 por la mañana**.

## Reparto

| | Rol | Responsable de que funcione |
|---|---|---|
| **P1** | Líder / Agentes | Repo, orquestación, `agente.py`, coordinar |
| **P2** | Datos | Global Fishing Watch, xView3, capas de zonas → `datos.py` |
| **P3** | Infra / Modelo | Cuentas NVIDIA, NIM, calidad de las respuestas |
| **P4** | Producto / Solicitud | Formulario, texto en inglés, email a EFCA, demo |

---

## HOY (miércoles 22) — 2 horas

**Todos**
- [ ] Idea cerrada: **pesca ilegal / barcos oscuros**. No se reabre.
- [ ] Cada uno crea cuenta en **build.nvidia.com** y saca su **API key** (`nvapi-...`).

**P1**
- [ ] Repo en GitHub. Al crearlo, "Add a license" → **Apache License 2.0**. Subir el esqueleto. Añadir a los otros 3.

**P3**
- [ ] `pip install -r requirements.txt` → `python src/main.py --solo-cruce` (funciona sin key).
- [ ] Con key: `export NVIDIA_API_KEY='nvapi-...'` → `python src/main.py`.
- [ ] **Verificar el identificador exacto del modelo** en build.nvidia.com y ajustar `MODELO` en `agente.py`. Es el fallo más probable del primer día.

**P2**
- [ ] Registrarse en **Global Fishing Watch** y pedir acceso a la API. *Hacedlo hoy: si tarda en aprobarse, no os pilla el domingo.*

**P4**
- [ ] Inventario de qué piden los pasos 2, 3 y 4 del formulario.

**Objetivo de hoy:** que el prototipo escupa fichas de inspección. Aunque sea con datos sintéticos.

---

## JUEVES 23 — datos reales

**P2** (día grande)
- [ ] Descargar del portal de GFW el dataset **"Vessel detections from Sentinel-1 SAR"** de **una** zona y **un** periodo. Una sola.
- [ ] Mirar **xView3** y anotar si nos sirve para fase 2 (detector propio). Hoy no se toca código de visión.
- [ ] Bajar una capa real de **zonas marinas protegidas** (Natura 2000 marino o WDPA) de esa misma zona.
- [ ] Elegir el área de la demo: que tenga zona protegida y actividad pesquera.

**P1 + P3**
- [ ] Afinar prompts. Que el JSON salga siempre parseable.
- [ ] **Verificar el umbral de eslora de obligación de AIS** y su base legal. Está en `zonas.json` como parámetro con un aviso. Es el dato que sostiene toda la defensa ética del proyecto: hay que citarlo bien.

**P4**
- [ ] Descripción del proyecto en inglés (base en el README).
- [ ] Redactar el email a EFCA / Secretaría General de Pesca.

---

## VIERNES 24 — conectar

**P2 + P1**
- [ ] Sustituir **al menos una** fuente sintética por real en `datos.py`. La más fácil: las detecciones de GFW.
- [ ] Que el sistema genere fichas de una zona real con su zonificación real.
- [ ] Sustituir el ray casting por shapely **solo si** los polígonos reales lo exigen. Si no, no tocar.

**P4**
- [ ] **Enviar el email.** Presentaos como equipo universitario candidato a un programa de NVIDIA que quiere validar el caso de uso. Aunque no contesten, cuenta.
- [ ] Pasos 1 y 2 del formulario.

**P3**
- [ ] Probar Nemotron Nano vs Super por agente. Anotar cuál va mejor: es material de solicitud.

---

## SÁBADO 25 — pulir y redactar

**Todos**
- [ ] README con **captura de la salida real**. Es lo que demuestra que existe.
- [ ] Revisar el formulario entero juntos.
- [ ] *Application Domain*: **Agentic AI**, Computer Vision and Machine Vision, Image Processing, Machine Learning and AI, Natural Language Processing.

---

## DOMINGO 26 — enviar por la mañana

- [ ] Repo **público** y `LICENSE` presente.
- [ ] Enviar. Guardar copia.

---

## Reglas para no descarrilar

1. **Una zona. Un periodo.** Todo "y si también..." se anota para septiembre.
2. **No entrenéis ningún detector ahora.** Usamos detecciones ya hechas. El detector propio es fase 2.
3. **Si una fuente se atasca más de 3 horas, se queda sintética** y seguimos. La solicitud no exige datos reales, exige que dominéis vuestro código.
4. **Nadie toca la regla de cautela.** El umbral de eslora y la exclusión de "no evaluables" no se quitan para que salgan más candidatas. Es el corazón defendible del proyecto.
5. El objetivo de estos 4 días no es un producto. Es **demostrar que ejecutáis**.

---

## Lo que NO hay que hacer

- Entrenar modelos de visión.
- Montar interfaz web (septiembre, si acaso).
- Procesar imágenes Sentinel-1 crudas. Detecciones ya hechas.
- Enviar el domingo a las 23:50.
