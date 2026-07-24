# Informe de cierre — Sistema de IA agéntica contra la pesca furtiva de angula

**Open Models Codefest 2026 (NVIDIA · Oracle · Open Hackathons)**
Caso de uso público: apoyo a la planificación de inspecciones pesqueras (SEPRONA,
guardacostas, agencias medioambientales) en desembocaduras del Golfo de Cádiz.

---

## 1. Resumen ejecutivo

El proyecto entrega un **sistema agéntico de triaje** que orquesta el ciclo ReAct
del roadmap —contexto ambiental → adquisición SAR → detección → cruce con AIS →
reporte— sobre **modelos abiertos NVIDIA Nemotron**, con una propiedad de diseño
que lo hace legítimo y no un generador de sospechas: **el deber de cautela en
ambas direcciones, garantizado en código, no en el prompt**.

El andamiaje de las **cinco fases** del roadmap está en pie y **verificado con
comprobaciones ejecutables** (sin clave, sin red, sin coste). Lo que resta no es
código, sino **ejecución con recursos externos** (imágenes SAR reales + GPU para
entrenar; token GFW / clave NVIDIA para datos y modelos en vivo) — y el sistema
está construido con esos puntos de integración explícitamente marcados.

---

## 2. La tesis del sistema

> Un prompt es una petición, no un contrato. Los modelos siguen instrucciones de
> forma aproximada, y aquí una respuesta aproximada puede **atribuir una
> infracción a un buque que cumple**, mover una coordenada, o **descartar en
> silencio un buque que el dossier dice que hay que inspeccionar**.

De ahí las dos decisiones que gobiernan todo el código:

1. **Separación determinista / razonamiento.** Posiciones, geometría, umbrales
   legales y puntuaciones se calculan en un motor puro y auditable
   (`analysis.py`). El LLM nunca inventa una cifra; razona y prioriza sobre
   hechos ya computados. *En un expediente sancionador, los datos no pueden
   salir de un modelo generativo.*
2. **El validador es el producto.** Cada garantía que debe cumplirse se
   **re-comprueba en código** (`validate.py`) antes de que un humano lea la
   salida. Si el modelo alucina, la salida se **retiene** y el proceso termina
   con código distinto de cero.

**Deber de cautela bidireccional**, la propiedad central:

- *No sobre-reportar*: no se acusa. El sistema prioriza y justifica; la decisión
  de inspeccionar es siempre humana. La ausencia de AIS **no** es indicador para
  buques por debajo del umbral legal de porte (15 m, Art. 10(1) Reg. (CE)
  1224/2009), que no están obligados a emitir.
- *No sub-reportar*: soltar un objetivo de alta prioridad es tan grave como
  acusar sin base. La omisión de un registro high-priority es un **bloqueo**.

---

## 3. Arquitectura

```
  Fase 3 · Ciclo ReAct                        Separación de responsabilidades
  ─────────────────────────                   ───────────────────────────────
  Paso 1  Contexto ambiental   environment.py  (luna/marea → prioridad de escaneo)
  Paso 2  Adquisición SAR      vision.py        (CA-CFAR, determinista, numpy)
  Paso 3  Detección            vision.py        (posición, eslora, confianza)
  Paso 4  Cruce con AIS        analysis.py      (motor determinista = la herramienta)
  Paso 5  Reporte de incidencia agents.py       (analista + redactor, Nemotron)
                               validate.py      (guardrail: retiene si alucina)
                               app.py / main.py (frontend Streamlit / CLI)
```

Los agentes corren contra un endpoint **OpenAI-compatible** (`NVIDIA_BASE_URL`).
Eso hace que **autohospedar un NIM de Nemotron sea cambiar una variable de
entorno, cero código** — la tesis de "modelos abiertos dentro del entorno de la
autoridad" es literal (ver `docs/DEPLOY_NIM_OCI.md`).

---

## 4. Estado por fase del roadmap

| Fase | Objetivo | Entregado | Verificación |
|---|---|---|---|
| **1.2** Preprocesado + etiquetado | Denoise de radar, etiquetar embarcaciones | `curation.py`: filtro Lee + CFAR → etiquetas **candidatas** YOLO + manifiesto, para revisión humana | Self-check: 3/3 objetivos → etiquetas YOLO válidas |
| **1.1 / 1.3** Dataset SAR / DB entorno | Sentinel-1 histórico, DB de mareas/AIS | Loader `.npy` listo; capa de entorno y datos simulados (`environment.py`, `data.py`) | — (necesita descarga Copernicus/ASF) |
| **2.1** Fine-tuning visión + TensorRT | Detector ligero optimizado | `train_detector.py`: valida/parte/emite `data.yaml`; export TRT como costurón GPU | Self-check: curar→validar→split→yaml; rechaza etiqueta corrupta |
| **2.2** System prompt agéntico | Rol del agente de vigilancia | `agents.py` (analista + redactor); documentado en `docs/PROMPTS.md` | Regla a regla, con la comprobación que la respalda |
| **3** Flujo agéntico (ReAct) | Ciclo autónomo de 5 pasos | Completo (ver §3) | Pipeline end-to-end determinista |
| **4.1** Evaluación del razonamiento | Evitar alucinaciones y falsos positivos | `eval_agent.py` (red-team del guardrail); supresión de **infraestructura fija** en el motor | 12/12 adversariales atrapados, 15/15 casos |
| **4.2** Optimización de latencia | Medir el flujo completo | `latency.py`: desglose por etapa | Ruta determinista ~1 ms / 13 detecciones |
| **5.1** Frontend | Alertas para el agente de campo | `app.py` (Streamlit + mapa pydeck) | AppTest headless |
| **5.2** Documentación | Prompts y modelos abiertos | `docs/PROMPTS.md`, este informe | — |

