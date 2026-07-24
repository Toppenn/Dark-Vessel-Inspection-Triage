"""Streamlit frontend (Phase 5): the triage view a coastguard officer reads.

This is only a presentation layer. All the reasoning lives in the modules it
imports — the deterministic engine (analysis), the environmental gate
(environment), the agents, and the validator that gates their output. The UI
never computes a position, a score or a classification of its own.

    pip install -r requirements.txt
    export NVIDIA_API_KEY='nvapi-...'     # only needed for the agent step
    streamlit run src/app.py
"""

import json
import sys
from pathlib import Path

import streamlit as st

# The sibling modules (analysis, data, …) use bare imports and assume src/ is on
# the path. `streamlit run src/app.py` and `python src/main.py` both provide that;
# this guard makes it hold under any launcher (e.g. the app-testing harness) too.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import analysis
import data
import validate

# The agent layer needs the OpenAI SDK; the deterministic view must work without
# it, exactly as `main.py --cross-reference-only` does.
try:
    import agents
except ImportError:
    agents = None

# Colour by classification: red = act first, amber = look, grey = context only.
# RGBA, reused for both the map points and the summary chips.
_COLOURS = {
    "high_priority": (214, 40, 40, 220),
    "medium_priority": (243, 166, 30, 220),
    "below_candidate_threshold": (140, 140, 140, 160),
    "no_indicators": (140, 140, 140, 120),
    "ais_not_applicable": (90, 140, 200, 160),
}


def _rgba_css(cls: str) -> str:
    r, g, b, a = _COLOURS.get(cls, (140, 140, 140, 160))
    return f"rgba({r},{g},{b},{a / 255:.2f})"


@st.cache_data
def _run_engine(zones_file: str, detections_file: str) -> dict:
    """Deterministic dossier. Cached on the file names; cheap and reproducible."""
    return analysis.analyse(data.load_zones(zones_file),
                            data.load_detections(detections_file))


def _map(dossier: dict) -> None:
    import pydeck as pdk

    records = dossier.get("records", [])
    points = [{
        "id": r["id"],
        "lat": r["position"]["lat"],
        "lon": r["position"]["lon"],
        "classification": r["classification"],
        "colour": list(_COLOURS.get(r["classification"], (140, 140, 140, 160))),
        # Candidates get a larger marker so the eye lands on them first.
        "radius": 1400 if r["classification"] in analysis.CANDIDATE_CLASSES else 700,
    } for r in records]

    # GeoJSON polygon order is [lon, lat]; our zones are stored as [lat, lon].
    zones = [{
        "name": z["name"],
        "polygon": [[lon, lat] for lat, lon in z["polygon"]],
    } for z in data.load_zones()["zones"]]

    layers = [
        pdk.Layer(
            "PolygonLayer", zones, get_polygon="polygon",
            get_fill_color=[30, 90, 160, 40], get_line_color=[30, 90, 160, 180],
            line_width_min_pixels=1, pickable=True, stroked=True, filled=True),
        pdk.Layer(
            "ScatterplotLayer", points, get_position=["lon", "lat"],
            get_fill_color="colour", get_radius="radius", pickable=True),
    ]
    view = pdk.ViewState(
        latitude=sum(p["lat"] for p in points) / len(points),
        longitude=sum(p["lon"] for p in points) / len(points),
        zoom=8.2) if points else pdk.ViewState(latitude=36.6, longitude=-6.9, zoom=8)
    st.pydeck_chart(pdk.Deck(
        layers=layers, initial_view_state=view,
        tooltip={"text": "{id} {name}\n{classification}"}))


def _candidate_rows(dossier: dict) -> list:
    rows = []
    for r in dossier["inspection_candidates"]:
        rows.append({
            "id": r["id"],
            "priority": r["classification"].replace("_priority", ""),
            "position": f"{r['position']['lat']}, {r['position']['lon']}",
            "length_m": r["estimated_length_m"],
            "AIS": r["ais"],
            "indicators": len(r["potential_indicators"]),
            "km_from_base": r.get("distance_from_base_km", "—"),
        })
    return rows


def _agent_step(dossier: dict) -> None:
    """Run both agents, gate each output through the validator, then display.

    Same contract as main.py: an output with blocking issues is withheld, never
    shown as if it were fit for an inspector."""
    prioritisation = agents.prioritise(dossier)
    pri_issues = validate.validate_prioritisation(dossier, prioritisation)
    if validate.has_blockers(pri_issues):
        st.error("Analyst output withheld — blocking validation issues:")
        st.code(validate.format_issues(pri_issues))
        return
    st.session_state["prioritisation"] = prioritisation
    st.session_state["pri_issues"] = pri_issues

    report = agents.write_briefs(dossier, prioritisation)
    rep_issues = validate.validate_report(dossier, report)
    if validate.has_blockers(rep_issues):
        st.error("Report withheld — blocking validation issues. The briefs are "
                 "not shown; only the issues are.")
        st.code(validate.format_issues(rep_issues))
        return
    st.session_state["report"] = report
    st.session_state["rep_issues"] = rep_issues


