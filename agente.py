"""Capa agentica sobre modelos abiertos NVIDIA Nemotron.

Dos agentes especializados:
  1. analista -> razona sobre el dossier factual y prioriza candidatas
  2. redactor -> convierte la priorizacion en fichas de inspeccion

Principio de diseno: el sistema PRIORIZA y JUSTIFICA. No acusa ni concluye
que exista infraccion. La decision de inspeccionar es siempre humana, y todo
output es trazable a los datos que lo originan.
"""

import json
import os

from openai import OpenAI

BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")

# OJO: verificad el identificador exacto en el catalogo de build.nvidia.com,
# los nombres de modelo cambian. Sobrescribible por variable de entorno.
MODELO = os.environ.get("NEMOTRON_MODEL", "nvidia/nemotron-3-super")


def _cliente() -> OpenAI:
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Falta NVIDIA_API_KEY. Sacala en build.nvidia.com y exportala:\n"
            "  export NVIDIA_API_KEY='nvapi-...'"
        )
    return OpenAI(base_url=BASE_URL, api_key=api_key)


def _completar(system: str, user: str, temperatura: float = 0.2) -> str:
    resp = _cliente().chat.completions.create(
        model=MODELO,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=temperatura,
        max_tokens=1500,
    )
    return "".join(c.message.content or "" for c in resp.choices).strip()


def _parsear_json(texto: str) -> dict:
    limpio = texto.strip()
    if limpio.startswith("```"):
        limpio = limpio.split("```")[1]
        if limpio.startswith("json"):
            limpio = limpio[4:]
    limpio = limpio.strip()
    try:
        return json.loads(limpio)
    except json.JSONDecodeError:
        ini, fin = limpio.find("{"), limpio.rfind("}")
        if ini != -1 and fin != -1:
            return json.loads(limpio[ini:fin + 1])
        raise


SYS_ANALISTA = """Eres un analista de apoyo a la inspeccion pesquera.
Recibes un dossier factual ya calculado: detecciones radar cruzadas con zonas
reguladas, vedas y emparejamiento AIS.

REGLAS INNEGOCIABLES:
- No inventes ni recalcules cifras. Usa solo las del dossier.
- Nunca afirmes que existe una infraccion. Hablas de INDICIOS que justifican
  o no una inspeccion.
- Las detecciones marcadas 'no_evaluable' estan por debajo del umbral legal de
  obligacion de AIS. NO las prioriza nunca y debes decir explicitamente por que
  quedan fuera.
- Una embarcacion identificada por AIS tambien puede presentar indicios: no
  confundas 'identificada' con 'conforme'.

Responde UNICAMENTE con un objeto JSON, sin texto adicional ni markdown:
{
  "candidatas_priorizadas": [
    {"id": "...", "orden": 1, "motivo": "1-2 frases citando los datos concretos",
     "tipo_indicio": "...", "confianza": "alta|media|baja"}
  ],
  "descartadas_por_cautela": ["id: motivo legal del descarte"],
  "patron_observado": "hay agrupacion espacial o temporal relevante?",
  "recomendacion_general": "2-3 frases para el responsable de inspeccion",
  "limitaciones": ["que no puede saber este analisis"]
}"""

SYS_REDACTOR = """Eres el redactor tecnico de un servicio de inspeccion pesquera.
Escribes fichas de inspeccion en espanol claro y preciso, para que un inspector
decida en menos de dos minutos a que posicion acudir.

REGLAS: no inventes datos; no afirmes infracciones, solo indicios; toda ficha
debe poder rastrearse hasta los datos de origen.

Responde UNICAMENTE con un objeto JSON, sin texto adicional ni markdown:
{
  "resumen_ejecutivo": "100-150 palabras sobre la escena analizada",
  "fichas_inspeccion": [
    {"id": "...", "posicion": "lat, lon", "prioridad": "alta|media|baja",
     "indicios": ["..."], "norma_afectada": "...",
     "actuacion_sugerida": "...", "salvedad": "que podria explicar el indicio sin infraccion"}
  ],
  "nota_metodologica": "una frase sobre el limite del metodo, para el expediente",
  "requiere_decision_humana": "que decide exactamente la persona responsable"
}"""


def analizar_con_agente(dossier: dict) -> dict:
    """Agente 1: prioriza candidatas y razona sobre el conjunto."""
    user = "Dossier factual del cruce:\n\n" + json.dumps(dossier, ensure_ascii=False, indent=2)
    return _parsear_json(_completar(SYS_ANALISTA, user))


def redactar(dossier: dict, priorizacion: dict) -> dict:
    """Agente 2: genera las fichas de inspeccion."""
    user = ("Dossier factual:\n\n" + json.dumps(dossier, ensure_ascii=False, indent=2)
            + "\n\nPriorizacion del analista:\n\n"
            + json.dumps(priorizacion, ensure_ascii=False, indent=2))
    return _parsear_json(_completar(SYS_REDACTOR, user, temperatura=0.3))