**Empaquetado (5.x):** `Dockerfile` (app CPU-only) + `docs/DEPLOY_NIM_OCI.md`
(NIM en OCI, shapes GPU, wiring de contenedores).

---

## 5. Inventario de artefactos

**Motor y razonamiento** (~4.300 líneas Python, `src/`):

| Archivo | Rol |
|---|---|
| `analysis.py` | Motor de cruce determinista — la herramienta que llaman los agentes |
| `validate.py` | Comprueba la salida del modelo contra el dossier; bloquea ante fallo |
| `agents.py` | Agentes Nemotron: analista + redactor |
| `environment.py` | Puerta de contexto ambiental (luna/marea) — prioridad de escaneo |
| `vision.py` | Detector SAR (CA-CFAR) — el detector del Paso 3 |
| `geo.py` | Punto-en-polígono y distancia; shapely opcional para GeoJSON real |
| `data.py` | Carga de datos — la frontera que cambia para ir a producción (adaptador GFW) |
| `main.py` / `app.py` | Orquestador CLI / vista de triaje Streamlit |
| `curation.py` | Curación de datos (Fase 1.2): etiquetas auto-candidatas |
| `train_detector.py` | Scaffold de entrenamiento (Fase 2.1) |
| `test_caution.py` | 62 pruebas: deber de cautela, invariantes, reglas del validador |
| `eval_agent.py` | Harness red-team (Fase 4.1): tasa de captura del guardrail |
| `latency.py` | Desglose de latencia (Fase 4.2) |

**Docs y empaquetado:** `docs/PROMPTS.md`, `docs/DEPLOY_NIM_OCI.md`, este informe,
`Dockerfile`, `requirements.txt` (core, instalable en 10 s), `requirements-train.txt`
(pesado, GPU, aislado).

---

## 6. Verificación (reproducible, sin clave ni red)

| Comprobación | Resultado |
|---|---|
| `test_caution.py` — deber de cautela, invariantes, reglas | **62/62** |
| `eval_agent.py` — guardrail contra alucinaciones de LLM | **15/15** (12/12 adversariales) |
| `vision.py` — recuperación CFAR sobre escena sintética | **4/4 objetivos**, 0 falsos |
| `curation.py` — etiquetas YOLO candidatas | 3/3, formato válido |
| `train_detector.py` — dataset training-ready + rechazo de etiqueta corrupta | OK |
| `geo.py` — ray-cast + rama GeoJSON (con y sin shapely) | OK |
| `latency.py` — ruta determinista | **~1 ms / 13 detecciones** |

Familias de fallo cubiertas por el red-team del guardrail: alucinación de id,
sobre-reporte (no-candidato, resucitar suprimido, brief a estructura fija),
sub-reporte (soltar high-priority), integridad de coordenadas, **mala atribución
de AIS** (citar el porte contra un buque emisor — el peor error del sistema), y
fabricación (regulación sin indicadores, indicador añadido, etiqueta de
categoría, tokens fabricados que sobreviven a la traducción).

---

## 7. Techos deliberados (honestidad de ingeniería)

Lo que **no** corre en este repositorio, marcado y sin fingir:

- **Detector CNN/TensorRT:** hoy el detector es CA-CFAR (clásico, determinista,
  auditable, corre en CPU con numpy). El detector fino se conecta en el seam
  `detect_vessels(backend='trt')` cuando existan pesos. *No hay un YOLO falso.*
- **Entrenamiento real:** `train_detector.py --train` hace el fine-tune + export
  TRT **solo si** hay GPU + framework; si no, falla con instrucción. **Nunca
  reporta una métrica que no midió.**
- **Etiquetas de curación:** son **auto-candidatas de CFAR para revisión
  humana**, marcadas `review_status: pending`. Sobre-confiar en ellas enseñaría
  al detector los propios falsos positivos del CFAR — se dice explícito.
- **Capa HTTP de GFW / llamadas al modelo en vivo:** el mapeo GFW→esquema está
  probado contra el modelo de datos real; la capa HTTP y los modelos Nemotron en
  vivo necesitan token/clave y red, con fallback a datos demo.

Convención `ponytail:` en el código para cada esquina cortada con su techo y su
vía de mejora.

---

## 8. Qué resta para producción

Ninguno es código de andamiaje; son **recursos externos** que encajan en costurones ya definidos:

1. **Datos SAR reales:** descargar chips Sentinel-1 GRD (Copernicus Data Space /
   ASF) como `.npy` → `curation.py --input`.
2. **Etiquetas verificadas:** revisar las candidatas de CFAR (quitar `pending`).
3. **GPU + entrenamiento:** `pip install -r requirements-train.txt` en host GPU →
   `train_detector.py --train` → `.engine` TensorRT → seam `backend='trt'`.
4. **Datos en vivo:** `GFW_TOKEN` (detecciones SAR reales) y `NVIDIA_API_KEY` o un
   NIM autohospedado (razonamiento).
5. **Polígonos reales:** cargar capas Natura 2000 / WDPA como geometría GeoJSON
   (`geo.py` ya las consume vía shapely).
6. **Calibración:** `length_sigma_m` contra Paolo et al. 2024; pesos de
   puntuación contra resultados de inspección reales.

---

## 9. Cómo ejecutarlo

Ver `README.md` (quickstart 1–9). Sin clave ni red: pruebas, harness de
evaluación, latencia, detector SAR, curación y scaffold de entrenamiento corren
tal cual. Con recursos: modelos Nemotron (hosted o NIM), GFW en vivo, entrenamiento GPU.

> El trabajo de esta sesión está pendiente de commit. Los números de §6 se
> reproducen ejecutando los archivos indicados desde `src/`.
