from collections import deque
import json
import mesa
from mesa.time import Priority


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
            self.model.registrar_evento(
                tipo="Abandono",
                votante=self,
                mensaje=f"Votante {self.unique_id:02d} decide abandonar la casilla",
            )
            return

        self.estado = "Esperando verificación"
        self.model.registrar_evento(
            tipo="LlegadaFila",
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
        urna = self.model.casillas[idx]
        urna.registrar_voto(self.voto)
        urna.disponible = True
        self.recurso_asignado = None

        self.estado = "Finalizado"
        self.salida = self.model.time
        self.model.registrar_evento(
            tipo="Salida",
            votante=self,
            recurso=idx + 1,
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
        rng: int | None = None,
    ):
        super().__init__(rng=rng) # Inicializa el modelo con una semilla aleatoria para reproducibilidad
        self.num_votantes = num_votantes # Número total de votantes que llegarán a la casilla
        self.candidatos = candidatos or ["Candidato A", "Candidato B", "Candidato C"] # Lista de candidatos disponibles para la votación
        self.edad_min = edad_min
        self.edad_max = edad_max
        self.edad_prioridad = edad_prioridad

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
            priority=Priority.HIGH,
        )

    # --- Asignación de recursos ---

    def asignar_verificadores(self) -> None: # Asigna verificadores a los votantes en la fila de verificación, 
        for i in range(len(self.verificadores)):
            if self.verificadores[i] and self.fila_verificacion:# si hay verificadores disponibles y votantes esperando
                votante = self.fila_verificacion.popleft() # Saca al votante de la fila de verificación
                self.verificadores[i] = False # Marcar el verificador como no disponible
                votante.recurso_asignado = i # Asigna el índice del verificador al votante, el indice es el número del verificador que le toca
                votante.estado = "Verificando" # Cambia el estado del votante a "Verificando"

                # Programar evento de finalización de verificación con duración aleatoria entre 2 y 7 minutos
                duracion = self.random.randint(2, 7)
                votante.evento_pendiente = self.schedule_event(
                    votante.finalizar_verificacion,
                    after=duracion,
                )

                # Registrar evento de inicio de verificación en el historial para Unity
                self.registrar_evento(
                    tipo="InicioVerificacion",
                    votante=votante,
                    recurso=i + 1,
                    mensaje=f"Votante {votante.unique_id:02d} inicia verificación {i + 1}",
                )

    #  Asignación de mamparas
    def asignar_mamparas(self) -> None:
        for i in range(len(self.mamparas)): # Itera sobre cada mampara disponible
            if self.mamparas[i] and self.fila_mampara: # Si la mampara está disponible y hay votantes esperando en la fila de mampara
                votante = self.fila_mampara.popleft() # Saca al votante de la fila de mampara
                self.mamparas[i] = False # Marca la mampara como no disponible, cuando lo pasamos a la mampara
                votante.recurso_asignado = i # Asigna el índice de la mampara al votante, el indice es el número de la mampara que le toca
                votante.estado = "En mampara" 
                votante.elegir_candidato()

                # Programar evento de finalización de mampara con duración aleatoria entre 3 y 9 minutos
                duracion = self.random.randint(3, 9)
                votante.evento_pendiente = self.schedule_event(
                    votante.finalizar_mampara,
                    after=duracion,
                )

                # Registrar evento de inicio de mampara en el historial para Unity
                self.registrar_evento(
                    tipo="InicioMampara",
                    votante=votante,
                    recurso=i + 1,
                    mensaje=f"Votante {votante.unique_id:02d} inicia mampara {i + 1}",
                )

    # asignación de casillas, similar a la asignación de verificadores y mamparas
    def asignar_casillas(self) -> None:
        for i, urna in enumerate(self.casillas):
            if urna.disponible and self.fila_casilla:
                votante = self.fila_casilla.popleft()
                urna.disponible = False
                votante.recurso_asignado = i
                votante.estado = "En casilla"

                duracion = self.random.randint(1, 3)
                votante.evento_pendiente = self.schedule_event(
                    votante.finalizar_casilla,
                    after=duracion,
                )
                self.registrar_evento(
                    tipo="InicioCasilla",
                    votante=votante,
                    recurso=i + 1,
                    mensaje=f"Votante {votante.unique_id:02d} deposita voto en casilla {i + 1}",
                )

    # --- Evento externo: Terremoto ---

    def evento_terremoto(self) -> None:
        print(f"{self.time:5.1f} | ALERTA: TERREMOTO")
        print("        La casilla se evacúa y la votación se detiene.")

        # Evacuar a quienes están dentro de la casilla usando AgentSet.select()
        # select() devuelve un nuevo AgentSet con los agentes que cumplen la condición, en este caso, los votantes que no están "En camino", "Finalizado" o "Abandonó"
        en_sitio = self.agents.select(
            lambda v: v.estado not in ["En camino", "Finalizado", "Abandonó"]
        )
        # Evacuar a los votantes en el sitio, cambiando su estado a "Evacuado", registrando la hora de salida y liberando cualquier recurso asignado
        for v in en_sitio:
            estado_anterior = v.estado
            v.estado = "Evacuado"
            v.salida = self.time
            v.recurso_asignado = None
            print(f"        Votante {v.unique_id:02d} evacuado (Estaba: {estado_anterior})")

        # Cancelar todos los eventos futuros (incluyendo llegadas de quienes venían en camino)
        for v in self.agents:
            if v.evento_pendiente is not None:
                v.evento_pendiente.cancel()
                v.evento_pendiente = None

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
            tipo="Terremoto",
            votante=None,
            mensaje="Evacuación total de la casilla por sismo",
        )

    # --- Telemetría y puente hacia Unity ---

    def registrar_evento( # Registra un evento en el historial para Unity y en el DataCollector de Mesa
            # el datacollector de mesa es para poder graficar y analizar los datos en Python,
            # mientras que el historial para Unity es para enviar los datos a Unity y poder visualizarlos en tiempo real
        self,
        tipo: str,
        votante: Votante | None,
        mensaje: str,
        recurso: int | None = None,
    ) -> None:
        print(f"{self.time:5.1f} | {mensaje}")

        payload = { # Diccionario que contiene la información del evento para enviar a Unity
            "tiempo": self.time,
            "tipo_evento": tipo,
            "votante_id": votante.unique_id if votante else None,
            "estado": votante.estado if votante else "Emergencia",
            "recurso": recurso,
            "filas": {
                "verificacion": len(self.fila_verificacion),
                "mampara": len(self.fila_mampara),
                "casilla": len(self.fila_casilla),
            },
        }
        self.historial_unity.append(payload)
        self.datacollector.collect(self)

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