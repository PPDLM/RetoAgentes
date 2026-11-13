""" Este script solo considera cuando llegan los votantes, la etapa de verificación en lista nominal y """
""" pasar a la mampara """

# Los eventos representan las acciones o cambios de estado que ocurren durante la simulación
# del proceso electoral.
# Cada evento está asociado a un tiempo de ejecución, un tipo de evento
#(llegada, verificación, mampara o salida) y un votante.
# Los eventos se administran mediante una cola de prioridad (heapq), que permite procesarlos en orden cronológico.
# Al ejecutarse un evento, se actualiza el estado del votante, se asignan o liberan los recursos correspondientes
#(verificadores o mamparas) y, cuando es necesario, se generan nuevos eventos que se incorporan a la cola de prioridad.

# TODO: Falta conteo de votos, candidatos; en casilla se van incrementando los votos, no es un agente sino un objeto

import random
import heapq
from collections import deque

N = 5
random.seed(10)

# Recursos disponibles
verificadores = [True] * 3
mamparas = [True] * 2
casillas = [True] * 1

# Filas de espera
fila_verificacion = deque()
fila_mampara = deque()
fila_casilla = deque()

# Cola de eventos
eventos = []
contador = 0


class Votante:
    def __init__(self, numero):
        self.id = numero
        self.estado = "En camino"
        self.llegada = 0
        self.salida = 0
        self.edad = random.randint(18, 90)

     #El votante al llegar decide formarse y esperar, ó marcharse
    def decidir_formarse(self, personas_en_fila):
        # Probabilidad de abandonar según la fila
        if personas_en_fila < round(N*.20):
            probabilidad = 0.10
        elif personas_en_fila < round(N*.40):
            probabilidad = 0.40
        else:
            probabilidad = 0.80

        numero = random.random()

        if numero < probabilidad:
            return "Abandonar"
        elif self.edad >= 65:
            votante.estado = "Esperando verificación"
            fila_verificacion.append(votante)
            return "Formarse"
        else:
            return "Formarse"
        

# Método independiente del objeto para insertar eventos en heapq
def nuevo_evento(tiempo, tipo, votante, recurso=-1):
    global contador
    contador += 1
    heapq.heappush(
        eventos,
        (tiempo, contador, tipo, votante, recurso)
    )

# EVENTO 1: LLEGADA
# procesa la llegada de un votante a la casilla electoral, actualiza su estado,
# lo incorpora a la fila de verificación e intenta asignarle un verificador disponible.
def llegada_votante(votante, t):
    votante.llegada = t

    personas_en_fila = len(fila_verificacion)

    decision = votante.decidir_formarse(personas_en_fila)

    if decision == "Abandonar":
        votante.estado = "Abandonó"
        votante.salida = t

        print(f"{t:3} | Votante {votante.id:02d} "
              f"decide abandonar la casilla")

    else:
        votante.estado = "Esperando verificación"
        if (votante.edad >= 65):
            print(f"{t:3} | Votante mayor de edad {votante.id:02d} "
                          f"decide formarse")
            fila_verificacion.appendleft(votante)
        else:
            fila_verificacion.append(votante)

        print(f"{t:3} | Votante {votante.id:02d} "
              f"decide formarse")

        # Asigna al votante un tiempo para verificar y lo asigna al primer verificador libre
        # Ustedes pueden dejar al votante que decida con que verificador va (en caso de haber dos disponibles)
        verificar(t)

# EVENTO 2: VERIFICAR
# asignar los votantes que están esperando en la fila de verificación a cualquiera de los tres verificadores
# disponibles. Cuando un votante comienza a ser atendido, se genera un tiempo aleatorio de atención y
# se programa un nuevo evento en heapq.
def verificar(t):
    for i in range(3):
        # El verificador esta libre y existe al menos un votante esperando
        if verificadores[i] and fila_verificacion:
            votante = fila_verificacion.popleft()
            verificadores[i] = False
            votante.estado = "Verificando"

            duracion = random.randint(2, 7)

            #Cuando se calcula el tiempo aleatorio para la verificacion y el verificador donde se forma el votante
            # t + duracion: tiempo en que termina el evento.
            # "Verificar": tipo de evento.
            # votante: votante que está siendo atendido.
            # i: número del verificador que lo atiende (0, 1 o 2).
            nuevo_evento(
                t + duracion, "Verificar", votante, i
            )

            print(f"{t:3} | Votante {votante.id:02d} "
                  f"inicia verificación {i+1}")


# EVENTO 3: MAMPARA
# asignar los votantes que están esperando en la fila despues de la verificacion a una de las dos mamparas
# disponibles.
# Una vez que el votante comienza a votar, se genera un tiempo aleatorio y se programa un nuevo evento en heapq para indicar cuándo terminará.
def mampara(t):
    for i in range(2):
        if mamparas[i] and fila_mampara:
            votante = fila_mampara.popleft()
            mamparas[i] = False
            votante.estado = "En mampara"

            duracion = random.randint(3, 9)

            # Los eventos 

            nuevo_evento(
                t + duracion, "Mampara", votante, i
            )

            print(f"{t:3} | Votante {votante.id:02d} "
                  f"inicia mampara {i+1}")

