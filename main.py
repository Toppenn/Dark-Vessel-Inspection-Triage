"""Orquestador.

Flujo:  detecciones + capa legal -> cruce determinista -> agente analista
        -> agente redactor -> fichas de inspeccion

Uso:
    export NVIDIA_API_KEY='nvapi-...'
    python src/main.py

    # Solo el cruce, sin llamar al modelo:
    python src/main.py --solo-cruce
"""

import argparse
import json
import sys

import analisis
import datos


def separador(titulo: str) -> None:
    print("\n" + "=" * 72)
    print(titulo)
    print("=" * 72)


def imprimir_dossier(d: dict) -> None:
    separador(f"DOSSIER FACTUAL - {d['area_estudio']} - escena {d['escena']['timestamp']}")
    print(f"Detecciones analizadas: {d['total_detecciones']}")
    print(f"Umbral de obligacion AIS aplicado: {d['umbral_eslora_ais_m']} m")
    if d["vedas_activas"]:
        for v in d["vedas_activas"]:
            print(f"Veda activa: {v['zona']} ({v['motivo']})")
    print("\nClasificacion:")
    for clase, n in d["resumen_clasificacion"].items():
        print(f"  {clase:<18} {n}")

    print("\n--- CANDIDATAS A INSPECCION ---")
    for f in d["candidatas_inspeccion"]:
        ident = ""
        if "identidad" in f and f["identidad"].get("nombre"):
            ident = f" [{f['identidad']['nombre']} / {f['identidad']['pabellon']}]"
        print(f"\n  {f['id']}{ident}  puntuacion {f['puntuacion']} -> {f['clasificacion'].upper()}")
        print(f"    Pos {f['posicion']['lat']}, {f['posicion']['lon']} | "
              f"eslora {f['eslora_estimada_m']} m | AIS: {f['ais']} | "
              f"arte probable: {f['arte_probable']}")
        for z in f["zonas"]:
            print(f"    Zona: {z['nombre']} ({z['tipo']})")
        for inf in f["posibles_infracciones"]:
            print(f"    Indicio: {inf['motivo']}")
        for dg in f["desglose_puntuacion"]:
            print(f"      +{dg['puntos']:<3} {dg['factor']}")

    print("\n--- EXCLUIDAS POR CAUTELA (no priorizables) ---")
    for f in d["excluidas_por_cautela"]:
        print(f"  {f['id']}: {f['nota']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--solo-cruce", action="store_true")
    parser.add_argument("--zonas", default="zonas.json")
    parser.add_argument("--detecciones", default="detecciones.json")
    args = parser.parse_args()

    zonas_doc = datos.cargar_zonas(args.zonas)
    det_doc = datos.cargar_detecciones(args.detecciones)

    # --- Paso 1: cruce determinista (la "tool") ---
    dossier = analisis.analizar(zonas_doc, det_doc)
    imprimir_dossier(dossier)

    if args.solo_cruce:
        return 0

    if agente is None:
        print("\n[ERROR] No se pudo importar 'agente'. Instala las dependencias:"
              "\n  pip install -r requirements.txt", file=sys.stderr)
        return 1

    # --- Paso 2: agente analista ---
    try:
        priorizacion = agente.analizar_con_agente(dossier)
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] Fallo al llamar al modelo: {exc}", file=sys.stderr)
        print("Comprueba NVIDIA_API_KEY y el identificador del modelo "
              "(variable NEMOTRON_MODEL).", file=sys.stderr)
        return 1

    separador("PRIORIZACION DEL AGENTE ANALISTA")
    for c in priorizacion.get("candidatas_priorizadas", []):
        print(f"  {c.get('orden')}. {c.get('id')} "
              f"[{c.get('tipo_indicio')}, confianza {c.get('confianza')}]")
        print(f"     {c.get('motivo')}")
    print("\nDescartadas por cautela:")
    for x in priorizacion.get("descartadas_por_cautela", []):
        print(f"  - {x}")
    print(f"\nPatron observado: {priorizacion.get('patron_observado', 'n/d')}")
    print(f"Recomendacion: {priorizacion.get('recomendacion_general', 'n/d')}")

    # --- Paso 3: agente redactor ---
    informe = agente.redactar(dossier, priorizacion)

    separador("RESUMEN EJECUTIVO")
    print(informe.get("resumen_ejecutivo", ""))

    separador("FICHAS DE INSPECCION")
    for f in informe.get("fichas_inspeccion", []):
        print(f"\n  [{str(f.get('prioridad', '')).upper()}] {f.get('id')} - {f.get('posicion')}")
        for i in f.get("indicios", []):
            print(f"    - {i}")
        print(f"    Norma: {f.get('norma_afectada')}")
        print(f"    Actuacion: {f.get('actuacion_sugerida')}")
        print(f"    Salvedad: {f.get('salvedad')}")

    print(f"\nNota metodologica: {informe.get('nota_metodologica', '')}")
    print(f"Decision humana requerida: {informe.get('requiere_decision_humana', '')}")

    with open("ultima_salida.json", "w", encoding="utf-8") as f:
        json.dump({"dossier": dossier, "priorizacion": priorizacion, "informe": informe},
                  f, ensure_ascii=False, indent=2)
    print("\n(Salida completa en ultima_salida.json)")
    return 0


if __name__ == "__main__":
    try:
        import agente
    except ImportError:
        agente = None
    sys.exit(main())