st.set_page_config(page_title="Dark-vessel inspection triage", page_icon="🛰️",
                   layout="wide")
st.title("🛰️ Dark-vessel inspection triage")
st.caption("Prioritises and justifies — it does not accuse. Every figure is "
           "computed deterministically; the decision to inspect is always human.")

with st.sidebar:
    st.header("Scene")
    zones_file = st.text_input("Regulatory layer", "zones.json")
    detections_file = st.text_input("Detections", "detections.json")
    st.divider()
    run_agents = st.button("Run agent analysis", type="primary",
                           disabled=agents is None,
                           help="Needs NVIDIA_API_KEY. The deterministic view "
                                "below always works without it.")
    if agents is None:
        st.info("Install dependencies (`pip install -r requirements.txt`) to "
                "enable the agent step.")

try:
    dossier = _run_engine(zones_file, detections_file)
except (OSError, KeyError, ValueError) as exc:
    st.error(f"Could not load or analyse the scene: {exc}")
    st.stop()

env = dossier.get("environmental_context", {})
suit_colour = {"high": "🔴", "moderate": "🟠", "low": "⚪"}.get(env.get("suitability"), "")
st.subheader(f"Environmental context — {suit_colour} angula suitability "
             f"{env.get('suitability', 'n/a').upper()}")
c1, c2, c3 = st.columns(3)
c1.metric("Moon phase", env.get("moon_phase", "—"))
c2.metric("Moon illumination", f"{env.get('moon_illumination', 0):.0%}")
c3.metric("Spring-tide tendency", f"{env.get('spring_tide_tendency', 0):.0%}")
st.caption(f"{env.get('rationale', '')}  "
           f"_Scanning-priority signal only — never a per-vessel indicator._")

st.divider()
summary = dossier["classification_summary"]
cols = st.columns(len(summary) or 1)
for col, (cls, count) in zip(cols, summary.items()):
    col.markdown(
        f"<div style='border-left:4px solid {_rgba_css(cls)};padding-left:.6rem'>"
        f"<div style='font-size:1.6rem;font-weight:700'>{count}</div>"
        f"<div style='opacity:.7'>{cls.replace('_', ' ')}</div></div>",
        unsafe_allow_html=True)

for closure in dossier["active_closures"]:
    st.warning(f"Active closure: **{closure['zone']}** ({closure['reason']})")

st.subheader("Scene map")
st.caption("Regulated zones shaded; larger markers are inspection candidates. "
           "Red = high priority, amber = medium, grey = context only.")
_map(dossier)

st.subheader(f"Inspection candidates ({len(dossier['inspection_candidates'])})")
st.dataframe(_candidate_rows(dossier), width="stretch", hide_index=True)

if run_agents:
    with st.spinner("Running analyst and writer agents, then validating…"):
        try:
            _agent_step(dossier)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Model call failed: {exc}\n\nCheck NVIDIA_API_KEY and the "
                     f"model identifiers.")

if st.session_state.get("prioritisation"):
    st.divider()
    st.subheader("Analyst prioritisation")
    for c in st.session_state["prioritisation"].get("prioritised_candidates", []):
        st.markdown(f"**{c.get('rank')}. {c.get('id')}** "
                    f"— {c.get('indicator_type')} · confidence {c.get('confidence')}  \n"
                    f"{c.get('reason')}")
    st.info(st.session_state["prioritisation"].get("overall_recommendation", ""))

if st.session_state.get("report"):
    report = st.session_state["report"]
    st.divider()
    st.subheader("Executive summary")
    st.write(report.get("executive_summary", ""))
    st.subheader("Inspection briefs")
    for b in report.get("inspection_briefs", []):
        pos = b.get("position")
        if isinstance(pos, dict):
            pos = f"{pos.get('lat')}, {pos.get('lon')}"
        with st.expander(f"[{str(b.get('priority', '')).upper()}] {b.get('id')} — {pos}"):
            for ind in b.get("indicators", []):
                st.markdown(f"- {ind}")
            st.markdown(f"**Regulation:** {b.get('regulation_concerned')}")
            st.markdown(f"**Action:** {b.get('suggested_action')}")
            st.markdown(f"**Caveat:** {b.get('caveat')}")
    st.caption(f"Methodological note: {report.get('methodological_note', '')} · "
               f"Human decision required: {report.get('human_decision_required', '')}")
    issues = st.session_state.get("rep_issues", [])
    (st.success if not issues else st.warning)(validate.format_issues(issues))
    st.download_button("Download full run (JSON)",
                       json.dumps({"dossier": dossier, "report": report},
                                  ensure_ascii=False, indent=2),
                       file_name="triage_run.json", mime="application/json")
