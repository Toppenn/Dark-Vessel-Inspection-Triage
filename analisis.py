"""Herramienta determinista de cruce.

Esto NO es el LLM. Es la 'tool' que invocan los agentes: calculo puro,
reproducible y auditable. En un expediente de inspeccion las cifras y los
cruces geograficos no pueden salir de un modelo generativo.

PRINCIPIO DE CAUTELA, deliberado y explicito:
Un barco que no emite AIS NO es automaticamente un infractor. Los pesqueros
por debajo del umbral de eslora no estan obligados a emitir. El sistema los
marca como NO EVALUABLES y nunca los prioriza. Esto no es un detalle
tecnico: es lo que separa una herramienta de priorizacion legitima de una
maquina de acusar sin fundamento.
"""

from datetime import date, datetime

import geo


def _fecha_escena(escena: dict) -> date:
    ts = escena.get("timestamp", "")
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
    except ValueError:
        return date.today()


def _veda_activa(zona: dict, dia: date) -> bool:
    veda = zona.get("veda")
    if not veda:
        return False
    try:
        ini = date.fromisoformat(veda["inicio"])
        fin = date.fromisoformat(veda["fin"])
    except (KeyError, ValueError):
        return False
    return ini <= dia <= fin


def _arte_prohibida(zona: dict, arte: str) -> bool:
    prohibidas = zona.get("artes_prohibidas", [])
    return "todas" in prohibidas or arte in prohibidas


def _zonas_de(det: dict, zonas: list) -> list:
    return [z for z in zonas
            if geo.punto_en_poligono(det["lat"], det["lon"], z["poligono"])]


def evaluar_deteccion(det: dict, zonas: list, config: dict, dia: date) -> dict:
    """Devuelve la ficha de una deteccion con su puntuacion desglosada."""
    umbral_eslora = config["umbral_eslora_ais_m"]
    umbral_fs = config["umbral_fishing_score"]

    eslora = det.get("eslora_estimada_m", 0.0)
    oscuro = not det.get("ais_emparejado", False)
    obligado_ais = eslora >= umbral_eslora
    pescando = det.get("fishing_score", 0.0) >= umbral_fs
    arte = det.get("arte_probable", "desconocido")

    dentro = _zonas_de(det, zonas)
    infracciones = []
    for z in dentro:
        if _arte_prohibida(z, arte):
            infracciones.append({
                "zona": z["nombre"], "zona_id": z["id"],
                "motivo": f"arte '{arte}' prohibida en {z['tipo']}",
            })
        if _veda_activa(z, dia) and pescando:
            infracciones.append({
                "zona": z["nombre"], "zona_id": z["id"],
                "motivo": f"actividad pesquera durante veda ({z['veda']['motivo']})",
            })

    # --- Puntuacion desglosada y trazable ---
    puntos = []
    if oscuro and obligado_ais:
        puntos.append(("no emite AIS estando obligado por eslora", 40))
    if dentro:
        puntos.append((f"dentro de zona regulada ({dentro[0]['tipo']})", 25))
    if pescando:
        puntos.append(("comportamiento compatible con pesca activa", 20))
    if infracciones:
        puntos.append(("arte prohibida o veda activa en la zona", 15))

    total = sum(p[1] for p in puntos)

    # --- Clasificacion con la cautela por delante ---
    if oscuro and not obligado_ais:
        clase = "no_evaluable"
        total = 0
        nota = (f"Eslora estimada {eslora} m, por debajo del umbral de "
                f"obligacion de AIS ({umbral_eslora} m). No emitir no constituye "
                f"indicio. Excluido de la priorizacion.")
    elif total >= 70:
        clase = "prioridad_alta"
        nota = "Concurren varios indicios objetivos."
    elif total >= 40:
        clase = "prioridad_media"
        nota = "Indicios parciales; requiere contraste."
    elif total > 0:
        clase = "prioridad_baja"
        nota = "Indicio aislado."
    else:
        clase = "sin_indicios"
        nota = "Sin elementos que justifiquen inspeccion."

    ficha = {
        "id": det["id"],
        "posicion": {"lat": det["lat"], "lon": det["lon"]},
        "eslora_estimada_m": eslora,
        "ais": "no emparejado (oscuro)" if oscuro else "emparejado",
        "obligado_a_emitir_ais": obligado_ais,
        "fishing_score": det.get("fishing_score"),
        "velocidad_kn": det.get("velocidad_kn"),
        "arte_probable": arte,
        "zonas": [{"id": z["id"], "nombre": z["nombre"], "tipo": z["tipo"]} for z in dentro],
        "posibles_infracciones": infracciones,
        "puntuacion": total,
        "desglose_puntuacion": [{"factor": f, "puntos": p} for f, p in puntos],
        "clasificacion": clase,
        "nota": nota,
    }
    if not oscuro:
        ficha["identidad"] = {
            "mmsi": det.get("mmsi"), "nombre": det.get("nombre_buque"),
            "pabellon": det.get("pabellon"),
        }
    return ficha


def analizar(zonas_doc: dict, detecciones_doc: dict) -> dict:
    """Cruce completo. Devuelve el dossier factual que consumen los agentes."""
    config = zonas_doc["config"]
    zonas = zonas_doc["zonas"]
    escena = detecciones_doc["escena"]
    dia = _fecha_escena(escena)

    fichas = [evaluar_deteccion(d, zonas, config, dia)
              for d in detecciones_doc["detecciones"]]

    orden = {"prioridad_alta": 0, "prioridad_media": 1, "prioridad_baja": 2,
             "sin_indicios": 3, "no_evaluable": 4}
    fichas.sort(key=lambda f: (orden[f["clasificacion"]], -f["puntuacion"]))

    resumen = {}
    for f in fichas:
        resumen[f["clasificacion"]] = resumen.get(f["clasificacion"], 0) + 1

    vedas = [{"zona": z["nombre"], "motivo": z["veda"]["motivo"]}
             for z in zonas if _veda_activa(z, dia)]

    return {
        "escena": escena,
        "fecha_analisis": dia.isoformat(),
        "area_estudio": config.get("area_estudio"),
        "umbral_eslora_ais_m": config["umbral_eslora_ais_m"],
        "zonas_reguladas": [
            {"id": z["id"], "nombre": z["nombre"], "tipo": z["tipo"],
             "artes_prohibidas": z["artes_prohibidas"],
             "veda_activa": _veda_activa(z, dia)}
            for z in zonas
        ],
        "vedas_activas": vedas,
        "total_detecciones": len(fichas),
        "resumen_clasificacion": resumen,
        "fichas": fichas,
        "candidatas_inspeccion": [f for f in fichas
                                  if f["clasificacion"].startswith("prioridad")],
        "excluidas_por_cautela": [f for f in fichas
                                  if f["clasificacion"] == "no_evaluable"],
    }
