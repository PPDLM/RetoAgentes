from collections import deque
import json
import mesa
from mesa.time import Priority

ESTADOS_UNITY = {
    "En camino": "en_route",
    "Esperando verificación": "waiting_verification",
    "Yendo a verificación": "en_route",
    "Verificando": "verifying",
    "Esperando mampara": "waiting_booth",
    "Yendo a mampara": "en_route",
    "En mampara": "in_booth",
    "Esperando casilla": "waiting_ballot_box",
    "Yendo a casilla": "en_route",
    "En casilla": "at_ballot_box",
    "Finalizado": "finished",
    "Abandonó": "abandoned",
    "Evacuado": "evacuated",
}

class Casilla:# Clase para representar la casilla electoral y llevar el conteo de votos por candidato
    """Representa una urna electoral y lleva el conteo de votos válidos."""

    def __init__(self, numero: int, candidatos: list[str]):
        self.id = numero
        self.disponible = True
        self.votos = {candidato: 0 for candidato in candidatos}
# Método para registrar un voto para un candidato específico
    def registrar_voto(self, voto: str | None) -> None: # voto puede ser un candidato o "Voto Nulo"
        if voto in self.votos:
            self.votos[voto] += 1


class Votante(mesa.Agent):
    """Agente ciudadano que recorre las etapas de la casilla electoral."""

    def __init__(self, model: "ProcesoElectoralModel"): # model es una referencia al modelo que contiene al agente
        super().__init__(model)  # Asigna self.unique_id automáticamente y registra en model.agents
        self.estado = "En camino"
        self.llegada = 0.0
        self.salida = 0.0
        self.edad = self.random.randint(self.model.edad_min, self.model.edad_max) # Edad aleatoria, entre edad_min y edad_max, edad_min y edad_max se definen en el modelo
        self.voto: str | None = None # Voto elegido, puede ser un candidato o "Voto Nulo"
        self.recurso_asignado: int | None = None # Índice del recurso (verificador, mampara o casilla) asignado al votante
        self.evento_pendiente = None # Referencia al evento programado en el calendario DEVS, para poder cancelarlo si es necesario

        # Estado físico y de navegación (sincronizado con Unity)
        self.vivo: bool = True
        self.pos: list[int] = list(self.model.mapa_celdas["entrada"])
        self.celda_destino: list[int] = list(self.model.mapa_celdas["entrada"])
        self.orden: str = "hold"  # "move" | "hold"
        self.llego_a_destino: bool = False
        self.atorado: bool = False
        self.percepcion: list = []

        self.duracion_pendiente: int = 0

        self.duracion_pendiente: int = 0
        self.pasos_en_transito: int = 0  # Para timeout de 5 minutos en tránsito
        self.prioridad: bool = self.edad >= self.model.edad_prioridad
    # --- Helpers de navegación hacia Unity ---

    def mover_a(self, celda: list[int] | tuple[int, int]) -> None:
        destino = list(celda)
        if self.pos == destino:
            self.celda_destino = destino
            self.orden = "hold"
            self.llego_a_destino = True
        else:
            self.celda_destino = destino
            self.orden = "move"
            self.llego_a_destino = False

    def detener(self) -> None:
        self.orden = "hold"


    # --- Decisiones autónomas del agente ---

    def elegir_candidato(self) -> None:
        if self.random.random() < 0.02: # 2% de probabilidad del voto nulo segun lo investigado
            self.voto = "Voto Nulo"
        else:
            self.voto = self.random.choice(self.model.candidatos) # Elige un candidato al azar de la lista de candidatos del modelo

    def decidir_formarse(self, personas_en_fila: int) -> str: 
        n = self.model.num_votantes # Número total de votantes en el modelo

        # Determina la probabilidad de abandonar la fila según el porcentaje de personas en la fila
        if personas_en_fila < round(n * 0.20): 
            probabilidad = 0.10
        elif personas_en_fila < round(n * 0.40):
            probabilidad = 0.40
        else:
            probabilidad = 0.80

        # aqui el agente decide si abandonar o formarse en la fila según la probabilidad calculada}
        if self.random.random() < probabilidad:
            return "Abandonar"  
        else :
            return "Formarse" 

    # Desicion para ceder un lugar, segun la edad y que tan atras este
    # Entre más joven seas y más atrás estés en la fila, es más probable que cedas.
    # -> bool: Devuelve True si el votante decide ceder su lugar al recién llegado, False en caso contrario
    def decidir_ceder(self, recien_llegado: "Votante", posicion: int, largo_fila: int) -> bool: 

    
        if self.edad >= self.model.edad_prioridad and recien_llegado.edad <= self.edad:
            return False

        factor_posicion = (posicion + 1) / largo_fila
        factor_edad = (self.model.edad_max - self.edad) / (self.model.edad_max - self.model.edad_min) 
        probabilidad = factor_edad * factor_posicion
        return self.random.random() < probabilidad

    # --- Eventos discretos del ciclo de votación ---
    # en esta parte es donde quitamos lo de heapq y lo llevamos a la parte de mesa, 
    # ya que mesa tiene su propio scheduler y no necesitamos manejarlo manualmente

    # EVENTO 1: LLEGADA A LA CASILLA
    # Evento de llegada del votante a la casilla, decide si formarse o abandonar, 
    # y si se forma, se coloca en la fila de verificación
    def llegar(self) -> None: # -> None: indica que la función no devuelve ningún valor
        self.evento_pendiente = None 
        self.llegada = self.model.time
        personas_en_fila = len(self.model.fila_verificacion)

        if self.decidir_formarse(personas_en_fila) == "Abandonar":
            self.estado = "Abandonó"
            self.salida = self.model.time
            self.mover_a(self.model.mapa_celdas["salida"])
            self.model.registrar_evento(
                tipo="abandoned",
                votante=self,
                mensaje=f"Votante {self.unique_id:02d} decide abandonar la casilla",
            )
            return

        self.estado = "Esperando verificación"
        self.model.registrar_evento(
            tipo="joined_queue",
            votante=self,
            mensaje=f"Votante {self.unique_id:02d} ({self.edad} años) decide formarse",
        )

        # Cortesía hacia adultos mayores en la fila de verificación
        if self.edad >= self.model.edad_prioridad and personas_en_fila > 0:
            pos = personas_en_fila
            for i in range(personas_en_fila - 1, -1, -1): # Itera desde el final de la fila hacia el inicio, es desde personas_en_fila -1 de -1 en -1 
                persona = self.model.fila_verificacion[i] # Obtiene la persona en la posición i

                # Si la persona decide ceder su lugar, actualiza la posición y registra el evento
                if persona.decidir_ceder(self, i, personas_en_fila):
                    pos = i
                    tipo="yield_decision"
                    print(
                        f"        Votante {persona.unique_id:02d} ({persona.edad} años) "
                        f"cede su lugar a Votante {self.unique_id:02d} ({self.edad} años)"
                    )

                # Si la persona no cede su lugar, se detiene la iteración y registra el evento
                else:
                    print(
                        f"        Votante {persona.unique_id:02d} ({persona.edad} años) "
                        f"no cede su lugar a Votante {self.unique_id:02d} ({self.edad} años)"
                    )
                    break

        # Si se encontró una posición para ceder, inserta al votante en esa posición; de lo contrario, lo agrega al final de la fila
            self.model.fila_verificacion.insert(pos, self)
        else:
            self.model.fila_verificacion.append(self)

        self.model.asignar_verificadores() # Asigna verificadores a los votantes en la fila, para que puedan pasar a la etapa de verificación
        
    #Es el método que arranca el temporizador (schedule_event) únicamente cuando Unity confirma que el avatar ya llegó físicamente al módulo (arrived: true).
    def iniciar_atencion_en_recurso(self) -> None:
            self.pasos_en_transito = 0
            station = f"station_{self.recurso_asignado + 1}" if self.recurso_asignado is not None else None
            """Se dispara cuando Unity confirma que el votante llegó físicamente al módulo asignado."""
            if self.estado == "Yendo a verificación":
                self.estado = "Verificando"
                self.detener()
                self.evento_pendiente = self.model.schedule_event(
                    self.finalizar_verificacion,
                    after=self.duracion_pendiente,
                )
                self.model.registrar_evento(
                    tipo="verification_started",
                    votante=self,
                    recurso=self.recurso_asignado + 1,
                    mensaje=f"Votante {self.unique_id:02d} inicia verificación {self.recurso_asignado + 1}",
                )

            elif self.estado == "Yendo a mampara":
                self.estado = "En mampara"
                self.detener()
                self.elegir_candidato()
                self.evento_pendiente = self.model.schedule_event(
                    self.finalizar_mampara,
                    after=self.duracion_pendiente,
                )
                self.model.registrar_evento(
                    tipo="booth_started",
                    votante=self,
                    recurso=self.recurso_asignado + 1,
                    mensaje=f"Votante {self.unique_id:02d} inicia mampara {self.recurso_asignado + 1}",
                )

            elif self.estado == "Yendo a casilla":
                self.estado = "En casilla"
                self.detener()
                self.evento_pendiente = self.model.schedule_event(
                    self.finalizar_casilla,
                    after=self.duracion_pendiente,
                )
                self.model.registrar_evento(
                    tipo="deposit_started",
                    votante=self,
                    recurso=self.recurso_asignado + 1,
                    mensaje=f"Votante {self.unique_id:02d} deposita voto en casilla {self.recurso_asignado + 1}",
                )

    # EVENTO 2: VERIFICACIÓN
    # Evento de finalización de la verificación del votante, libera el verificador y pasa a la fila de mampara
    def finalizar_verificacion(self) -> None:
        self.evento_pendiente = None
        idx = self.recurso_asignado
        self.model.verificadores[idx] = True
        self.recurso_asignado = None

        self.estado = "Esperando mampara"
        self.model.fila_mampara.append(self)
        self.model.registrar_evento(
            tipo="FinVerificacion",
            votante=self,
            recurso=idx + 1,
            mensaje=f"Votante {self.unique_id:02d} termina verificación {idx + 1} y pasa a fila de mampara",
        )

        self.model.asignar_verificadores()
        self.model.asignar_mamparas()

    # EVENTO 3: MAMPARA
    def finalizar_mampara(self) -> None:
        self.evento_pendiente = None
        idx = self.recurso_asignado
        self.model.mamparas[idx] = True
        self.recurso_asignado = None

        self.estado = "Esperando casilla"
        self.model.fila_casilla.append(self)
        self.model.registrar_evento(
            tipo="FinMampara",
            votante=self,
            recurso=idx + 1,
            mensaje=f"Votante {self.unique_id:02d} sale de mampara {idx + 1} hacia la urna",
        )

        self.model.asignar_mamparas()
        self.model.asignar_casillas()

    # EVENTO 4: CASILLA
    def finalizar_casilla(self) -> None:
        self.evento_pendiente = None
        idx = self.recurso_asignado
        station = f"station_{idx + 1}"
        urna = self.model.casillas[idx]
        urna.registrar_voto(self.voto)
        urna.disponible = True
        self.recurso_asignado = None

        self.estado = "Finalizado"
        self.salida = self.model.time
        self.mover_a(self.model.mapa_celdas["salida"])
        self.model.registrar_evento(
            tipo="vote_counted",
            votante=self,
            station_id=station,
            mensaje=f"Votante {self.unique_id:02d} deposita voto y sale de la casilla",
        )
        self.model.asignar_casillas()


