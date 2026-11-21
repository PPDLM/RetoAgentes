from flask import Flask, jsonify, request
from proceso_electoral_mesa import ProcesoElectoralModel

app = Flask(__name__)

# Instancia activa del modelo en memoria (un cliente Unity a la vez)
modelo_actual: ProcesoElectoralModel | None = None


@app.route("/init", methods=["POST"])
def init_simulacion():
    """Inicializa una nueva partida electoral y devuelve el estado base (step 0)."""
    global modelo_actual
    data = request.get_json(silent=True) or {}

    modelo_actual = ProcesoElectoralModel(
        num_votantes=data.get("num_votantes", 15),
        num_verificadores=data.get("num_verificadores", 3),
        num_mamparas=data.get("num_mamparas", 2),
        num_casillas=data.get("num_casillas", 1),
        mapa_celdas=data.get("mapa_celdas"),
        rng=data.get("rng"),
    )

    return jsonify(modelo_actual.generar_respuesta_sync()), 200


@app.route("/sync", methods=["POST"])
def sync_step():
    """
    Loop principal cada 1.5s reales (1 minuto simulado):
    1. Lee los reportes físicos de Unity.
    2. Corre model.step() una sola vez.
    3. Devuelve órdenes, eventos del minuto, escrutinio y estadísticas.
    """
    global modelo_actual
    if modelo_actual is None:
        return jsonify({"error": "Modelo no inicializado. Llama primero a POST /init"}), 400

    payload = request.get_json(silent=True) or {}

    # 1. Leer reportes de Unity (ack_step, agents, events, crowd_costs)
    modelo_actual.leer_reportes(payload)

    # 2. Avanzar exactamente 1 minuto simulado
    modelo_actual.step()

    # 3. Contestar con agentes vivos, eventos del minuto, tally y stats
    respuesta = modelo_actual.generar_respuesta_sync()
    return jsonify(respuesta), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)