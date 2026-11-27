from flask import Flask, jsonify, request
from flasgger import Swagger
from proceso_electoral_mflask import ProcesoElectoralModel

# INICIALIZACIÓN DE LA APLICACIÓN Y SWAGGER
app = Flask(__name__)
# Configuración de la página interactiva de Swagger (http://127.0.0.1:5001/apidocs)
swagger = Swagger(app, template={
    "info": {
        "title": "Simulación Proceso Electoral — API Contrato v1.1",
        "description": "Servidor Flask + Mesa para sincronización con Unity (StateSync, LegacyGetAgents) e inspección en vivo.",
        "version": "1.1.0"
    }
})
# Instancia activa del modelo en memoria (un cliente Unity a la vez)
modelo_actual: ProcesoElectoralModel | None = None

# RUTA RAÍZ
@app.route("/", methods=["GET"])
def index():
    """Redirige la raíz directamente a la página interactiva de documentación y pruebas."""
    return redirect("/apidocs")

# ==============================================================================
# 1. GET /health — Unity lo llama antes de cada /init para validar conexión
# ==============================================================================
@app.route("/health", methods=["GET"])
def health():
    """
    Verifica que el servidor Flask esté activo y reporta el estado del modelo.
    ---
    tags:
      - Contrato Unity v1.1
    responses:
      200:
        description: Servidor disponible y listo.
    """
    return jsonify({
        "api_version": "1.1",
        "ok": True,
        "model": "ProcesoElectoralModel",
        "step": modelo_actual.current_step if modelo_actual else 0
    }), 200


# 2. POST /init — Inicialización o reinicio de la simulación
@app.route("/init", methods=["POST"])
def init_simulacion(): 
    """
    Inicializa o reinicia la elección electoral y devuelve el estado base (step 0).
    ---
    tags:
      - Contrato Unity v1.1
    parameters:
      - in: body
        name: body
        required: false
        schema:
          type: object
          properties:
            num_votantes:
              type: integer
              example: 10
            num_verificadores:
              type: integer
              example: 3
            num_mamparas:
              type: integer
              example: 2
            num_casillas:
              type: integer
              example: 1
            rng:
              type: integer
              example: 42
    responses:
      200:
        description: Simulación inicializada con layout del salón y agentes en step 0.
    """
    global modelo_actual
    data = request.get_json(silent=True) or {}

# Instanciar el modelo electoral con parámetros del request o valores por defecto
    modelo_actual = ProcesoElectoralModel(
        num_votantes=data.get("num_votantes", 15),
        num_verificadores=data.get("num_verificadores", 3),
        num_mamparas=data.get("num_mamparas", 2),
        num_casillas=data.get("num_casillas", 1),
        mapa_celdas=data.get("mapa_celdas"),
        rng=data.get("rng"),
    )

# Construir el payload inicial adjuntando la topología del salón y metadatos
    respuesta = modelo_actual.generar_respuesta_sync()
    respuesta["layout"] = modelo_actual.mapa_celdas
    respuesta["sim"] = {
        "num_votantes": modelo_actual.num_votantes,
        "candidatos": modelo_actual.candidatos,
        "edad_prioridad": modelo_actual.edad_prioridad,
    }

    return jsonify(respuesta), 200


# 3. POST /sync — Bucle principal de sincronización (1 paso = 1 minuto simulado)
@app.route("/sync", methods=["POST"])
def sync_step():
    """
    Avanza 1 minuto simulado: lee reportes de Unity, ejecuta model.step() y devuelve órdenes.
    ---
    tags:
      - Contrato Unity v1.1
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            ack_step:
              type: integer
              example: 0
            agents:
              type: array
              items:
                type: object
              example:
                - id: "1"
                  pos: [0, 0]
                  arrived: false
                  stuck: false
                  sees: []
            events:
              type: array
              items:
                type: object
              example: []
            crowd_costs:
              type: object
              example:
                "2,1": 0.2
    responses:
      200:
        description: Estado actualizado del minuto siguiente (agents, removed, events, tally, stats).
      400:
        description: El modelo no ha sido inicializado con POST /init.
      409:
        description: Desincronización de pasos (step_mismatch). Unity debe reiniciar con POST /init.
    """
    global modelo_actual 
    if modelo_actual is None:
        return jsonify({"error": "Modelo no inicializado. Llama primero a POST /init"}), 400

    payload = request.get_json(silent=True) or {}

    ack_step = payload.get("ack_step", 0)


# Caso A (Replay): Unity reenvió una petición atrasada -> devolver caché sin avanzar
    if ack_step < modelo_actual.current_step and modelo_actual.ultima_respuesta_sync is not None:
        return jsonify(modelo_actual.ultima_respuesta_sync), 200

# Caso B (Desincronización): Unity va adelantado al servidor -> forzar reinicio con 409
    if ack_step > modelo_actual.current_step:
        return jsonify({
            "error": "step_mismatch",
            "expected_step": modelo_actual.current_step,
            "received_ack_step": ack_step
        }), 409

# Caso C (Flujo normal):
    # 1. Leer reportes de Unity (ack_step, agents, events, crowd_costs)
    modelo_actual.leer_reportes(payload)

    # 2. Avanzar exactamente 1 minuto simulado
    modelo_actual.step()

    # 3. Contestar con agentes vivos, eventos del minuto, tally y stats
    respuesta = modelo_actual.generar_respuesta_sync()
    return jsonify(respuesta), 200

# ==============================================================================
# 4. GET /get_agents — Compatibilidad Legacy (HW01) e inspección rápida en navegador
# ==============================================================================
@app.route("/get_agents", methods=["GET"])
def get_agents():
    """
    Devuelve únicamente las posiciones (x, y) de los agentes activos (modo LegacyGetAgents).
    ---
    tags:
      - Legacy HW01 / Inspección
    responses:
      200:
        description: Lista simple de posiciones de agentes.
      400:
        description: Modelo no inicializado.
    """
    if modelo_actual is None:
        return jsonify({"error": "Modelo no inicializado. Llama primero a POST /init"}), 400


# Filtrar únicamente los votantes activos dentro del recinto
    agentes = [
        {
            "id": str(v.unique_id),
            "x": v.pos[0],
            "y": v.pos[1],
            "estado": v.estado
        }
        for v in modelo_actual.agents
        if v.vivo
    ]
    return jsonify({
        "step": modelo_actual.current_step,
        "agents": agentes
    }), 200



# PUNTO DE ENTRADA DEL SERVIDOR
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)