class ProcesoElectoralModel(mesa.Model):
    """Modelo DEVS en Mesa que coordina recursos, filas, eventos y telemetría para Unity."""

    def __init__( # Constructor del modelo, crea agentes Votante y programa eventos
        self,
        num_votantes: int = 5, # Número total de votantes que llegarán a la casilla
        num_verificadores: int = 3, # Número de verificadores disponibles para la etapa de verificación
        num_mamparas: int = 2, # Número de mamparas disponibles para la etapa de votación
        num_casillas: int = 1, # Número de casillas disponibles para la etapa de votación
        candidatos: list[str] | None = None,
        edad_min: int = 18,
        edad_max: int = 90,
        edad_prioridad: int = 65,
        mapa_celdas: dict | None = None,
        rng: int | None = None,
        
    ):
        # Coordenadas de celdas en el grid de Unity
        self.mapa_celdas = mapa_celdas or {
            "entrada": [0, 0],
            "salida": [0, 9],
            "fila_verificacion": [[2, 1], [2, 2], [2, 3], [2, 4], [2, 5]],
            "verificadores": [[4, 1], [4, 3], [4, 5]],
            "fila_mampara": [[6, 2], [6, 3], [6, 4]],
            "mamparas": [[8, 2], [8, 4]],
            "fila_casilla": [[10, 2], [10, 3]],
            "casillas": [[12, 3]],
        }

        super().__init__(rng=rng) # Inicializa el modelo con una semilla aleatoria para reproducibilidad
        self.num_votantes = num_votantes # Número total de votantes que llegarán a la casilla
        self.candidatos = candidatos or ["Candidato A", "Candidato B", "Candidato C"] # Lista de candidatos disponibles para la votación
        self.edad_min = edad_min
        self.edad_max = edad_max
        self.edad_prioridad = edad_prioridad

        # Control de sincronización con Flask/Unity
        self.current_step: int = 0
        self.last_ack_step: int = 0
        self._en_run_for: bool = False
        self.puerta_abierta: bool = True
        self.crowd_costs: dict[str, float] = {}
        self.umbral_congestion: float = 0.85

        # Recursos de la casilla
        self.verificadores = [True] * num_verificadores
        self.mamparas = [True] * num_mamparas
        self.casillas = [Casilla(i + 1, self.candidatos) for i in range(num_casillas)]

        # Filas de espera
        self.fila_verificacion: deque[Votante] = deque()
        self.fila_mampara: deque[Votante] = deque()
        self.fila_casilla: deque[Votante] = deque()

        # Registro de eventos para enviar a Unity
        self.historial_unity: list[dict] = []
        self.eventos_minuto: list[dict] = []

        # Recolector de métricas de Mesa
        self.datacollector = mesa.DataCollector( 
            # DataCollector de Mesa para recolectar métricas del modelo y de los agentes,
            #  que se pueden usar para análisis y visualización en Python
            model_reporters={
                "Finalizados": lambda m: len(m.agents.select(lambda a: a.estado == "Finalizado")),
                "Abandonaron": lambda m: len(m.agents.select(lambda a: a.estado == "Abandonó")),
                "Evacuados": lambda m: len(m.agents.select(lambda a: a.estado == "Evacuado")),
                "EnFilaVerificacion": lambda m: len(m.fila_verificacion),
            },
            agent_reporters={
                "Estado": "estado",
                "Edad": "edad",
                "Voto": "voto",
            },
        )
        self.removed_ids: list[str] = []
        self.ultima_respuesta_sync: dict | None = None
        self.arrival_timeout_steps: int = 5

        # Crear agentes Votante y programar llegadas
        Votante.create_agents(model=self, n=self.num_votantes)
        tiempo_llegada = 0
        for votante in self.agents:
            tiempo_llegada += self.random.randint(1, 4)
            votante.evento_pendiente = self.schedule_event(
                votante.llegar,
                at=tiempo_llegada,
                priority=Priority.DEFAULT,
            )

        # Programar evento externo (terremoto) con prioridad alta
        tiempo_terremoto = self.random.randint(10, 25)
        self.schedule_event(
            self.evento_terremoto,
            at=tiempo_terremoto,
            priority=Priority.LOW,
        )

    # =========================================================================
    # FASE 1 DEL /sync: LEER REPORTES DE UNITY
    # =========================================================================

    #Es el núcleo que lee el JSON de Unity (ack_step, agents, events, crowd_costs) 
    # y hace que model.step() avance exactamente 1 minuto simulado.
    
    def leer_reportes(self, payload: dict) -> None:
        """Procesa ack_step, agents, events y crowd_costs enviados por Unity."""
        self.eventos_minuto.clear()
        self.last_ack_step = payload.get("ack_step", self.last_ack_step)
        self.crowd_costs = payload.get("crowd_costs", {})

        agentes_por_id = {v.unique_id: v for v in self.agents}

        for info in payload.get("agents", []):
            vid = info.get("id")
            votante = agentes_por_id.get(vid)
            if not votante or not votante.vivo:
                continue

            if "pos" in info:
                votante.pos = list(info["pos"])
            if "stuck" in info:
                votante.atorado = bool(info["stuck"])
            if "sees" in info:
                votante.percepcion = info["sees"]

            if info.get("arrived"):
                votante.llego_a_destino = True
                if votante.estado.startswith("Yendo a "):
                    votante.iniciar_atencion_en_recurso()
                elif votante.estado in ("Finalizado", "Abandonó", "Evacuado"):
                    votante.vivo = False

        # Procesar eventos externos reportados por Unity (salio_del_salon, llego_a_destino, se_atoro, se_abrio_puerta)  
        for ev in payload.get("events", []):
            tipo_ev = ev.get("type") or ev.get("tipo")
            vid = ev.get("agent_id") or ev.get("votante_id")
            votante = agentes_por_id.get(vid) if vid is not None else None

            if tipo_ev == "exited" and votante:
                votante.vivo = False
                votante.detener()
                self.registrar_evento(
                    tipo="exited",
                    votante=votante,
                    mensaje=f"Votante {votante.unique_id:02d} salió físicamente del salón",
                )
                if vid not in self.removed_ids:
                    self.removed_ids.append(vid)

            elif tipo_ev == "arrived_at_target" and votante:
                votante.llego_a_destino = True
                if votante.estado.startswith("Yendo a "):
                    votante.iniciar_atencion_en_recurso()
                elif votante.estado in ("Finalizado", "Abandonó", "Evacuado"):
                    votante.vivo = False
                    if vid not in self.removed_ids:
                        self.removed_ids.append(vid)

            elif tipo_ev == "blocked_physically" and votante:
                votante.atorado = True
                self.registrar_evento(
                    tipo="blocked_physically",
                    votante=votante,
                    mensaje=f"ALERTA: Votante {votante.unique_id:02d} reporta atasco en {votante.pos}",
                )

            elif tipo_ev == "door_opened":
                self.puerta_abierta = True
                self.registrar_evento(
                    tipo="door_opened",
                    votante=votante,
                    mensaje="Se abrió la puerta de acceso a la casilla",
                )

    # =========================================================================
    # FASE 2 DEL /sync: AVANZAR UN MINUTO SIMULADO (model.step())
    # =========================================================================

    def step(self) -> None:
        """Avanza exactamente 1 minuto simulado (eventos DEVS + navegación de filas)."""
        if not self._en_run_for:
            self._en_run_for = True
            try:
                self.run_for(1)
            finally:
                self._en_run_for = False
            return

        self.current_step += 1
        self._actualizar_navegacion_filas() # Actualiza celdas destino de quienes esperan en fila y aplica 'hold' si hay congestión
        self.datacollector.collect(self)

    def _costo_celda(self, celda: list[int]) -> float:
        clave = f"{celda[0]},{celda[1]}"
        return float(self.crowd_costs.get(clave, 0.0))

    def _actualizar_navegacion_filas(self) -> None:
        # 1. Verificar timeout de traslado (5 minutos)
        for v in list(self.agents):
            if v.vivo and v.estado.startswith("Yendo a "):
                v.pasos_en_transito += 1
                if v.pasos_en_transito >= self.arrival_timeout_steps:
                    v.pos = list(v.celda_destino)
                    v.llego_a_destino = True
                    v.iniciar_atencion_en_recurso()
        """Actualiza celdas destino de quienes esperan en fila y aplica 'hold' si hay congestión."""
        filas_config = [
            (self.fila_verificacion, self.mapa_celdas["fila_verificacion"]),
            (self.fila_mampara, self.mapa_celdas["fila_mampara"]),
            (self.fila_casilla, self.mapa_celdas["fila_casilla"]),
        ]

        for cola, puntos_fila in filas_config:
            for idx, votante in enumerate(cola):
                punto = puntos_fila[min(idx, len(puntos_fila) - 1)]
                votante.mover_a(punto)

        for v in self.agents:
            if not v.vivo:
                continue
            if not self.puerta_abierta and v.estado == "En camino":
                v.detener()
                continue
            if v.orden == "move" and self._costo_celda(v.celda_destino) >= self.umbral_congestion:
                v.detener()



    # --- Asignación de recursos ---

    def _elegir_recurso_menos_congestionado(self, disponibles: list[int], celdas_recurso: list[list[int]]) -> int:
        return min(disponibles, key=lambda idx: self._costo_celda(celdas_recurso[idx]))
    
    def asignar_verificadores(self) -> None:
        libres = [i for i, disp in enumerate(self.verificadores) if disp]
        while libres and self.fila_verificacion:
            idx = self._elegir_recurso_menos_congestionado(libres, self.mapa_celdas["verificadores"])
            libres.remove(idx)

            votante = self.fila_verificacion.popleft()
            self.verificadores[idx] = False
            votante.recurso_asignado = idx
            votante.duracion_pendiente = self.random.randint(2, 7)
            votante.estado = "Yendo a verificación"
            votante.mover_a(self.mapa_celdas["verificadores"][idx])

            if votante.llego_a_destino:
                votante.iniciar_atencion_en_recurso()

    #  Asignación de mamparas
    def asignar_mamparas(self) -> None:
        libres = [i for i, disp in enumerate(self.mamparas) if disp]
        while libres and self.fila_mampara:
            idx = self._elegir_recurso_menos_congestionado(libres, self.mapa_celdas["mamparas"])
            libres.remove(idx)

            votante = self.fila_mampara.popleft()
            self.mamparas[idx] = False
            votante.recurso_asignado = idx
            votante.duracion_pendiente = self.random.randint(3, 9)
            votante.estado = "Yendo a mampara"
            votante.mover_a(self.mapa_celdas["mamparas"][idx])

            if votante.llego_a_destino:
                votante.iniciar_atencion_en_recurso()

    # asignación de casillas, similar a la asignación de verificadores y mamparas
    def asignar_casillas(self) -> None:
        libres = [i for i, urna in enumerate(self.casillas) if urna.disponible]
        while libres and self.fila_casilla:
            idx = self._elegir_recurso_menos_congestionado(libres, self.mapa_celdas["casillas"])
            libres.remove(idx)

            votante = self.fila_casilla.popleft()
            self.casillas[idx].disponible = False
            votante.recurso_asignado = idx
            votante.duracion_pendiente = self.random.randint(1, 3)
            votante.estado = "Yendo a casilla"
            votante.mover_a(self.mapa_celdas["casillas"][idx])

            if votante.llego_a_destino:
                votante.iniciar_atencion_en_recurso()

    # --- Evento externo: Terremoto ---

    def evento_terremoto(self) -> None:
        print(f"{self.time:5.1f} | ALERTA: TERREMOTO")
        print("        La casilla se evacúa y la votación se detiene.")

        # Evacuar a quienes están dentro de la casilla usando AgentSet.select()
        # select() devuelve un nuevo AgentSet con los agentes que cumplen la condición, en este caso, los votantes que no están "En camino", "Finalizado" o "Abandonó"
        en_sitio = self.agents.select(
            lambda v: v.vivo and v.estado not in ["En camino", "Finalizado", "Abandonó"]
        )
        # Evacuar a los votantes en el sitio, cambiando su estado a "Evacuado", registrando la hora de salida y liberando cualquier recurso asignado
        for v in en_sitio:
            estado_anterior = v.estado
            v.estado = "Evacuado"
            v.salida = self.time
            v.recurso_asignado = None
            print(f"        Votante {v.unique_id:02d} evacuado (Estaba: {estado_anterior})")
            v.mover_a(self.mapa_celdas["salida"])  # Ordena al votante moverse a la salida

        # Cancelar todos los eventos futuros (incluyendo llegadas de quienes venían en camino)
        for v in self.agents:
            if v.evento_pendiente is not None:
                v.evento_pendiente.cancel()
                v.evento_pendiente = None
            if v.estado == "En camino":
                v.vivo = False
                self.removed_ids.append(str(v.unique_id))

        # Limpiar filas y liberar recursos
        self.fila_verificacion.clear()
        self.fila_mampara.clear()
        self.fila_casilla.clear()
        self.verificadores = [True] * len(self.verificadores)
        self.mamparas = [True] * len(self.mamparas)
        for c in self.casillas:
            c.disponible = True

        # Registrar el evento de terremoto en el historial para Unity
        self.registrar_evento(
            tipo="external_event",
            votante=None,
            subtipo="earthquake",
            mensaje="ALERTA: TERREMOTO - Evacuación total de la casilla",
        )
        for v in en_sitio:
            self.registrar_evento(
                tipo="evacuated",
                votante=v,
                mensaje=f"Votante {v.unique_id:02d} evacuado",
            )

    # --- Telemetría y puente hacia Unity ---

    def registrar_evento( # Registra un evento en el historial para Unity y en el DataCollector de Mesa
            # el datacollector de mesa es para poder graficar y analizar los datos en Python,
            # mientras que el historial para Unity es para enviar los datos a Unity y poder visualizarlos en tiempo real
        self,
        tipo: str,
        votante: Votante | None,
        mensaje: str,
        station_id: str | None = None,
        subtipo: str | None = None,
    ) -> None:
        print(f"[Min {self.time:4.0f}] {mensaje}")
        payload = {
            "tiempo": self.time,
            "tipo": tipo,
            "agent_id": votante.unique_id if votante else None,
            "station_id": station_id,
            "mensaje": mensaje,
        }
        if subtipo:
            payload["subtype"] = subtipo
        self.eventos_minuto.append(payload)
        self.historial_unity.append(payload)

    def obtener_tally(self) -> dict:
        by_candidate = {c: 0 for c in self.candidatos}
        for urna in self.casillas:
            for candidato, cantidad in urna.votos.items():
                by_candidate[candidato] += cantidad

        finalizados = len(self.agents.select(lambda v: v.estado == "Finalizado"))
        total_validos = sum(by_candidate.values())
        null_votes = max(0, finalizados - total_validos)

        return {
            "closed": not self.puerta_abierta,
            "deposited": finalizados,
            "valid": total_validos,
            "null_votes": null_votes,
            "by_candidate": by_candidate,
        }

    def obtener_estadisticas(self) -> dict:
        grupos = dict(self.agents.groupby("estado"))
        finalizados = grupos.get("Finalizado", [])
        abandonaron = grupos.get("Abandonó", [])
        evacuados = grupos.get("Evacuado", [])
        en_camino = grupos.get("En camino", [])

        tiempo_total = sum(v.salida - v.llegada for v in finalizados)
        promedio = round(tiempo_total / len(finalizados), 2) if finalizados else 0.0

        return {
            "total_votantes": self.num_votantes,
            "finalizados": len(finalizados),
            "abandonaron": len(abandonaron),
            "evacuados": len(evacuados),
            "en_camino": len(en_camino),
            "tiempo_promedio_min": promedio,
        }

    def generar_respuesta_sync(self) -> dict:
        """Genera el payload exacto que devuelve POST /sync a Unity."""
        agentes_vivos = []
        for v in self.agents:
            if not v.vivo:
                continue
            agentes_vivos.append({
                "id": str(v.unique_id),
                "state": ESTADOS_UNITY.get(v.estado, "en_route"),
                "command": v.orden,
                "target_x": v.celda_destino[0],
                "target_y": v.celda_destino[1],
                "path": [v.pos, v.celda_destino] if v.orden == "move" else [],
                "age": v.edad,
                "priority": v.prioridad,
            })

        respuesta = {
            "step": self.current_step,
            "simulated_time": self.time,
            "agents": agentes_vivos,
            "removed": list(self.removed_ids),
            "events": list(self.eventos_minuto),
            "tally": self.obtener_tally(),
            "stats": self.obtener_estadisticas(),
        }
        self.ultima_respuesta_sync = respuesta
        return respuesta

    def imprimir_resumen(self) -> None: # Imprime un resumen de la simulación, incluyendo estadísticas de votantes, resultados y conteo de votos por casilla
        grupos = dict(self.agents.groupby("estado")) # Agrupa los agentes por su estado actual, 
        # lo que crea un diccionario donde la clave es el estado y el valor es una lista de agentes en ese estado

        finalizados = grupos.get("Finalizado", []) # Obtiene la lista de votantes que finalizaron, si no hay ninguno, devuelve una lista vacía
        abandonaron = grupos.get("Abandonó", [])
        evacuados = grupos.get("Evacuado", [])
        no_llegaron = grupos.get("En camino", [])

        print("\nESTADÍSTICAS DE VOTANTES") 
        print(f"Total de votantes: {self.num_votantes}") 
        print(f"Votantes que finalizaron: {len(finalizados)}")
        print(f"Votantes que abandonaron: {len(abandonaron)}")
        print(f"Votantes evacuados: {len(evacuados)}")
        print(f"Votantes que no llegaron: {len(no_llegaron)}")

        tiempo_total = sum(v.salida - v.llegada for v in finalizados) # Calcula el tiempo total que tardaron los votantes en finalizar, 
        # sumando la diferencia entre la hora de salida y la hora de llegada para cada votante que finalizó

        promedio = (tiempo_total / len(finalizados)) if finalizados else 0.0 # Calcula el tiempo promedio que tardaron los votantes en finalizar, 
        # dividiendo el tiempo total entre el número de votantes que finalizaron

        print("\nRESULTADOS")
        print(f"Votantes Atendidos: {len(finalizados)}")
        print(f"Tiempo Promedio: {promedio:.2f} minutos")

        print("\nCONTEO DE VOTOS POR CASILLA")
        conteo_total = {c: 0 for c in self.candidatos} # Inicializa un diccionario para llevar el conteo total de votos por candidato, con cada candidato como clave y 0 como valor inicial
        
        # Imprime el conteo de votos por casilla y actualiza el conteo total
        for urna in self.casillas: 
            print(f"Casilla {urna.id}:")
            for candidato, cantidad in urna.votos.items():
                print(f"  {candidato}: {cantidad} votos")
                conteo_total[candidato] += cantidad

        # Calcula el total de votos válidos y nulos
        total_validos = sum(conteo_total.values())
        votos_nulos = len(finalizados) - total_validos

        # Imprime el resultado general, incluyendo el porcentaje de votos por candidato y el total de votos válidos y nulos
        print("\nRESULTADO GENERAL")
        for candidato, cantidad in conteo_total.items():
            porcentaje = (cantidad / total_validos * 100) if total_validos > 0 else 0.0
            print(f"  {candidato}: {cantidad} votos ({porcentaje:.1f}%)")
        print(f"\nTotal de votos válidos: {total_validos}")
        print(f"Total de votos nulos: {votos_nulos}")
        print(f"Total de votos depositados: {total_validos + votos_nulos} de {self.num_votantes} votantes")


if __name__ == "__main__":
    # Configuración del modelo y ejecución de la simulación
    modelo = ProcesoElectoralModel(num_votantes=5, rng=None) # rng funciona como la semilla si es 42, queda fija la simulación, si es None, es aleatoria; Ayuda para unity el tenerlo
    modelo.run_until(120)  # Avanza el reloj DEVS ejecutando los eventos programados
    modelo.imprimir_resumen()

    # Ejemplo de salida JSON lista para consumirse desde Unity
    print("\nMUESTRA DE TELEMETRÍA JSON PARA UNITY:")
    print(json.dumps(modelo.historial_unity[:3], indent=2, ensure_ascii=False))