# EVENTO 4: Ballot box stage
def casilla(t):
    for i in range(len(casillas)):
        if casillas[i] and fila_casilla: # si la casilla está libre y hay votantes esperando
            votante = fila_casilla.popleft() # extrae el primer votante de la fila
            casillas[i] = False # la casilla se ocupa
            votante.estado = "En casilla" # actualiza el estado del votante

            duracion = random.randint(1, 3) # tiempo aleatorio para depositar el voto
            
            # en el tiempo t + duracion este votante terminará de usar la urna i 
            # (para que en ese momento el ciclo while libere el recurso y envíe al votante a la salida).
            nuevo_evento(t + duracion, "Casilla", votante, i) 

            print(f"{t:3} | Votante {votante.id:02d} deposita voto en casilla {i+1}")

# EVENTO 5: SALIR
def salir(votante, t):
    votante.estado = "Finalizado"
    votante.salida = t

    print(f"{t:3} | Votante {votante.id:02d} "
          f"sale de la casilla")

# EVENTO 6: EVENTO EXTERNO TERREMOTO

def external_event(t):
    print(f"{t:3} | ALERTA: TERREMOTO")
    print(f"      La casilla se evacua y la votacion se detiene.")

    for v in votantes:
        if v.estado not in ["En camino", "Finalizado", "Abandonó"]:
            anterior = v.estado         
            v.estado = "Evacuado"
            v.salida = t
            print(f"      El votante {v.id:02d} evacuado (Estaba: {anterior})")

    fila_verificacion.clear()
    fila_mampara.clear()
    fila_casilla.clear()
    for lista in (verificadores, mamparas, casillas):
        for i in range(len(lista)):
            lista[i] = True

    eventos.clear()
    


# CREAR VOTANTES Y PROGRAMAR LLEGADAS
votantes = [Votante(i + 1) for i in range(N)]

tiempo_llegada = 0

for votante in votantes:
    tiempo_llegada += random.randint(1, 4)
    nuevo_evento(tiempo_llegada, "Llegada", votante)

tiempo_terremoto = random.randint(10, 25)
nuevo_evento(tiempo_terremoto, "Terremoto", None)

# SIMULACIÓN
# Durante el proceso electoral, cada votante genera diferentes
# eventos dependiendo de la etapa en la que se encuentra.
# Un votante puede tener como máximo un evento pendiente en heapq.
# Cuando termina un evento, puede generarse el siguiente,
# dependiendo de la disponibilidad de los recursos.

while eventos:

    # EN SU RETO, CADA EVENTO Y CAMBIO RELEVANTE DE ESTADO
    # SE DEBE COMUNICAR A UNITY PARA SU VISUALIZACIÓN.
    t, _, tipo, votante, recurso = heapq.heappop(eventos)

    # LLEGADA:
    # El votante llega a la casilla y entra a la fila de verificación.
    # Si hay un verificador disponible, comienza su atención.
    # Se genera un tiempo aleatorio y se programa en heapq
    # el evento de finalización de la verificación.
    if tipo == "Terremoto":
        external_event(t)

    elif tipo == "Llegada":
        llegada_votante(votante, t)

    # VERIFICAR:
    # El votante termina la verificación de la lista nominal.
    # Se libera al verificador y el votante pasa a la fila de mamparas.
    # Se intenta atender al siguiente votante de la fila de
    # verificación y asignar una mampara disponible.
    # Si obtiene una mampara, se genera un tiempo aleatorio
    # y se programa en heapq la finalización de la votación.
    elif tipo == "Verificar":
        verificadores[recurso] = True

        votante.estado = "Esperando mampara"
        fila_mampara.append(votante)

        verificar(t)
        mampara(t)

    # MAMPARA:
    # El votante termina de votar en la mampara.
    # Se libera la mampara y el votante sale de la casilla.
    # Se intenta asignar la mampara liberada al siguiente
    # votante que esté esperando.
    elif tipo == "Mampara":
        mamparas[recurso] = True

        mampara(t)
        fila_casilla.append(votante)
        casilla(t)

    #CASILLA:
    # El votante termina de depositar su voto en la casilla.
    # Se libera la casilla y el votante sale de la casilla.
    elif tipo == "Casilla":
        casillas[recurso] = True
        # Una vez depositado el voto, el votante sale de la casilla
        salir(votante, t)
        casilla(t)




# RESULTADOS
print("\nRESULTADOS")

for votante in votantes:
    permanencia = votante.salida - votante.llegada

    print(f"Votante {votante.id:02d}: "
          f"{permanencia} minutos")

promedio = sum(
    v.salida - v.llegada for v in votantes
) / N

print(f"\nTiempo promedio: {promedio:.2f} minutos")
