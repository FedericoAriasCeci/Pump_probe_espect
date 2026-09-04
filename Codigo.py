# PAQUETES IMPORTADOS Y USADOS EN EL CÓDIGO: 
# Pyserial es para la comunicación serial con el SMC y el SMS
# Pyvisa es para la comunicación GPIB con el lock in.
# Time es para dormir la ejecución del código durante un cierto tiempo
# Csv es para grabar los .csv
# Tkinter es para la interfaz gráfica de ventanas
# Canvas y BOTH son para dibujar los recuadros de los paneles de la pantalla principal
# Numpy es el paquete matemático y de vectores
# Matplotlib para los gráficos
# FigureCanvasTkAgg para actualizar los gráficos en la interfaz gráfica
# Threading para crear líneas de código que se ejecuten paralelamente a la línea principal. Solo se usa en el 
# panel de medición manual (el de la derecha de la interfaz gráfica)
# Datetime para importar la hora y día actuales
# Decimal es para manejar más cómodamente los float que tiran errores difíciles de manejar al hacer operaciones

import serial
import serial.tools.list_ports
import pyvisa
import time
import csv
import tkinter as tk
import tkinter.font as font
from tkinter import Canvas, BOTH
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.ticker import FormatStrFormatter
from mpl_toolkits.axes_grid1 import make_axes_locatable
import threading as th
from datetime import date
import datetime
from decimal import Decimal
import os # os_exit(00) restartea el núcleo.

from acquisition_utils import AcquisitionDataManager, add_suffix_to_filename

CARPETA_CODIGO = os.path.dirname(os.path.abspath(__file__))


def RutaEnCarpetaDelCodigo(nombre):
    return os.path.join(CARPETA_CODIGO, nombre)


def TextoPuertosSerieDisponibles():
    try:
        puertos = list(serial.tools.list_ports.comports())
    except Exception as error:
        return "No se pudieron listar los puertos COM.\n" + str(error)
    if len(puertos) == 0:
        return "No hay puertos COM visibles para Python/Windows."
    lineas = ["Puertos COM detectados:"]
    for puerto in puertos:
        lineas.append(str(puerto.device) + " - " + str(puerto.description))
    return "\n".join(lineas)


# VARIABLES GLOBALES
global do_run # Es una variable usada para cancelar las mediciones. Podría cambiarse para que no sea global
do_run = True # pasándola a través del código.
global t
global tiempoAgregadoMonocromador # Tiempo de espera por paso agregado para el monocromador.
tiempoAgregadoMonocromador = 1 # (segundos)
global tiempoAgregadoPlataforma # Tiempo de espera por paso agregado para la plataforma.
tiempoAgregadoPlataforma = 1 # (segundos)
global numeroDeAuxsPorSegundo # Es el número de veces por segundo que se mide el AUX para promediarlo.
numeroDeAuxsPorSegundo = 20 # Se puede agrandar hasta que el LockIn responda bien.
global posicionExtremaSMC
posicionExtremaSMC = 25 # Es una variable global que es 0 o 25 dependiendo si se quiere que un extremo del 
                        # recorrido sea la posición cero, o si se quiere que el otro extremo del recorrido
                        # sea la posición cero. Es para invertir el recorrido de la plataforma.
global velocidadSMC_mmPorSegundo # Es la que tiene seteada el SMC. Se puede leer y modificar. Falta probar el código.
velocidadSMC_mmPorSegundo = 0.16
global velocidadSMS_nmPorSegundo # Calculada a mano con un cronómetro. Se podría leer y modificar. Falta probar el 
velocidadSMS_nmPorSegundo = 9    # código. La variable que se puede modificar es un valor inverso de la velocidad.
global resolucionSMC
resolucionSMC_mm = 0.0001 # En mm. Es decir, una resolución de 0.1 micrómetro. Esta resolución es inmodificable.
global resolucionSMS
resolucionSMS_nm = 0.3125 # en nm. Es para la red de 1200. OBS: De acuerdo al manual la resolución debería ser de
global offsetSMS          # 0.03125 (la inversa de 32, que es el multiplicador). Sin embargo, en la hoja de internet
                          # del fabricante dice que la resolución es de 0.3125. Creo que el motor no funciona dando
                          # los pasos mínimos. Quizás sí, y la resolución es de 0.03125. Se puede probar..
offsetSMS = -87.0 # Es el 9913 que muestra el visor al calibrar el monocromador
global fuente
fuente = "Helvetica"
        
# OBS: En el código se usa SMC y plataforma para referirse a lo mismo. Lo mismo pasa con el SMS y el monocromador.

#%%%%%%

# El SMC100PP es el controlador de la plataforma de retardo (la plataforma la mueve un tornillo micrométrico llamado
# TRAPPD25). El controlador está conectado a la PC por un USB que simula un puerto
# serie RS-232. Hay un driver (que se instala automáticamente) que hace que se vea directamente el puerto serie
# sin ver el USB. En la clase de aquí abajo se abre este puerto serie (no se maneja el USB, digamos).

class SMC():

    def __init__(self):
        self.address = serial.Serial( #Crea el puerto pero no lo abre. En el manual están estos valores.
                port = None,
                baudrate = 57600,
                bytesize = 8,
                stopbits = 1,
                parity = 'N',
                timeout = 1,
                xonxoff = True,
                rtscts = False,
                dsrdtr = False)
        self.resolucion = resolucionSMC_mm # Se le asigna la variable global.
        self.posicion = posicionExtremaSMC # Esto es 0 o 25 dependiendo si se quiere barrer en un sentido o 
                                        # en el otro. Al configurar se lee la posición.
        self.velocidadMmPorSegundo = velocidadSMC_mmPorSegundo # Es la variable global. Se puede descomentar y probar
                                                               # el código para leer y modificar la velocidad.

    def AsignarPuerto(self, puerto): # Asigna y abre el puerto
        self.address.port = puerto 
        self.puerto = puerto
        self.address.open() 

    def CerrarPuerto(self):
        self.address.close()

    def Configurar(self):    
#        self.velocidadMmPorSegundo = self.LeerVelocidad()
        valor = -1
        estadosReady = ['32','33','34']
        while valor == -1:
            self.address.write(b'1TS\r\n') # Le pregunta el estado al controlador.
            time.sleep(0.1)
            lectura = self.LeerBuffer()
            if 'TS' in lectura:
                valor = 1
                if any(x in lectura for x in estadosReady): # Si ya estaba prendido le lee la posición y lo deja ahí.
                    self.posicion = posicionExtremaSMC-self.LeerPosicion()
                    return
        self.address.write(b'1RS\r\n') # Si no estaba prendido lo resetea y lo calibra: lo manda a la posición inicial.
        time.sleep(7)
        self.address.write(b'1PW1\r\n')
        time.sleep(2)
        self.address.write(b'1HT0\r\n')
        time.sleep(2)
        self.address.write(b'1PW0\r\n')
        time.sleep(2)
        self.address.write(b'1OR\r\n')
        time.sleep(2)
        valor = -1
        while valor == -1: # Esto es un loop para que el programa no siga corriendo hasta que la calibración no termine.
            self.address.write(b'1TS\r\n') 
            time.sleep(0.1)
            lectura = self.LeerBuffer()
            if 'TS' in lectura:
                valor = lectura.find('32')
        self.posicion = posicionExtremaSMC # Podría leerle la posición, pero siempre queda en el cero luego de la calibración.

    def LeerVelocidad(self): # Devuelve una velocidad en mm por segundo.
        velocidad = 0
        valor = -1
        while valor == -1:
            self.address.write(b'1VA?\r\n')
            time.sleep(0.1)
            lectura = self.LeerBuffer()
            if 'VA?' in lectura:
                a = lectura.split('?')[1]
                a = a.split('\r')[0]
                velocidad = float(a)
        return velocidad

    def CambiarVelocidad(self, velocidad): # En mm por segundo también.
        comando = '1VA?' + str(velocidad) + '\r\n'
        self.address.write(comando.encode())
        time.sleep(0.1)
        self.velocidadMmPorSegundo = float(velocidad)

    def LeerPosicion(self): # Devuelve la posición en mm.
        valor = -1
        while valor == -1:
            self.address.write(b'1TH\r\n') # Le pregunta la posición absoluta (teórica, del controlador)
            time.sleep(0.1)
            lectura = self.LeerBuffer()
            if 'TH' in lectura:
                a = lectura.split('\r')[0]
                b = a.split('TH')[len(a.split('TH'))-1]
                return abs(round(float(b),5))

    def Mover(self, PosicionSMC_mm): # Mueve a la posición especificada. OBS IMPORTANTE: Si se quiere dar vuelta 
        # la dirección de barrido de la plataforma, se debe cambiar la PosiciónSMC_mm por 25-PosicionSMC_mm, 
        # SOLAMENTE en la línea del .write.
        # Es como cambiar el punto cero de la plataforma de 0 a 25. Entonces si se ingresa la posición 1mm en el 
        # programa, voy a tener una posición de 24mm en la paltaforma. Si se hace un barrido desde 1mm a 5mm voy 
        # a barrer desde 24mm hasta 20mm. Toda la graficación y grabado de CSV's queda IGUAL. Hay que ver que esa 
        # resta 25-PosicionSMC_mm no induzca errores de redondeo.
        comando = '1PA' + str(posicionExtremaSMC-PosicionSMC_mm) + '\r\n'
        self.address.write(comando.encode())
        PosicionSMC_mm = round(PosicionSMC_mm, 6)
        self.posicion = PosicionSMC_mm

    def CalcularTiempoSleep(self, PosicionSMC_mm): # El código deja de ejecutarse hasta que el SMC se mueva.
                                                   # Hay un tiempo agregado que podría reducirse/quitarse.
        TiempoSMC = 0
        if (PosicionSMC_mm-self.posicion) == 0:
            time.sleep(0.1)
        else:
            TiempoSMC = abs(PosicionSMC_mm-self.posicion)/self.velocidadMmPorSegundo + tiempoAgregadoPlataforma
        return TiempoSMC

    def LeerBuffer(self): # Lee el puerto serie.
        lectura = 'a'
        lecturaTotal = ''
        while lectura != '\n' and lectura != '': 
            time.sleep(0.1)
            lectura = self.address.read()
            print(lectura)
            lectura = lectura.decode('windows-1252')
            lecturaTotal = lecturaTotal + lectura
        return lecturaTotal      

    def Identificar(self): # Se fija de que reconozca el controlador (el tornillo de la plataforma, en particular).
        b = False
        i=0
        while i < 4:
            self.address.write(b'1ID?\r\n')
            time.sleep(0.1)
            lectura = self.LeerBuffer()
            if 'ID' in lectura:
                if 'TRA25PPD' in lectura:
                    b = True
                    break
            i += 1
        return b

    def Calibrar(self): # Lo resetea y lo manda a la posición cero.
        self.address.write(b'1RS\r\n')
        time.sleep(7)
        self.address.write(b'1PW1\r\n')
        time.sleep(2)
        self.address.write(b'1HT0\r\n')
        time.sleep(2)
        self.address.write(b'1PW0\r\n')
        time.sleep(2)
        self.address.write(b'1OR\r\n')
        time.sleep(2)
        self.posicion = posicionExtremaSMC
        return
    
#%%%
        
# El SMS LambdaScan es el controlador del Monocromador (o espectrómetro). Está conectado a la PC via un cable USB
# que simula un puerto serie RS-232. Al controlador le falta un circuito integrado que se quemó (el del motor 1).
# Hablar con Maxi si ocurre alguna falla eléctrica, pero viene funcionando joya.
# Hay dos redes de difracción, una de 1200 ranuras por mm y otra creemos de 600 ranuras por mm. La calibración fue 
# hecha a "mano", sin una alineación muy fina, así que puede estar pifiada hasta por 5 nm masomenos.     

class SMS():

    def __init__(self):
        self.address = serial.Serial( # Crea el puerto, no lo abre. Los valores están en el manual.
                port = None,
                baudrate = 9600,
                bytesize = 8,
                stopbits = 1,
                parity = 'N',
                timeout = 3,
                xonxoff = False,
                rtscts = False,
                dsrdtr = True)
        self.multiplicador = int(1/resolucionSMS_nm*10) # El multiplicador es la inversa de la resolución.
                                                        # Como la resolución real es 0.03125 entonces el multiplicador
                                                        # debe ser 32. Pero como la resolución que funciona es
                                                        # 0.3125, se multiplica por 10 para obtener el valor correcto.
        self.resolucion = resolucionSMS_nm # La resolución es la inversa del multiplicador.
        self.posicion = 0
        self.velocidadNmPorSegundo = velocidadSMS_nmPorSegundo

    def AsignarPuerto(self, puerto): # Asigna y abre el puerto.
        self.address.port = puerto
        self.puerto = puerto     
        self.address.open()

    def CerrarPuerto(self): 
        self.address.close()

    def Configurar(self): 
        comando = '#SLM\r3\r' # Setea el control de mano del SMS para que muestre el motor 3.
        self.address.write(comando.encode())
        time.sleep(1)
        self.posicion = self.LeerPosicion()
#        self.velocidadNmPorSegundo = self.LeerVelocidad()
#        self.multiplicador = self.LeerMultiplicador()
        if self.posicion < 400: # Mueve automáticamente a 400nm al monocromador si está por debajo. Quitar si no se quiere.
            self.Mover(400)   

    def LeerVelocidad(self): # La velocidad que devuelve no es una velocidad realmente, es un número entero positivo
                             # que define la cantidad de "time counts" que el motor espera entre step y step.
                             # Es decir, a mayor número, menor velocidad.
        valor = -1
        while valor == -1:
            self.address.write(b'#RD?\r3\r')
            time.sleep(1)
            lectura = self.LeerBuffer()
            valor = lectura.find('RD?')        
        a = lectura.split('\r')[0]
        a = a.split(' ')[len(a.split(' '))-1]
        a = a.split('!!')[0]
        velocidad = float(a)
        return velocidad        

    def CambiarVelocidad(self, velocidad): # Idem LeerVelocidad().
        comando = '#SMO\r3\r' + str(velocidad) + '\r'
        self.address.write(comando.encode())
        time.sleep(1)
        self.velocidadNmPorSegundo = float(velocidad)

    def LeerPosicion(self): # Tanto el LeerPosicion y Mover están en nm y el controlador se encarga de ver qué 
                            # multiplicador está asignado y hacer los cálculos para mover la red de difracción.
        valor = -1
        while valor == -1:
            self.address.write(b'#CL?\r3\r')
            time.sleep(1)
            lectura = self.LeerBuffer()
            valor = lectura.find('CL?')        
        a = lectura.split('\r')[0]
        b = a.split(' ')[len(a.split(' '))-1]
        c = b.split('!!')[0]
        posicionEnNm = float(c)
        return round(posicionEnNm,4)

    def Mover(self, LongitudDeOnda_nm): 
        comando = '#MCL\r3\r' + str(LongitudDeOnda_nm) + '\r'
        self.address.write(comando.encode())
        self.posicion = LongitudDeOnda_nm

    def CalcularTiempoSleep(self, LongitudDeOnda_nm): # Hay un tiempo agregado que se puede reducir/quitar, con cuidado.
        TiempoMonocromador = 0
        if (LongitudDeOnda_nm-self.posicion) == 0:
            time.sleep(1)
        else:
            TiempoMonocromador = abs(LongitudDeOnda_nm-self.posicion)/(self.velocidadNmPorSegundo) + tiempoAgregadoMonocromador
        return TiempoMonocromador

    def LeerBuffer(self):
        lectura = 'a'
        lecturaTotal = ''
        while lectura != '\n' and lectura != '':
            lectura = self.address.read()
            print(lectura)
            lectura = lectura.decode('windows-1252')
            lecturaTotal = lecturaTotal + lectura
            time.sleep(0.1)
        return lecturaTotal

    def Identificar(self):
        b = False
        i = 0
        while i < 4:
            self.address.write(b'#VR?\r')
            time.sleep(0.5)
            self.address.flush()
            lectura = self.LeerBuffer()
            if 'VR' in lectura:
                if 'Version 3.03' in lectura:
                    b =True
                    break
            i += 1
        return b

    def Calibrar(self): # Lo manda a la posición de calibración, es la que tiene cuando se enciende y se toca ENT.
        self.address.write(b'#CAL\r3\r')
        self.posicion = offsetSMS
        return

    def CambiarRed(self, grating): # Hay que probar el código.
        if grating == '1200' and self.multiplicador == 32:
            return
        if grating == '600' and self.multiplicador == 16:
            return
        if grating == '600':
            self.address.write(b'#SCF\r3\r16\r')
            self.resolucion = 0.625
            self.multiplicador = 16
        if grating == '1200':
            self.address.write(b'#SCF\r3\r32\r')
            self.resolucion = 0.3125
            self.multiplicador = 32
        self.Calibrar()

    def LeerMultiplicador(self): # Hay que probar el código.
        valor = -1
        while valor == -1:
            self.address.write(b'#RC?\r3\r')
            time.sleep(1)
            lectura = self.LeerBuffer()
            valor = lectura.find('RC?')        
        a = lectura.split('\r')[0]
        a = a.split(' ')[len(a.split(' '))-1]
        a = a.split('!!')[0]
        multiplicador = float(a)
        return multiplicador
        
#%%%
    
# El LockIn está conectado a la PC via un cable USB que simula un GPIB.
    
class LockIn():

    def __init__(self):
        self.TiempoDeIntegracionTotal = 0

    def AsignarPuerto(self, puerto): # Crea, asigna y abre el puerto
        rm = pyvisa.ResourceManager()
        comando = 'GPIB0::' + puerto + '::INSTR'
        self.address = rm.open_resource(comando)
        self.puerto = puerto

    def Configurar(self):
        self.address.write("OUTX1") #Setea en GPIB=1 o RSR232=0
        time.sleep(0.2)
        self.address.write("FMOD0") #Setea el Lock In con fuente externa de modulacion---> interna=1
        time.sleep(0.2)
        self.address.write("RSLP1") #Setea Slope TTL up ---> Sin=0, TTLdown=2
        time.sleep(0.2)
        self.address.write("ISRC0") #Setea la input configuration---->0=A, 1=a-b, 2,3=I en distintas escalas
        time.sleep(0.2)
        self.address.write("IGND1") #Setea ground=1 o float=0
        time.sleep(0.2)
        self.address.write("ICPL0") #Setea Coupling en AC=0 o DC=1
        time.sleep(0.2)
        self.address.write("ILIN3") #Todos los filtros activados
        time.sleep(0.2)
        self.address.write("RMOD0") #Reserva dinamica 0=HR, 1=Normal, 2=LN
        time.sleep(0.2)
        self.address.write("OFSL3") #Setea Low Pass Filter Slope en 0=6, 1=12, 2=18 y 3=24 DB/octava
        time.sleep(0.2)
        self.address.write("SYNC0") #Synchronous Filter off=0 or on below 200hz=1
        time.sleep(0.2)
        self.address.write("OVRM1") #Setea Remote Control Override en on=1, off=0
        time.sleep(0.2)
        self.address.write("LOCL0") #Setea control en Local=0, Remote=1, Remote Lockout=2
        time.sleep(0.2)
        self.SetearNumeroDeConstantesDeIntegracion(1)

    def ConstanteDeIntegracion(self): # Le pregunta la constante de integración al Lock In.
        constanteDeIntegracion = 0
        a = self.address.query("OFLT?")
        a = a.replace('\n','')
        a = int(a)
        if (a % 2) == 0:
            constanteDeIntegracion = 10*(10**(-6))*(10**(a/2))
        else:
            constanteDeIntegracion = 30*(10**(-6))*(10**((a-1)/2))
        return constanteDeIntegracion

    def SetearNumeroDeConstantesDeIntegracion(self, numeroDeConstantesDeTiempo): # El número de constantes de tiempo
        # es un número por el que se multiplica la constate de tiempo del lock in para tener mayor libertad.
        self.numeroDeConstantesDeTiempo = numeroDeConstantesDeTiempo
        self.TiempoDeIntegracionTotal = self.CalcularTiempoDeIntegracion()

    def CalcularTiempoDeIntegracion(self): 
        constanteDeIntegracion = self.ConstanteDeIntegracion()
        TiempoDeIntegracionTotal = constanteDeIntegracion*self.numeroDeConstantesDeTiempo
        return TiempoDeIntegracionTotal

    def Identificar(self):
        b = False
        lectura = self.address.query("*IDN?")
        if 'SR830' in lectura:
            b = True
        return b

    def Adquirir(self): # Devuelve un string separado en comas con las cantidades.
        a = self.address.query("SNAP?1,2{,3,4,5,9}") # X,Y,R,THETA,AUX1,FREC
        a = a.replace('\n','')
        return a


#%%%

# Esta clase hace las iteraciones para los barridos: manda las órdenes para mover la plataforma, la red y adquiere
# del LockIn. También desarma el string del Lock In para devolver un vector de strings.
# Posee adentro una instancia de la clase SMC, una de SMS, una de LockIn y una de Grafico. Es el corazón de la medi-
# ción. Se encarga de llamar a la clase Grafico e ir armando los gráficos, como también ir grabando el CSV.

class Experimento(): 

    def __init__(self):
        self.smc = SMC()
        self.mono = SMS()
        self.lockin = LockIn()
        self.data_manager = AcquisitionDataManager(RutaEnCarpetaDelCodigo("CSVs"))

    def MedicionALambdaFija(self,
                            nombreArchivo,
                            VectorPosicionInicialSMC_mm,
                            VectorPosicionFinalSMC_mm,
                            VectorPasoSMC_mm):
        self.nombreArchivo = nombreArchivo
        global do_run # Esta variable global se vuelve False cuando se clickea el botón Cancelar Medición. Hasta 
                      # donde logro ver no genera ningún problema cancelar la medición de esta forma. Todos los 
                      # aparatos y objetos quedan con las variables en los estados que deben poseer. Esto es así
                      # porque las posiciones se modifican solamente cuando se mueven los aparatos, o en las cali-
                      # braciones. (En general intenté que todas las variables de los objetos se cambien cuando
                      # tienen que cambiar y no en otro momento. Eso reduce los posibles errores.)
        for i in range(0,len(VectorPosicionInicialSMC_mm)): # Este loop es sobre la cantidad de "Secciones": 1 a 5.
            if do_run == False:
                return
            tiempoDeSleep = self.smc.CalcularTiempoSleep(VectorPosicionInicialSMC_mm[i])
            self.smc.Mover(VectorPosicionInicialSMC_mm[i])
            time.sleep(tiempoDeSleep)
            if i==0: # Esto lo hace siempre. Es medir la primera posición de todo el barrido.
                self.AdquirirGraficarYGrabarCSV()
            if i>0 and VectorPosicionInicialSMC_mm[i] != VectorPosicionFinalSMC_mm[i-1]: # Esto es para evitar que
                # se mida dos veces si uno superpone los extremos de las secciones.
                self.AdquirirGraficarYGrabarCSV()
            numeroDePasos = abs(int(round((VectorPosicionFinalSMC_mm[i]-VectorPosicionInicialSMC_mm[i])/VectorPasoSMC_mm[i], 6)))
            print(numeroDePasos) # Es el número de pasos en cada Sección. Es para ver que no haya errores
            # de redondeo.
            for j in range(0,numeroDePasos): 
                if do_run == False:
                    return
                tiempoDeSleep = self.smc.CalcularTiempoSleep(VectorPasoSMC_mm[i]+self.smc.posicion)
                self.smc.Mover(VectorPasoSMC_mm[i]+self.smc.posicion)
                time.sleep(tiempoDeSleep)
                self.AdquirirGraficarYGrabarCSV()

    def MedicionAPosicionFijaSMC(self,
                            nombreArchivo,
                            VectorLongitudDeOndaInicial_nm,
                            VectorLongitudDeOndaFinal_nm,
                            VectorPasoMono_nm):
        global do_run
        self.nombreArchivo = nombreArchivo
        for i in range(0,len(VectorLongitudDeOndaInicial_nm)): # Loop sobre la cantidad de "Secciones".
            if do_run == False:
                return
            tiempoDeSleep = self.mono.CalcularTiempoSleep(VectorLongitudDeOndaInicial_nm[i])
            self.mono.Mover(VectorLongitudDeOndaInicial_nm[i])
            time.sleep(tiempoDeSleep)
            if i==0: # Idem MediciónALambdaFija
                self.AdquirirGraficarYGrabarCSV()
            if i>0 and VectorLongitudDeOndaInicial_nm[i] != VectorLongitudDeOndaFinal_nm[i-1]:
                self.AdquirirGraficarYGrabarCSV()
            numeroDePasos = abs(int(round((VectorLongitudDeOndaFinal_nm[i]-VectorLongitudDeOndaInicial_nm[i])/VectorPasoMono_nm[i], 6)))
            for j in range(0,numeroDePasos):
                if do_run == False:
                    return
                tiempoDeSleep = self.mono.CalcularTiempoSleep(round(VectorPasoMono_nm[i]+self.mono.posicion,4))
                self.mono.Mover(round(VectorPasoMono_nm[i]+self.mono.posicion,4))
                time.sleep(tiempoDeSleep)
                self.AdquirirGraficarYGrabarCSV()

    def MedicionCompleta(self, 
                         nombreArchivo,
                         VectorPosicionInicialSMC_mm,
                         VectorPosicionFinalSMC_mm,
                         VectorPasoSMC_mm,
                         VectorLongitudDeOndaInicial_nm,
                         VectorLongitudDeOndaFinal_nm,
                         VectorPasoMono_nm):
        self.nombreArchivo = nombreArchivo
        for i in range(0,len(VectorLongitudDeOndaInicial_nm)): # Loop sobre la cantidad de "Secciones" de lambdas.
            if do_run == False:
                return
            tiempoDeSleep = self.mono.CalcularTiempoSleep(VectorLongitudDeOndaInicial_nm[i])
            self.mono.Mover(VectorLongitudDeOndaInicial_nm[i])
            time.sleep(tiempoDeSleep)
            numeroDePasosMono = abs(int(round((VectorLongitudDeOndaFinal_nm[i]-VectorLongitudDeOndaInicial_nm[i])/VectorPasoMono_nm[i], 6)))
            for j in range(0,numeroDePasosMono+1): # Hace el barrido de cada sección del monocromador.
                if do_run == False:
                    return
                for k in range(0,len(VectorPosicionInicialSMC_mm)): # Loop sobre la cantidad de "Secciones" de la plataforma.
                    if do_run == False:
                        return
                    tiempoDeSleep = self.smc.CalcularTiempoSleep(VectorPosicionInicialSMC_mm[k])
                    self.smc.Mover(VectorPosicionInicialSMC_mm[k])
                    time.sleep(tiempoDeSleep)
                    if k==0:
                        self.AdquirirGraficarYGrabarCSV()
                    if k>0 and VectorPosicionInicialSMC_mm[k] != VectorPosicionFinalSMC_mm[k-1]:
                        self.AdquirirGraficarYGrabarCSV()
                    numeroDePasosSMC = abs(int(round((VectorPosicionFinalSMC_mm[k]-VectorPosicionInicialSMC_mm[k])/VectorPasoSMC_mm[k], 6)))
                    for l in range(0,numeroDePasosSMC): # Hace el barrido de cada sección de la plataforma.
                        if do_run == False:
                            return
                        tiempoDeSleep = self.smc.CalcularTiempoSleep(VectorPasoSMC_mm[k]+self.smc.posicion)
                        self.smc.Mover(VectorPasoSMC_mm[k]+self.smc.posicion)
                        time.sleep(tiempoDeSleep)
                        self.AdquirirGraficarYGrabarCSV()
                if j<numeroDePasosMono: # Mueve el monocromador para seguir barriendo con la plataforma.
                    tiempoDeSleep = self.mono.CalcularTiempoSleep(VectorPasoMono_nm[i] + self.mono.posicion)
                    self.mono.Mover(VectorPasoMono_nm[i] + self.mono.posicion)
                    time.sleep(tiempoDeSleep)

    def AdquirirGraficarYGrabarCSV(self):
        time.sleep(self.lockin.TiempoDeIntegracionTotal)
        vectorDeStringsDeDatos = self.ArmarVectorDeDatos()
        self.grafico.Graficar(vectorDeStringsDeDatos,self.smc.posicion,self.mono.posicion)
        self.GrabarCSV(vectorDeStringsDeDatos)

    def PrepararGuardadoCSV(self, nombreArchivo, metadata=None, repeticion=1):
        self.nombreArchivo = nombreArchivo
        self.data_manager.begin_run(nombreArchivo, metadata or {}, repeticion)

    def FinalizarGuardadoCSV(self):
        return self.data_manager.finish_run()

    def GuardarPromedioCSV(self, nombreArchivo, runs, metadata=None):
        return self.data_manager.save_average(nombreArchivo, runs, metadata or {})

    def GrabarCSV(self, vectorDeStringsDeDatos): # Crea un archivo y va appendeando filas.
        self.data_manager.append_row(vectorDeStringsDeDatos)

    def ArmarVectorDeDatos(self): # Transforma el string que devuelve el LockIn en un vector de strings y le agrega
        # la posición del smc y del mono.
        a = self.lockin.Adquirir()
        a = a + ',' + str(self.smc.posicion) + ',' + str(self.mono.posicion)
        b = a.split(',')
        return b

    def CalcularPromedioAux(self, segundosAPromediar): # Calcula un promedio del aux si se tildea la Box correspondiente.
        # Es para los gráficos que tienen el AUX diviendo.
        promedio = 0
        if segundosAPromediar == 0:
            return promedio
        sumaDeAuxs = 0
        numeroTotalDeAuxsAPromediar = segundosAPromediar*numeroDeAuxsPorSegundo
        tiempoADormirEnCadaMedicion = 1/numeroDeAuxsPorSegundo/10 # Es arbitrario. Es para darle unos milisegundos
                                                                  # mas al lock in para responder.
        for i in range(0,numeroTotalDeAuxsAPromediar): 
            medicion = self.ArmarVectorDeDatos()
            time.sleep(tiempoADormirEnCadaMedicion)
            aux = float(medicion[4])
            sumaDeAuxs = sumaDeAuxs + aux
        promedio = sumaDeAuxs/numeroTotalDeAuxsAPromediar
        return round(promedio, 6)

#%%%        

# Esta clase va armando los vectores de los ejes de los gráficos (y matrices en el plot de color). La idea es que
# en cada nueva medición (en cada barrido nuevo) esta clase se restartea al llamar a Configurar. Por eso cada vez
# que finaliza una medición se guarda el gráfico generado. Desde esta clase se plotea y se actualiza la ventana del
# tkinter.
# Posee una única figura que contiene adentro desde 1 hasta 6 gráficos que se van actualizando. Los gráficos se van
# actualizando de forma dinámica: para el colorplot los ejes de los gráficos están completamente determinados al 
# crearlos. Para los otros gráficos (los que no son colorplots) los ejes se van agrandando a medida que se actualizan.

class Grafico(): 

    def __init__(self):
        self.fig = plt.figure(figsize=(18,12), linewidth=10, edgecolor="#04253a")
        self.coloresRepeticiones = plt.rcParams["axes.prop_cycle"].by_key()["color"]
        self.lineasActuales = list()

    def Configurar(self, valoresAGraficar, promedioAux, promedioAuxBool, TipoDeMedicion, ejeX, VectorPosicionInicialSMC_mm = 0, VectorPosicionFinalSMC_mm = 0, VectorPasoSMC_mm = 0, VectorLongitudDeOndaInicial_nm = 0, VectorLongitudDeOndaFinal_nm = 0, VectorPasoMono_nm = 0, longitudDeOndaFija_nm = 0, posicionFijaSMC_mm = 0):
        self.fig.clear() # Borra la figura.
        self.fig.canvas.draw()
        self.fig.canvas.flush_events() # Actualiza la figura en la interfaz gráfica.
        self.TipoDeMedicion = TipoDeMedicion # Guarda el tipo de medición a realizar: 0, 1 o 2. (posicion, lambda o completa)
        self.ValoresAGraficar = valoresAGraficar # Es un vector de dimensión 6 con los booleanos de las checkbox
                                                 # que dicen qué cantidades se van a graficar.
        self.cantidadDeValoresAGraficar = valoresAGraficar.count(1)
        self.longitudDeOndaFija_nm = longitudDeOndaFija_nm # Para el tipo de medición 0
        self.posicionFijaSMC_mm = posicionFijaSMC_mm # Para el tipo de medición 1
        self.promedioAux = promedioAux 
        self.promedioAuxBool = promedioAuxBool # Es un booleano que tiene el valor de la checkbox de Promedio Aux.
        self.ejeX = ejeX # OJO: es un string: "Tiempo" o "Distancia" dependiendo qué se eligió en la interfaz.
        self.x = list() # Es el eje X para las mediciones tipo 0 o 1.
        self.listaDeEjesY = list() # Son los ejes Y de los gráficos. La lista poseerá tantos ejes Y como checkboxs
                                   # se hayan tildado.
        self.VectorX_mm = 0 # Es el eje X en mm para el colorplot. 
        self.VectorX_ps = 0 # Es el eje X en ps para el colorplot.
        self.VectorY = 0 # Es el eje Y en longitudes de onda para el colorplot.
        self.listaDeMatrices = list() # Esta lista poseerá adentro tantas matrices como valores a graficar se tildaron
                                      # en las checkbox. Cada matriz tantas filas y columnas como posiciones de la 
                                      # plataforma y del monocromador (no sé si respectivamente). En cada lugar guarda
                                      # el valor obtenido del lock in. Es para los colorplots!
        self.listaDeGraficos = list() # Una lista que poseerá tantos gráficos (los subplots en el código), como 
                                      # checkboxs se hayan tildado. Estos se usan para los tres tipos de mediciones.
        self.listaDeContours = list() # Se necesita para los colorplots.
        self.listaDeColorbars = list() # Idem.
        self.lineasActuales = list()
        self.repeticionActual = 1
        self.totalRepeticiones = 1
        self.graficarLeyenda = True
        self.graficarGrid = True

        self.diccionarioDeValoresAGraficar = dict() 
        
        if TipoDeMedicion == 0 or TipoDeMedicion == 1:
            for i in range(0, self.cantidadDeValoresAGraficar): 
                self.listaDeEjesY.append(list())
        if TipoDeMedicion == 2: # Crea los vectores X e Y y las matrices de los colorplots.
            numeroDePasos = 0
            self.VectorX_mm = np.array(VectorPosicionInicialSMC_mm[0])
            for i in range(0,len(VectorPosicionInicialSMC_mm)):
                if i>0 and VectorPosicionInicialSMC_mm[i] != VectorPosicionFinalSMC_mm[i-1]:
                    self.VectorX_mm = np.append(self.VectorX_mm, VectorPosicionInicialSMC_mm[i])
                numeroDePasos = int(round((VectorPosicionFinalSMC_mm[i]-VectorPosicionInicialSMC_mm[i])/VectorPasoSMC_mm[i], 3))
                for j in range(0,numeroDePasos):
                    self.VectorX_mm = np.append(self.VectorX_mm, round(VectorPosicionInicialSMC_mm[i]+(j+1)*VectorPasoSMC_mm[i],6))
            if self.ejeX == 'Tiempo':
                self.VectorX_ps = self.VectorX_mm*(2/3)*10
            numeroDePasos = 0
            self.VectorY = np.array(VectorLongitudDeOndaInicial_nm[0])
            for i in range(0,len(VectorLongitudDeOndaInicial_nm)):
                if i>0 and VectorLongitudDeOndaInicial_nm[i] != VectorLongitudDeOndaFinal_nm[i-1]:
                    self.VectorY = np.append(self.VectorY, VectorLongitudDeOndaInicial_nm[i])
                numeroDePasos = int(round((VectorLongitudDeOndaFinal_nm[i]-VectorLongitudDeOndaInicial_nm[i])/VectorPasoMono_nm[i],3))
                for j in range(0,numeroDePasos):
                    self.VectorY = np.append(self.VectorY, round(VectorLongitudDeOndaInicial_nm[i]+(j+1)*VectorPasoMono_nm[i],6))
            for i in range(0, self.cantidadDeValoresAGraficar):
                self.listaDeMatrices.append(np.zeros((len(self.VectorY),len(self.VectorX_mm))))
        
        # Se llena el diccionario.
        if valoresAGraficar[0] == 1:
            self.diccionarioDeValoresAGraficar['X'] = 0
        if valoresAGraficar[1] == 1:
            self.diccionarioDeValoresAGraficar['Y'] = 1
        if valoresAGraficar[2] == 1:
            self.diccionarioDeValoresAGraficar['R'] = 2
        if valoresAGraficar[3] == 1:
            self.diccionarioDeValoresAGraficar['\u03B8'] = 3
        if valoresAGraficar[4] == 1:
            self.diccionarioDeValoresAGraficar['X/AUX'] = 4
        if valoresAGraficar[5] == 1:
            self.diccionarioDeValoresAGraficar['R/AUX'] = 5
        self.listaDeValoresAGraficar = list(self.diccionarioDeValoresAGraficar.values())
        self.listaDeKeysDelDiccionario = list(self.diccionarioDeValoresAGraficar.keys())
        
        # Acá se agregan los gráficos a la única figura que hay.
        # Creo que no es necesario poner esto de una forma algorítmica.
        # Notar que los gráficos que están en la listaDeGraficos no están vinculados con los ejes todavía.
        if self.cantidadDeValoresAGraficar == 1:
            self.listaDeGraficos.append(self.fig.add_subplot(111))
        if self.cantidadDeValoresAGraficar == 2:
            self.listaDeGraficos.append(self.fig.add_subplot(211))
            self.listaDeGraficos.append(self.fig.add_subplot(212))
        if self.cantidadDeValoresAGraficar == 3:
            self.listaDeGraficos.append(self.fig.add_subplot(221))
            self.listaDeGraficos.append(self.fig.add_subplot(222))
            self.listaDeGraficos.append(self.fig.add_subplot(223))
        if self.cantidadDeValoresAGraficar == 4:
            self.listaDeGraficos.append(self.fig.add_subplot(221))
            self.listaDeGraficos.append(self.fig.add_subplot(222))
            self.listaDeGraficos.append(self.fig.add_subplot(223))
            self.listaDeGraficos.append(self.fig.add_subplot(224))
        if self.cantidadDeValoresAGraficar == 5:
            self.listaDeGraficos.append(self.fig.add_subplot(231))
            self.listaDeGraficos.append(self.fig.add_subplot(232))
            self.listaDeGraficos.append(self.fig.add_subplot(233))
            self.listaDeGraficos.append(self.fig.add_subplot(234))
            self.listaDeGraficos.append(self.fig.add_subplot(235))
        if self.cantidadDeValoresAGraficar == 6:
            self.listaDeGraficos.append(self.fig.add_subplot(231))
            self.listaDeGraficos.append(self.fig.add_subplot(232))
            self.listaDeGraficos.append(self.fig.add_subplot(233))
            self.listaDeGraficos.append(self.fig.add_subplot(234))
            self.listaDeGraficos.append(self.fig.add_subplot(235))
            self.listaDeGraficos.append(self.fig.add_subplot(236))
        self.CrearGrafico(TipoDeMedicion)
        self.AplicarEstiloEjes()
        
    def CrearGrafico(self, TipoDeMedicion): # Este método le pone los ejes y títulos a los gráficos.
        string = ' | Promedio Aux = ' + str(self.promedioAux)
        if TipoDeMedicion == 0:
            for i in range(0,self.cantidadDeValoresAGraficar):
                titulo = '\u03BB = ' + str(self.longitudDeOndaFija_nm) + ' nm'
                if self.promedioAuxBool:
                    self.listaDeGraficos[i].set_title(titulo + string)
                else:
                    self.listaDeGraficos[i].set_title(titulo)
                if self.ejeX == 'Distancia':
                    self.listaDeGraficos[i].set_xlabel('Retardo (mm)')
                else:
                    self.listaDeGraficos[i].set_xlabel('Retardo (ps)')
                self.listaDeGraficos[i].set_ylabel(self.listaDeKeysDelDiccionario[i])
                if self.listaDeValoresAGraficar[i] < 3 :
                    self.listaDeGraficos[i].yaxis.set_major_formatter(FormatStrFormatter('%.6f'))
        if TipoDeMedicion == 1:
            for i in range (0,self.cantidadDeValoresAGraficar):
                titulo = 'Posición = ' + str(self.posicionFijaSMC_mm) + ' mm'
                if self.promedioAuxBool:
                    self.listaDeGraficos[i].set_title(titulo + string)                    
                else:
                    self.listaDeGraficos[i].set_title(titulo)
                self.listaDeGraficos[i].set_xlabel('Longitud de onda (nm)')
                self.listaDeGraficos[i].set_ylabel(self.listaDeKeysDelDiccionario[i])
                if self.listaDeValoresAGraficar[i] < 3 :
                    self.listaDeGraficos[i].yaxis.set_major_formatter(FormatStrFormatter('%.6f'))
        if TipoDeMedicion == 2:
            for i in range(0,self.cantidadDeValoresAGraficar):
                if self.promedioAuxBool:
                    self.listaDeGraficos[i].set_title(self.listaDeKeysDelDiccionario[i]+ string)
                else:
                    self.listaDeGraficos[i].set_title(self.listaDeKeysDelDiccionario[i])                    
                if self.ejeX == 'Distancia':
                    self.listaDeGraficos[i].set_xlabel('Retardo (mm)')
                    self.listaDeContours.append(self.listaDeGraficos[i].contourf(self.VectorX_mm, self.VectorY, self.listaDeMatrices[i], 20, cmap='RdGy'))
                else:
                    self.listaDeGraficos[i].set_xlabel('Retardo (ps)')
                    # Acá se crean ya los contourplots de color.
                    self.listaDeContours.append(self.listaDeGraficos[i].contourf(self.VectorX_ps, self.VectorY, self.listaDeMatrices[i], 20, cmap='RdGy'))
                self.listaDeGraficos[i].set_ylabel('Longitud de onda (nm)') 
                
    def AplicarEstiloEjes(self):
        for grafico in self.listaDeGraficos:
            grafico.grid(self.graficarGrid, alpha=0.3)
            grafico.tick_params(direction="in")

    def IniciarRepeticion(self, repeticion=1, totalRepeticiones=1):
        self.repeticionActual = repeticion
        self.totalRepeticiones = totalRepeticiones
        self.x = list()
        self.lineasActuales = list()
        if self.TipoDeMedicion == 0 or self.TipoDeMedicion == 1:
            self.listaDeEjesY = [list() for i in range(0, self.cantidadDeValoresAGraficar)]
        if self.TipoDeMedicion == 2:
            for i in range(0, len(self.listaDeMatrices)):
                self.listaDeMatrices[i][:] = 0

    def ObtenerEtiquetaRepeticion(self):
        if self.totalRepeticiones > 1:
            return "Rep " + str(self.repeticionActual)
        return "Medicion"

    def ObtenerColorRepeticion(self):
        indice = (self.repeticionActual - 1) % len(self.coloresRepeticiones)
        return self.coloresRepeticiones[indice]

    def ObtenerLineaActual(self, indiceGrafico):
        while len(self.lineasActuales) <= indiceGrafico:
            self.lineasActuales.append(None)
        if self.lineasActuales[indiceGrafico] is None:
            linea, = self.listaDeGraficos[indiceGrafico].plot(
                [],
                [],
                marker="o",
                markersize=3,
                linewidth=1.4,
                color=self.ObtenerColorRepeticion(),
                label=self.ObtenerEtiquetaRepeticion(),
            )
            self.lineasActuales[indiceGrafico] = linea
            if self.graficarLeyenda and self.totalRepeticiones > 1:
                self.listaDeGraficos[indiceGrafico].legend(loc="best", fontsize=9)
        return self.lineasActuales[indiceGrafico]

    def ActualizarLimitesDeGrafico(self, indiceGrafico):
        self.listaDeGraficos[indiceGrafico].relim()
        self.listaDeGraficos[indiceGrafico].autoscale_view()

    def CalcularValorYGraficable(self, VectorAGraficar, indiceValor):
        if indiceValor != 4 and indiceValor != 5:
            return round(float(VectorAGraficar[indiceValor]), 6)
        aux = self.promedioAux
        if not self.promedioAuxBool:
            aux = float(VectorAGraficar[4])
        if aux == 0:
            return float("inf")
        if indiceValor == 4:
            return round(float(VectorAGraficar[0])/aux, 6)
        return round(float(VectorAGraficar[2])/aux, 6)

    # Los trés métodos que siguen se llaman cada vez que se hace una obtención de datos del Lock In en los barridos.

    def GraficarALambdaFija(self, VectorAGraficar, posicionSMC, posicionMono):
        if self.ejeX == 'Distancia':
            self.x.append(posicionSMC)
        else:
            self.x.append((posicionSMC)*(2/3)*10) # en picosegundos  
        # Este loop itera sobre cada gráfico de la figura. Se diferencia el 4 y el 5 porque son los X/Aux y R/Aux
        # que hay que dividirlos por Aux y por lo tanto darles un tratamiento especial debido a la posibilidad
        # de que esté promediado el Aux.
        for i in range(0, self.cantidadDeValoresAGraficar):
            if self.listaDeValoresAGraficar[i] != 4 and self.listaDeValoresAGraficar[i] != 5:
                self.listaDeEjesY[i].append(round(float(VectorAGraficar[self.listaDeValoresAGraficar[i]]), 6))
            else:
                if self.listaDeValoresAGraficar[i] == 4:
                    if self.promedioAuxBool:
                        self.listaDeEjesY[i].append(round(float(VectorAGraficar[2])/self.promedioAux, 6))
                    else:
                        self.listaDeEjesY[i].append(round(float(VectorAGraficar[0])/float(VectorAGraficar[4]), 6))
                elif self.listaDeValoresAGraficar[i] == 5:
                    if self.promedioAuxBool:
                        self.listaDeEjesY[i].append(round(float(VectorAGraficar[2])/self.promedioAux, 6))
                    else:
                        self.listaDeEjesY[i].append(round(float(VectorAGraficar[2])/float(VectorAGraficar[4]), 6))
            linea = self.ObtenerLineaActual(i)
            linea.set_data(self.x, self.listaDeEjesY[i])
            self.ActualizarLimitesDeGrafico(i)
        self.ActualizarFiguraEnInterfaz()

    def GraficarAPosicionFija(self, VectorAGraficar, posicionSMC, posicionMono):
        self.x.append(posicionMono)
        for i in range(0,self.cantidadDeValoresAGraficar):
            if self.listaDeValoresAGraficar[i] != 4 and self.listaDeValoresAGraficar[i] != 5:
                self.listaDeEjesY[i].append(round(float(VectorAGraficar[self.listaDeValoresAGraficar[i]]), 6))
            else:
                if self.listaDeValoresAGraficar[i] == 4:
                    if self.promedioAuxBool:
                        self.listaDeEjesY[i].append(round(float(VectorAGraficar[0])/self.promedioAux, 6))
                    else:
                        self.listaDeEjesY[i].append(round(float(VectorAGraficar[0])/float(VectorAGraficar[4]), 6))
                elif self.listaDeValoresAGraficar[i] == 5:
                    if self.promedioAuxBool:
                        self.listaDeEjesY[i].append(round(float(VectorAGraficar[0])/self.promedioAux, 6))
                    else:
                        self.listaDeEjesY[i].append(round(float(VectorAGraficar[2])/float(VectorAGraficar[4]), 6))
            linea = self.ObtenerLineaActual(i)
            linea.set_data(self.x, self.listaDeEjesY[i])
            self.ActualizarLimitesDeGrafico(i)
        self.ActualizarFiguraEnInterfaz()

    def GraficarCompletamente(self, VectorAGraficar, posicionSMC, posicionMono):
        posicionX = np.where(self.VectorX_mm == posicionSMC) # Este método recibe las posiciones actuales del SMC y
        posicionY = np.where(self.VectorY == posicionMono)   # del monocromador. Estas dos líneas buscan los índices
                                                             # de las matrices en los que se encuentran esos valores.
        if hasattr(self, 'listaDeColorbars'): # Vacía la listaDeColorbars.
            for i in range(0,len(self.listaDeColorbars)):
                self.listaDeColorbars[i].remove()
        self.listaDeColorbars = list()
        for i in range(0, self.cantidadDeValoresAGraficar):
            if self.listaDeValoresAGraficar[i] != 4 and self.listaDeValoresAGraficar[i] != 5:
                self.listaDeMatrices[i][posicionY[0][0],posicionX[0][0]] = float(VectorAGraficar[self.listaDeValoresAGraficar[i]])
            else:
                if self.listaDeValoresAGraficar[i] == 4:
                    if self.promedioAuxBool:
                        self.listaDeMatrices[i][posicionY[0][0],posicionX[0][0]] = float(VectorAGraficar[2])/self.promedioAux
                    else:
                        self.listaDeMatrices[i][posicionY[0][0],posicionX[0][0]] = float(VectorAGraficar[0])/float(VectorAGraficar[4])
                elif self.listaDeValoresAGraficar[i] == 5:
                    if self.promedioAuxBool:
                        self.listaDeMatrices[i][posicionY[0][0],posicionX[0][0]] = float(VectorAGraficar[0])/self.promedioAux
                    else:
                        self.listaDeMatrices[i][posicionY[0][0],posicionX[0][0]] = float(VectorAGraficar[2])/float(VectorAGraficar[4])
            if self.ejeX == 'Distancia':
                self.listaDeContours[i] = self.listaDeGraficos[i].contourf(self.VectorX_mm, self.VectorY, self.listaDeMatrices[i], 20, cmap='RdGy')
            else:
                self.listaDeContours[i] = self.listaDeGraficos[i].contourf(self.VectorX_ps, self.VectorY, self.listaDeMatrices[i], 20, cmap='RdGy')
            # Estas tres líneas que siguen son para las colorbars.
            divider = make_axes_locatable(self.listaDeGraficos[i])
            cax = divider.append_axes("right", size="5%", pad=0.05)
            self.listaDeColorbars.append(self.fig.colorbar(self.listaDeContours[i],cax=cax))
        self.ActualizarFiguraEnInterfaz()

    def ActualizarFiguraEnInterfaz(self):
        plt.tight_layout() # Reordena los gráficos para que no se superpongan.
        self.fig.canvas.draw()
        self.fig.canvas.flush_events()   

    def GraficarPromedio(self, filasPromedio):
        if self.TipoDeMedicion == 2:
            return
        xPromedio = list()
        yPromedio = [list() for i in range(0, self.cantidadDeValoresAGraficar)]
        for fila in filasPromedio:
            if self.TipoDeMedicion == 0:
                if self.ejeX == 'Distancia':
                    xPromedio.append(fila[6])
                else:
                    xPromedio.append((fila[6])*(2/3)*10)
            if self.TipoDeMedicion == 1:
                xPromedio.append(fila[7])
            for i in range(0, self.cantidadDeValoresAGraficar):
                yPromedio[i].append(self.CalcularValorYGraficable(fila, self.listaDeValoresAGraficar[i]))
        for i in range(0, self.cantidadDeValoresAGraficar):
            self.listaDeGraficos[i].plot(
                xPromedio,
                yPromedio[i],
                "k-",
                linewidth=2.4,
                label="Promedio",
            )
            self.listaDeGraficos[i].legend(loc="best", fontsize=9)
            self.ActualizarLimitesDeGrafico(i)
        self.ActualizarFiguraEnInterfaz()

    def GuardarGrafico(self, nombreArchivo):
        carpetaPlots = RutaEnCarpetaDelCodigo("Plots")
        os.makedirs(carpetaPlots, exist_ok=True)
        if os.path.splitext(nombreArchivo)[1] == "":
            nombreArchivo = nombreArchivo + ".png"
        self.fig.savefig(os.path.join(carpetaPlots, nombreArchivo), dpi=200)

    def Graficar(self, VectorAGraficar, posicionSMC, posicionMono): # Elije a qué método llamar.
        if self.TipoDeMedicion == 0:
            self.GraficarALambdaFija(VectorAGraficar, posicionSMC, posicionMono)
        if self.TipoDeMedicion == 1:
            self.GraficarAPosicionFija(VectorAGraficar, posicionSMC, posicionMono)
        if self.TipoDeMedicion == 2:
            self.GraficarCompletamente(VectorAGraficar, posicionSMC, posicionMono)

#%%%%
            
# Esta sección, con sus clases, maneja toda la interfaz gráfica. Hay 4 ventanas en total:
# Configuración: es la inicial
# Ventana principal (es Programa en el código). Está separada en muchos paneles para simplificar su ubicación 
# en la interfaz.
# Advertencia: es la que aparece para dar aviso o ayudas.
# Medición: es la que aparece al iniciar los barridos.
# La clase Programa además posee tres funciones que calculan los tiempos completos de las mediciones, para mostrarlo
# en la ventana Medición. Esto podría estar en Experimento. Posee también una función Salir que sigue un pequeño
# protocolo para cerrar el programa. 
# Al final de todo el código están las pocas líneas que corren el programa. Ver eso.
            
class Advertencia(): # Es simplemente una ventanita que tiene un título y un texto, con un botón para cerrarla.

    def __init__(self, titulo, texto):
        advertencia = tk.Tk()
        advertencia.title(titulo)
        ws, hs = advertencia.winfo_screenwidth(), advertencia.winfo_screenheight()
        advertencia.geometry('%dx%d+%d+%d' % (500, 200, ws/3, hs/3))
        labelExplicacion = tk.Label(advertencia, text = texto, font=(fuente,12))
        labelExplicacion.place(x=0, y=0)
        def Cerrar():
            advertencia.destroy()
        botonCerrar = tk.Button(advertencia, text = 'Ok', command = Cerrar, font=(fuente,15))
        botonCerrar.place(x=360, y = 140, height=30, width=40)
        advertencia.mainloop()

class Medicion():

    def IniciarVentana(self, programa, tiempoDeMedicion, tipoDeMedicion, experimento, VectorPosicionInicialSMC_mm=0, VectorPosicionFinalSMC_mm=0, VectorPasoSMC_mm=0, VectorLongitudDeOndaInicial_nm=0, VectorLongitudDeOndaFinal_nm=0, VectorPasoMono_nm=0):
        global do_run
        do_run = True
        self.midiendo = tk.Tk()
        self.midiendo.title('Midiendo')
        ws, hs = self.midiendo.winfo_screenwidth(), self.midiendo.winfo_screenheight()
        self.midiendo.geometry('%dx%d+%d+%d' % (520, 220, ws/3 , hs/70))
        cantidadDeMedicionesARealizar = int(programa.panelCantidadDeMedicionesARealizar.ObtenerCantidadDeMedicionesARealizar())
        horas, minutos, segundos, horaFinalizacion, minutoFinalizacion, segundoFinalizacion = self.CalcularDuracionYHoraDeFinalizacion(tiempoDeMedicion)
        horasVM, minutosVM, segundosVM, horaFinalizacionVM, minutoFinalizacionVM, segundoFinalizacionVM = self.CalcularDuracionYHoraDeFinalizacionVariasMediciones(tiempoDeMedicion, cantidadDeMedicionesARealizar)

        # Lo de abajo es un label que muestra lo que va a tardan la medición y la hora de finalización.
        if cantidadDeMedicionesARealizar == 1:
            self.labelEstado = tk.Label(self.midiendo, text="Realizando la medicion. Tiempo estimado: " + str(horas) + ' h ' + str(minutos) + ' m ' + str(segundos) + ' s. \n Hora estimada de finalización: ' + str(horaFinalizacion) + ':' + str(minutoFinalizacion) + ':' + str(segundoFinalizacion), font=(fuente,12))    
        else:
            self.labelEstado = tk.Label(self.midiendo, text="Realizando las mediciones. Tiempo estimado por medición: " + str(horas) + ' h ' + str(minutos) + ' m ' + str(segundos) + ' s. \n Tiempo estimado total: ' + str(horasVM) + ' h ' + str(minutosVM) + ' m ' + str(segundosVM) + ' s. \n Hora estimada de finalización: ' + str(horaFinalizacionVM) + ':' + str(minutoFinalizacionVM) + ':' + str(segundoFinalizacionVM), font=(fuente,12))    
            
        self.labelEstado.place(x=0, y=0)
        def Cancelar(): # Cancelar medición. Espera un segundo sumado al tiempo de integración del LockIn y 
                        # luego actualiza las posiciones de los motores.
            global do_run
            do_run = False
            time.sleep(experimento.lockin.TiempoDeIntegracionTotal+1)
            programa.panelJoggingPlataforma.Actualizar()
            programa.panelJoggingRedDeDifraccion.Actualizar()
            self.midiendo.destroy()
        botonCancelar = tk.Button(self.midiendo, text = 'Cancelar', command = Cancelar, font=(fuente,12))
        botonCancelar.place(x=70, y = 160, height=35, width=80)
        def Finalizar(): # Es un botón para cerrar la ventana una vez que finalizó completamente la medición.
            self.midiendo.destroy()
        self.botonFinalizar = tk.Button(self.midiendo, text = 'Finalizar', command = Finalizar, font=(fuente,12))
        self.botonFinalizar.place(x=200, y = 160, height=35, width=80)
        self.botonFinalizar["state"]="disabled" # Empieza deshabilitado. Se habilita al terminar la medición.
        def Medir():
            self.midiendo.update() # Para que aparezca la ventana antes de terminar de cargar todo el código.
            # Las próximas líneas levantan lo necesario de la interfaz gráfica.
            nombreArchivo = programa.panelNombreArchivo.textoNombreArchivo.get()
            programa.panelNombreArchivo.ActualizarNombreArchivo()
            ejeX = programa.panelEjeX.ObtenerValor()
            valoresAGraficar = programa.panelValoresAGraficar.ObtenerValores() 
            promedioAux = experimento.CalcularPromedioAux(programa.panelPromedioAux.ObtenerSegundosAPromediar())
            promediarRepeticiones = programa.panelPromedioRepeticiones.ObtenerPromedioRepeticionesBool()
            # Graba los valores elegidos en un .txt para que ya quede así para la próxima vez que se use el programa.
            programa.GrabarDataGraficos(ejeX, valoresAGraficar, programa.panelPromedioAux.ObtenerSegundosAPromediar(), programa.panelPromedioAux.ObtenerPromedioAuxBool(), cantidadDeMedicionesARealizar, promediarRepeticiones)
            metadataBase = self.ArmarMetadataBase(programa, tipoDeMedicion, ejeX, valoresAGraficar, cantidadDeMedicionesARealizar, VectorPosicionInicialSMC_mm, VectorPosicionFinalSMC_mm, VectorPasoSMC_mm, VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm)
            runs = list()
            medicionCancelada = False
            
            for i in range(0,int(cantidadDeMedicionesARealizar)):
                if int(cantidadDeMedicionesARealizar) > 1:
                    nombreArchivoDeLaMedicion_i = add_suffix_to_filename(nombreArchivo, i+1) 
                else:
                    nombreArchivoDeLaMedicion_i = nombreArchivo
                # Los próximos tres if son para generar el gráfico correspondiente a la medición. Configurar
                # es como resetear el objeto grafico.
                if tipoDeMedicion == 0 and i == 0:
                    programa.grafico.Configurar(valoresAGraficar, promedioAux, programa.panelPromedioAux.ObtenerPromedioAuxBool(), 0, ejeX, longitudDeOndaFija_nm=experimento.mono.posicion)
                if tipoDeMedicion == 1 and i == 0:
                    programa.grafico.Configurar(valoresAGraficar, promedioAux, programa.panelPromedioAux.ObtenerPromedioAuxBool(), 1, 0, posicionFijaSMC_mm = experimento.smc.posicion)
                if tipoDeMedicion == 2:
                    programa.grafico.Configurar(valoresAGraficar, promedioAux, programa.panelPromedioAux.ObtenerPromedioAuxBool(), 2, ejeX, VectorPosicionInicialSMC_mm, VectorPosicionFinalSMC_mm, VectorPasoSMC_mm, VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm)            
                experimento.grafico = programa.grafico # Se le asigna el mismo gráfico al objeto experimento.
                experimento.grafico.IniciarRepeticion(i+1, cantidadDeMedicionesARealizar)
                metadataMedicion = dict(metadataBase)
                metadataMedicion["repeticion"] = i+1
                experimento.PrepararGuardadoCSV(nombreArchivoDeLaMedicion_i, metadataMedicion, i+1)
           
                # Estos tres if son para realizar la medición. Dentro de estas líneas ocurren literalmente todas 
                # las mediciones.
                if tipoDeMedicion == 0:
                   experimento.MedicionALambdaFija(nombreArchivoDeLaMedicion_i,VectorPosicionInicialSMC_mm,VectorPosicionFinalSMC_mm,VectorPasoSMC_mm)
                if tipoDeMedicion == 1:
                    experimento.MedicionAPosicionFijaSMC(nombreArchivoDeLaMedicion_i,VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm)
                if tipoDeMedicion == 2:
                    experimento.MedicionCompleta(nombreArchivoDeLaMedicion_i, VectorPosicionInicialSMC_mm,VectorPosicionFinalSMC_mm,VectorPasoSMC_mm, VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm)
                runs.append(experimento.FinalizarGuardadoCSV())
                nombreGrafico = os.path.splitext(os.path.basename(nombreArchivoDeLaMedicion_i))[0]
                experimento.grafico.GuardarGrafico(nombreGrafico)         
                programa.panelJoggingPlataforma.Actualizar()  
                programa.panelJoggingRedDeDifraccion.Actualizar()
                self.CambiarEstadoAFinalizado(nombreArchivoDeLaMedicion_i, cantidadDeMedicionesARealizar, i)
                if do_run == False:
                    medicionCancelada = True
                    break
            if not medicionCancelada and promediarRepeticiones and cantidadDeMedicionesARealizar > 1:
                nombreArchivoPromedio = add_suffix_to_filename(nombreArchivo, "promedio")
                resultadoPromedio = experimento.GuardarPromedioCSV(nombreArchivoPromedio, runs, metadataBase)
                if resultadoPromedio["ok"]:
                    if tipoDeMedicion != 2:
                        experimento.grafico.GraficarPromedio(resultadoPromedio["rows"])
                        nombreGraficoPromedio = os.path.splitext(os.path.basename(nombreArchivoPromedio))[0]
                        experimento.grafico.GuardarGrafico(nombreGraficoPromedio)
                    self.CambiarEstadoPromedio("Promedio guardado: " + nombreArchivoPromedio)
                else:
                    self.CambiarEstadoPromedio("No se calculo promedio: " + resultadoPromedio["message"])
            self.HabilitarBotonFinalizar()
        Medir()
        self.midiendo.mainloop()

    def CalcularDuracionYHoraDeFinalizacion(self, tiempoDeMedicion):
        segundos = tiempoDeMedicion%60
        totalMinutos = int(tiempoDeMedicion/60)
        minutos = totalMinutos%60
        horas = int(totalMinutos/60)
        hora = datetime.datetime.now()
        horaActual = int(hora.strftime('%H'))
        minutoActual = int(hora.strftime('%M'))
        segundoActual = int(hora.strftime('%S'))
        segundoFinalizacion = (segundoActual + segundos)%60
        minutoFinalizacion = ((segundoActual+segundos)//60 + minutoActual + minutos)%60
        horaFinalizacion = horaActual + horas + (((segundoActual+segundos)//60 + minutoActual + minutos)//60)
        if segundoFinalizacion < 10:
            segundoFinalizacion = '0' + str(segundoFinalizacion)
        if minutoFinalizacion < 10:
            minutoFinalizacion = '0' + str(minutoFinalizacion)
        return horas, minutos, segundos, horaFinalizacion, minutoFinalizacion, segundoFinalizacion

    def CalcularDuracionYHoraDeFinalizacionVariasMediciones(self, tiempoDeMedicion, cantidadDeMedicionesARealizar):
        return self.CalcularDuracionYHoraDeFinalizacion(tiempoDeMedicion*cantidadDeMedicionesARealizar)

    def CambiarEstadoAFinalizado(self, nombreArchivo, cantidadDeMedicionesARealizar, numeroDeMedicion):
        if cantidadDeMedicionesARealizar == 1:
            self.labelEstadoFinalizado = tk.Label(self.midiendo, text="Medicion finalizada. El archivo ha sido guardado con el\n nombre: " + nombreArchivo, font=(fuente,12))
        else:
            self.labelEstadoFinalizado = tk.Label(self.midiendo, text="Medicion " + str(numeroDeMedicion+1) + " finalizada. El archivo ha sido guardado con el\n nombre: " + nombreArchivo, font=(fuente,12))
        self.labelEstadoFinalizado.place(x=0, y=80)  

    def CambiarEstadoPromedio(self, texto):
        self.labelEstadoPromedio = tk.Label(self.midiendo, text=texto, font=(fuente,10))
        self.labelEstadoPromedio.place(x=0, y=125)

    def ArmarMetadataBase(self, programa, tipoDeMedicion, ejeX, valoresAGraficar, cantidadDeMedicionesARealizar, VectorPosicionInicialSMC_mm, VectorPosicionFinalSMC_mm, VectorPasoSMC_mm, VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm):
        tipos = {0: "barrido_distancia_lambda_fija", 1: "barrido_lambda_posicion_fija", 2: "barrido_doble"}
        return {
            "tipo_medicion": tipos.get(tipoDeMedicion, "desconocido"),
            "eje_x_grafico": ejeX,
            "valores_graficados": valoresAGraficar,
            "repeticiones_totales": cantidadDeMedicionesARealizar,
            "promedio_repeticiones_activo": programa.panelPromedioRepeticiones.ObtenerPromedioRepeticionesBool(),
            "promedio_aux_activo": programa.panelPromedioAux.ObtenerPromedioAuxBool(),
            "promedio_aux_segundos": programa.panelPromedioAux.ObtenerSegundosAPromediar(),
            "tiempo_integracion_lockin_s": programa.experimento.lockin.TiempoDeIntegracionTotal,
            "numero_constantes_tiempo_lockin": getattr(programa.experimento.lockin, "numeroDeConstantesDeTiempo", ""),
            "puerto_smc": getattr(programa.experimento.smc, "puerto", ""),
            "puerto_sms": getattr(programa.experimento.mono, "puerto", ""),
            "puerto_lockin": getattr(programa.experimento.lockin, "puerto", ""),
            "smc_inicio_mm": VectorPosicionInicialSMC_mm,
            "smc_fin_mm": VectorPosicionFinalSMC_mm,
            "smc_paso_mm": VectorPasoSMC_mm,
            "lambda_inicio_nm": VectorLongitudDeOndaInicial_nm,
            "lambda_fin_nm": VectorLongitudDeOndaFinal_nm,
            "lambda_paso_nm": VectorPasoMono_nm,
        }
    
    def HabilitarBotonFinalizar(self):
        self.botonFinalizar["state"]="normal"                     

class Configuracion():
    
    def __init__(self, experimento, programa):
        self.primeraVez = True # Este booleano es para hacer que la primera vez aparezcan dos botones y luego
        # uno solo para volver al Menu Principal.
        self.experimento = experimento
        self.programa = programa
        self.b1 = False # Los tres booleanos b son para guardar el valor verdadero de haber identificado a los
        self.b2 = False # aparatos.
        self.b3 = False
        self.c1 = False # Los tres booleanos c son para guardar el valor verdadero de haber inicializado a los 
        self.c2 = False # aparatos.
        self.c3 = False    
    
    def AbrirVentana(self):
        raizConfiguracion = tk.Tk()
        raizConfiguracion.title('Pump and Probe Software - Configuración')
        ws, hs = raizConfiguracion.winfo_screenwidth(), raizConfiguracion.winfo_screenheight()
        raizConfiguracion.geometry('%dx%d+%d+%d' % (1360, 280,ws/6 ,hs/4 ))#'1450x825' Notebook #'1920x1080' Mi compu de escritorio #'' Laboratorio
        
        puertoSMCDefault, puertoSMSDefault, puertoLockInDefault = self.programa.LeerDataPuertos()

        # Esta parte es para armar las líneas que arman el cuadro de Configuracion.
        canvasRecuadros = Canvas(raizConfiguracion, width=ws, height=hs)
        canvasRecuadros.create_line(10, 35, 1350, 35)
        canvasRecuadros.create_line(270, 5,270, 180) 
        canvasRecuadros.create_line(490, 5,490, 180) 
        canvasRecuadros.create_line(730, 5,730, 180)
        canvasRecuadros.create_line(850, 5,850, 180)
        canvasRecuadros.create_line(1020, 5,1020, 180)
        canvasRecuadros.pack(fill=BOTH)

        # Son solo textos.
        labelPuertos = tk.Label(raizConfiguracion, text = 'Puertos', font=(fuente,15))
        labelPuertos.place(x=350, y=5)
        labelConfiguracion = tk.Label(raizConfiguracion, text = 'Configuración', font=(fuente,15))
        labelConfiguracion.place(x=540, y=5)
        labelCalibracion = tk.Label(raizConfiguracion, text = 'Calibración', font=(fuente,15))
        labelCalibracion.place(x=740, y=5)
        labelVelocidad = tk.Label(raizConfiguracion, text = 'Velocidad', font=(fuente,15))
        labelVelocidad.place(x=890, y=5)
        labelRedDeDifraccion = tk.Label(raizConfiguracion, text = 'Red de difracción', font=(fuente,15))
        labelRedDeDifraccion.place(x=1100, y=5)

        # SMC - PLATAFORMA DE RETARDO #
        # Esta función se llama al tocar el botón Setear.
        def SetearPuertoSMC():
            # Primero intenta agarrar el número de puerto de la cajita.
            try:
                puertoSMC = int(textoSMC.get())
            except ValueError:
                Advertencia('Atención','El valor ingresado debe ser un número entero.')
                return
            # Luego intenta abrir el puerto serie.
            try:
                self.experimento.smc.AsignarPuerto('COM' + str(puertoSMC))
            except Exception as error:
                Advertencia('Atención','No se ha podido abrir COM' + str(puertoSMC) + '.\n' + str(error) + '\n\n' + TextoPuertosSerieDisponibles())
                return
            # Acá se aseguro de estar leyendo bien el aparato.
            self.b1 = self.experimento.smc.Identificar() # Booleano
            if self.b1:
                labelSMCReconocido.config(text = 'Reconocido', font=(fuente,12))
                botonInicializarSMC["state"]="normal"
            else:
                labelSMCReconocido.config(text = 'No reconocido', font=(fuente,12))
                self.experimento.smc.CerrarPuerto()
        # Esta función se llama al tocar le botón Inicializar.
        def InicializarSMC():
            self.experimento.smc.Configurar()
            self.c1 = True
            labelSMCInicializado.config(text = 'Inicializado', font=(fuente,12))
            botonCalibrarSMC['state'] = 'normal'
            botonCambiarVelocidadSMC["state"]="normal"
            textoVelocidadSMC["state"]="normal"
            textoVelocidadSMC.config(text=str(self.experimento.smc.velocidadMmPorSegundo))
        def CambiarVelocidadSMC():
            self.experimento.smc.CambiarVelocidad(float(textoVelocidadSMC.get()))
        labelSMC = tk.Label(raizConfiguracion, text = 'Plataforma de retardo(SMC)', font=(fuente,15))
        labelSMC.place(x=5, y=45)
        textoSMC = tk.Entry(raizConfiguracion, font=(fuente,15))
        textoSMC.place(x=280, y=45, height=30, width=30)
        textoSMC.delete(0, tk.END)
        textoSMC.insert(0, str(puertoSMCDefault))
        textoVelocidadSMC = tk.Entry(raizConfiguracion, font=(fuente,15))
        textoVelocidadSMC.place(x=860, y=45, height=30, width=50)
        botonSetearPuertoSMC = tk.Button(raizConfiguracion, text = 'Setear', command = SetearPuertoSMC, font=(fuente,12))
        botonSetearPuertoSMC.place(x=315,y=45)
        botonInicializarSMC = tk.Button(raizConfiguracion, text = 'Inicializar', command = InicializarSMC, font=(fuente,12))
        botonInicializarSMC.place(x=500,y=45)
        botonCalibrarSMC = tk.Button(raizConfiguracion, text = 'Calibrar', command = self.experimento.smc.Calibrar, font=(fuente,12))
        botonCalibrarSMC.place(x=740, y=45)
        botonCambiarVelocidadSMC = tk.Button(raizConfiguracion, text = 'Cambiar', command = CambiarVelocidadSMC, font=(fuente,12))
        botonCambiarVelocidadSMC.place(x=930, y=45)
        # Estos if y else son para que al reabrir la ventana configuración esté todo como tiene que estar.
        # Esto podría pasarse a objetos de una forma más normal...
        if self.b1:
            labelSMCReconocido = tk.Label(raizConfiguracion, text = 'Reconocido', font=(fuente,12))
            botonInicializarSMC["state"] = "normal"
        else:
            labelSMCReconocido = tk.Label(raizConfiguracion)
            botonInicializarSMC["state"] = "disabled"             
        labelSMCReconocido.place(x=380, y=50)
        if self.c1:
            labelSMCInicializado = tk.Label(raizConfiguracion, text = 'Inicializado', font=(fuente,12))
            botonCalibrarSMC["state"] = "normal"    
            botonCambiarVelocidadSMC["state"]="normal"
            textoVelocidadSMC["state"]="normal"
            textoVelocidadSMC.config(text=str(self.experimento.smc.velocidadMmPorSegundo))
        else:
            labelSMCInicializado = tk.Label(raizConfiguracion)
            botonCalibrarSMC["state"] = "disabled"   
            botonCambiarVelocidadSMC["state"]="disabled"
            textoVelocidadSMC["state"]="disabled"
        labelSMCInicializado.place(x=640, y=50)
        
        # SMS - MONOCROMADOR #
        def SetearPuertoSMS():
            try:
                puertoSMS = int(textoMono.get())
            except ValueError:
                Advertencia('Atención','El valor ingresado debe ser un número entero.')
                return
            try:
                self.experimento.mono.AsignarPuerto('COM' + str(puertoSMS))
            except Exception as error:
                Advertencia('Atención','No se ha podido abrir COM' + str(puertoSMS) + '.\n' + str(error) + '\n\n' + TextoPuertosSerieDisponibles())
                return
            self.b2 = self.experimento.mono.Identificar() # Booleano
            if self.b2:
                labelSMSReconocido.config(text = 'Reconocido', font=(fuente,12))
                botonInicializarSMS["state"]="normal"
            else:
                labelSMSReconocido.config(text = 'No reconocido', font=(fuente,12))
                self.experimento.mono.CerrarPuerto()
        def InicializarSMS():
            self.experimento.mono.Configurar()       
            self.c2 = True
            labelSMSInicializado.config(text = 'Inicializado', font=(fuente,12))
            botonCalibrarSMS['state'] = 'normal'
            botonCambiarVelocidadSMS["state"]="normal"
            textoVelocidadSMS["state"]="normal"
            textoVelocidadSMS.config(text=str(self.experimento.mono.velocidadNmPorSegundo))
            multiplicador = self.experimento.mono.multiplicador
            if multiplicador == 32:
                variable.set('1200')
            if multiplicador == 16:
                variable.set('600')
            w["state"]="normal"
        def CambiarVelocidadSMS():
            self.experimento.mono.CambiarVelocidad(float(textoVelocidadSMS.get()))
        def CambiarRed():
            self.experimento.mono.CambiarRed(variable.get())
        labelMono = tk.Label(raizConfiguracion, text = 'Red de difracción(SMS)', font=(fuente,15))
        labelMono.place(x=5, y=95)
        textoMono = tk.Entry(raizConfiguracion, font=(fuente,15))
        textoMono.place(x=280, y=95, height=30, width=30)
        textoMono.delete(0, tk.END)
        textoMono.insert(0, str(puertoSMSDefault))
        botonSetearPuertoSMS = tk.Button(raizConfiguracion, text = 'Setear', command = SetearPuertoSMS, font=(fuente,12))
        botonSetearPuertoSMS.place(x=315,y=95)
        botonInicializarSMS = tk.Button(raizConfiguracion, text = 'Inicializar', command = InicializarSMS, font=(fuente,12))
        botonInicializarSMS.place(x=500,y=95)
        botonCalibrarSMS = tk.Button(raizConfiguracion, text = 'Calibrar', command = self.experimento.mono.Calibrar, font=(fuente,12))
        botonCalibrarSMS.place(x=740, y=95)
        textoVelocidadSMS = tk.Entry(raizConfiguracion, font=(fuente,15))
        textoVelocidadSMS.place(x=860, y=95, height=30, width=50)
        botonCambiarVelocidadSMS = tk.Button(raizConfiguracion, text = 'Cambiar', command = CambiarVelocidadSMS, font=(fuente,12))
        botonCambiarVelocidadSMS.place(x=930, y=95)
        labelRed = tk.Label(raizConfiguracion, text="ranuras/mm ", font=(fuente,15))
        labelRed.place(x=1145, y=95) 
        botonCambiarRed = tk.Button(raizConfiguracion, text = 'Cambiar', command = CambiarRed, font=(fuente,12))
        botonCambiarRed.place(x=1260, y=95)
        choices = ['600', '1200']
        variable = tk.StringVar(raizConfiguracion)
        w = tk.OptionMenu(raizConfiguracion, variable, *choices)
        w.config(font=(fuente,12))
        w.place(x=1040,y=95, height=35, width=100)
        if self.b2:
            labelSMSReconocido = tk.Label(raizConfiguracion, text = 'Reconocido', font=(fuente,12))
            botonInicializarSMS["state"] = "normal"             
        else:
            labelSMSReconocido = tk.Label(raizConfiguracion)
            botonInicializarSMS["state"] = "disabled"             
        labelSMSReconocido.place(x=380, y=95)
        if self.c2:
            labelSMSInicializado = tk.Label(raizConfiguracion, text = 'Inicializado', font=(fuente,12))
            botonCalibrarSMS["state"] = "normal"    
            botonCambiarVelocidadSMS["state"]="normal"
            textoVelocidadSMS["state"]="normal"
            textoVelocidadSMS.config(text=str(self.experimento.mono.velocidadNmPorSegundo))
            w["state"] = "normal"
            botonCambiarRed["state"] = "normal"
            multiplicador = self.experimento.mono.multiplicador
            if multiplicador == 32:
                variable.set('1200')
            if multiplicador == 16:
                variable.set('600')
        else:
            labelSMSInicializado = tk.Label(raizConfiguracion)
            botonCalibrarSMS["state"] = "disabled"  
            botonCambiarVelocidadSMS["state"]="disabled"
            textoVelocidadSMS["state"]="disabled"
            w["state"]="disabled"
            botonCambiarRed["state"] = "disabled"  
        labelSMSInicializado.place(x=640, y=95)
        
        # LOCK IN #
        def SetearPuertoLockIn():
            try:
                puertoLockIn = int(textoLockIn.get())
            except ValueError:
                Advertencia('Atención','El valor ingresado debe ser un número entero.')
                return
            try:
                self.experimento.lockin.AsignarPuerto(str(puertoLockIn))
            except:
                Advertencia('Atención','No se ha podido abrir el puerto GPIB.')
                return
            self.b3 = self.experimento.lockin.Identificar() # Booleano
            if self.b3:
                labelLockInReconocido.config(text = 'Reconocido', font=(fuente,12))
                botonInicializarLockIn["state"] = "normal"
            else:
                labelLockInReconocido.config(text = 'No reconocido', font=(fuente,12))                
        def InicializarLockIn():
            self.experimento.lockin.Configurar()   
            self.c3 = True           
            labelLockInInicializado.config(text = 'Inicializado', font=(fuente,12))
        labelLockIn = tk.Label(raizConfiguracion, text = 'Lock-In', font=(fuente,15))
        labelLockIn.place(x=5, y=140)
        textoLockIn = tk.Entry(raizConfiguracion, font=(fuente,15))
        textoLockIn.place(x=280, y=140, height=30, width=30)
        textoLockIn.delete(0, tk.END)
        textoLockIn.insert(0, puertoLockInDefault)
        botonSetearPuertoLockIn = tk.Button(raizConfiguracion, text = 'Setear', command = SetearPuertoLockIn, font=(fuente,12))
        botonSetearPuertoLockIn.place(x=315,y=140)
        botonInicializarLockIn = tk.Button(raizConfiguracion, text = 'Inicializar', command = InicializarLockIn, font=(fuente,12))
        botonInicializarLockIn.place(x=500,y=140)
        if self.b3:
            labelLockInReconocido = tk.Label(raizConfiguracion, text='Reconocido', font=(fuente,12))
            botonInicializarLockIn["state"] = "normal"
        else:
            labelLockInReconocido = tk.Label(raizConfiguracion)
            botonInicializarLockIn["state"] = "disabled"
        labelLockInReconocido.place(x=380, y=140)
        if self.c3:
            labelLockInInicializado = tk.Label(raizConfiguracion, text = 'Inicializado', font=(fuente,12))
        else:
            labelLockInInicializado = tk.Label(raizConfiguracion)
        labelLockInInicializado.place(x=640, y=140)
        # Cuando se abre el programa empieza en la ventana configuración y se tiene dos opciones: Salir o 
        # Continuar. Luego de Continuar, si se quiere volver a la ventana configuración, como ya no es la 
        # primera vez que se llama a configuración, solo aparece el botón Volver para ir a la ventana principal.
        def MenuPrincipal():
            self.programa.GrabarDataPuertos(textoSMC.get(), textoMono.get(), textoLockIn.get())
            raizConfiguracion.destroy()
            # Acá se llama a la Pantalla Principal y se corre casi todo el código de la clase Programa.
            self.programa.PantallaPrincipal()
        def Salir():
            raizConfiguracion.destroy()                    
        if self.primeraVez:
            botonMenuPrincipal = tk.Button(raizConfiguracion, text = 'Continuar', command = MenuPrincipal, font=(fuente,15))
            botonMenuPrincipal.place(x=200, y=200)
            botonSalir = tk.Button(raizConfiguracion, text = 'Salir', command = Salir, font=(fuente,15))
            botonSalir.place(x=100, y=200)
            self.primeraVez = False
        else:
            botonSalir = tk.Button(raizConfiguracion, text = 'Volver', command = Salir, font=(fuente,15))
            botonSalir.place(x=100, y=200)            
        raizConfiguracion.mainloop()
        
# Es la ventana principal. Cuando se crea el objeto "programa" se crea un objeto "experimento" y otro 
# "configuracion" contenidos dentro del objeto programa. Se abre la ventana de Configuración. 

class Programa():    
    
    def __init__(self):
        self.experimento = Experimento()
        self.configuracion = Configuracion(self.experimento, self)
        self.configuracion.AbrirVentana()
    
    class PanelValoresAGraficar():
        
        def __init__(self, raiz, posicion, boolXDefault, boolYDefault, boolRDefault, boolTitaDefault, boolXAuxDefault, boolRAuxDefault):
            X = posicion[0]
            Y = posicion[1]
            labelGraficos = tk.Label(raiz, text="Valores a graficar: ", font=(fuente,15))
            labelGraficos.place(x=X, y=Y)
            self.Var1 = tk.IntVar()
            tk.Checkbutton(raiz, text='X', variable=self.Var1, font=(fuente,15)).place(x=X,y=Y+25)
            self.Var1.set(boolXDefault)
            self.Var2 = tk.IntVar()
            tk.Checkbutton(raiz, text='Y', variable=self.Var2, font=(fuente,15)).place(x=X+50,y=Y+25)
            self.Var2.set(boolYDefault)
            self.Var3 = tk.IntVar()
            tk.Checkbutton(raiz, text='R', variable=self.Var3, font=(fuente,15)).place(x=X+100,y=Y+25)
            self.Var3.set(boolRDefault)
            self.Var4 = tk.IntVar()
            tk.Checkbutton(raiz, text='\u03B8', variable=self.Var4, font=(fuente,15)).place(x=X+148,y=Y+25)
            self.Var4.set(boolTitaDefault)
            self.Var5 = tk.IntVar()
            tk.Checkbutton(raiz, text='X/AUX', variable=self.Var5, font=(fuente,15)).place(x=X+195,y=Y+25)
            self.Var5.set(boolXAuxDefault)
            self.Var6 = tk.IntVar()
            tk.Checkbutton(raiz, text='R/AUX', variable=self.Var6, font=(fuente,15)).place(x=X+285,y=Y+25)            
            self.Var6.set(boolRAuxDefault)
            
        def ObtenerValores(self):
            return (self.Var1.get(), self.Var2.get(), self.Var3.get(), self.Var4.get(), self.Var5.get(), self.Var6.get())
    
    class PanelEjeX():
        
        def __init__(self, raiz, posicion, ejeXDefault):
            X = posicion[0]
            Y = posicion[1]
            labelEjeX = tk.Label(raiz, text="Eje X del gráfico: ", font=(fuente,15))
            labelEjeX.place(x=X, y=Y) 
            choices = ['Tiempo', 'Distancia']
            self.variable = tk.StringVar(raiz)
            self.variable.set(ejeXDefault)
            w = tk.OptionMenu(raiz, self.variable, *choices)
            w.config(font=(fuente,12))
            w.place(x=X+228,y=Y-3, height=35, width=130)
        
        def ObtenerValor(self):
            return(self.variable.get())
    
    class PanelNombreArchivo():
        
        def __init__(self, raiz, posicion):
            self.numeroDeMedicion = self.LecturaTxt()
            X = posicion[0]
            Y = posicion[1]
            labelNombreArchivo = tk.Label(raiz, text="Nombre del archivo:", font=(fuente,15))
            labelNombreArchivo.place(x=X, y=Y)
            self.textoNombreArchivo = tk.Entry(raiz,width=15, font=(fuente,10))
            self.textoNombreArchivo.place(x=X+230, y=Y, height=30, width=145)
            self.textoNombreArchivo.delete(0, tk.END)
            fecha = date.today()
            fechaEnFormatoString = fecha.strftime("%Y-%m-%d")
            nombre = fechaEnFormatoString + '_' + str(self.numeroDeMedicion) + '.csv'
            self.textoNombreArchivo.insert(0, nombre)
    
        def ActualizarNombreArchivo(self):
            self.numeroDeMedicion += 1
            fecha = date.today()
            fechaEnFormatoString = fecha.strftime("%Y-%m-%d")
            nombreFechadoNuevo = fechaEnFormatoString + '_' + str(self.numeroDeMedicion) + '.csv'
            self.textoNombreArchivo.delete(0, tk.END)
            self.textoNombreArchivo.insert(0, nombreFechadoNuevo)      
            with open(RutaEnCarpetaDelCodigo('dataNombreArchivo.txt'), 'w') as f:
                f.write(nombreFechadoNuevo)
        
        def LecturaTxt(self):
            with open(RutaEnCarpetaDelCodigo('dataNombreArchivo.txt'), 'r') as f:
                linea = f.readline()
                fecha = date.today()
                fechaEnFormatoString = fecha.strftime("%Y-%m-%d")
                if fechaEnFormatoString in linea:
                    return int((linea.split('_')[1]).split('.')[0])
                else:
                    return 1
 
    class PanelPromedioAux():
        
        def __init__(self, raiz, posicion, segundosAPromediarDefault, boolPromedioAuxDefault):
            X = posicion[0]
            Y = posicion[1]
            
            self.Var7 = tk.IntVar()
            tk.Checkbutton(raiz, text='Promediar Aux:', variable=self.Var7, command=self.CambiarEstadoDeEntradaDeTexto, font=(fuente,15)).place(x=X,y=Y)
            self.Var7.set(boolPromedioAuxDefault)
            self.textoSegundosAPromediar = tk.Entry(raiz, font=(fuente,15))
            self.textoSegundosAPromediar.place(x=X+230, y=Y, height=30, width=40)
            if boolPromedioAuxDefault:
                self.textoSegundosAPromediar["state"]="normal"
            else:
                self.textoSegundosAPromediar["state"]="disabled"
            self.textoSegundosAPromediar.delete(0, tk.END)
            self.textoSegundosAPromediar.insert(0, segundosAPromediarDefault)
            self.labelSegundos = tk.Label(raiz, text='segundos', font=(fuente,15))
            self.labelSegundos.place(x=X+275, y=Y)
        
        def ObtenerSegundosAPromediar(self):
            if self.Var7.get():
                return int(self.textoSegundosAPromediar.get())
            else:
                return 0
        
        def ObtenerPromedioAuxBool(self):
            return self.Var7.get()
    
        def CambiarEstadoDeEntradaDeTexto(self):
            if self.Var7.get():
                self.textoSegundosAPromediar["state"]="normal"
            else:
                self.textoSegundosAPromediar["state"]="disabled"
    
    class PanelCantidadDeMedicionesARealizar():
        
        def __init__(self, raiz, posicion, cantidadDeMedicionesARealizarDefault):
            X = posicion[0]
            Y = posicion[1]
            
            self.labelCantidadDeMedicionesARealizar = tk.Label(raiz, text='Número de mediciones:', font=(fuente,15))
            self.labelCantidadDeMedicionesARealizar.place(x=X, y=Y)            
            self.textoCantidadDeMedicionesARealizar = tk.Entry(raiz, font=(fuente,15))
            self.textoCantidadDeMedicionesARealizar.place(x=X+230, y=Y, height=30, width=40)
            self.textoCantidadDeMedicionesARealizar.delete(0, tk.END)
            self.textoCantidadDeMedicionesARealizar.insert(0, cantidadDeMedicionesARealizarDefault)            
            
        def ObtenerCantidadDeMedicionesARealizar(self):
            return self.textoCantidadDeMedicionesARealizar.get()

    class PanelPromedioRepeticiones():

        def __init__(self, raiz, posicion, boolPromedioRepeticionesDefault):
            X = posicion[0]
            Y = posicion[1]
            self.VarPromedioRepeticiones = tk.IntVar()
            tk.Checkbutton(raiz, text='Promediar reps', variable=self.VarPromedioRepeticiones, font=(fuente,11)).place(x=X,y=Y)
            self.VarPromedioRepeticiones.set(boolPromedioRepeticionesDefault)

        def ObtenerPromedioRepeticionesBool(self):
            return self.VarPromedioRepeticiones.get()
    
    class PanelConversor():
    
        def __init__(self, raiz, posicion):
            X = posicion[0] 
            Y = posicion[1] 
            labelTituloConversor = tk.Label(raiz, text="Conversor", font=(fuente,20))
            labelTituloConversor.place(x=X+205, y=Y-60)
            def Ayuda():
                Advertencia('Información', 'La conversión tiene incluida el factor x2 que genera la reflección \n en el espejo  retrorefractor de la plataforma de retardo.')
            botonAyuda = tk.Button(raiz, text="?", command=Ayuda, font=(fuente,15))
            botonAyuda.place(x=X+410, y=Y-60, height=30, width=30)
            
            labelmm = tk.Label(raiz, text="mm", font=(fuente,20))
            labelmm.place(x=X+160, y=Y-15)
            labelfs = tk.Label(raiz, text="fs", font=(fuente,20))
            labelfs.place(x=X+370, y=Y-15)
            textomm = tk.Entry(raiz, font=(fuente,20))
            textomm.place(x=X+125, y=Y+17, height=40, width=100)
            textofs = tk.Entry(raiz, font=(fuente,20))
            textofs.place(x=X+340, y=Y+17, height=40 ,width=100)
            def ConvertirAfs():
                mm = textomm.get()
                fs = round(float(mm)*6666.666,1)
                textofs.delete(0, tk.END)
                textofs.insert(tk.END, fs)
            def ConvertirAmm():
                fs = textofs.get()
                mm = round(float(fs)/6666.666,5)
                textomm.delete(0, tk.END)
                textomm.insert(tk.END, mm)
            botonConvertirAmm = tk.Button(raiz, text="<-", command=ConvertirAmm, font=(fuente,15))
            botonConvertirAmm.place(x=X+235, y=Y+17, height=40, width=45)
            botonConvertirAfs = tk.Button(raiz, text="->", command=ConvertirAfs, font=(fuente,15))
            botonConvertirAfs.place(x=X+280, y=Y+17, height=40, width=45)
    
    # En esta clase se usa un hilo (thread) para correr en paralelo el programa y el loop de medición manual.
    class PanelMedicionManual():
    
        def __init__(self, raiz, posicion, experimento):
            self.experimento = experimento
            X = posicion[0]
            Y = posicion[1]
            labelX = tk.Label(raiz, text = 'X')
            labelX.place(x=X+70, y=Y)
            labelX.config(font=("Helvetica", 25))
            textoX = tk.Entry(raiz, font=("Helvetica",30))
            textoX.place(x=X-7, y=Y+35, height=45, width=180)
            labelY = tk.Label(raiz, text = 'Y')
            labelY.place(x=X+70, y=Y+85+1*13)
            labelY.config(font=("Helvetica", 25))
            textoY = tk.Entry(raiz, font=("Helvetica",30))
            textoY.place(x=X-7, y=Y+120+1*13, height=45, width=180)
            labelR = tk.Label(raiz, text = 'R')
            labelR.place(x=X+70, y=Y+170+2*13)
            labelR.config(font=("Helvetica", 25))
            textoR = tk.Entry(raiz, font=("Helvetica",30))
            textoR.place(x=X-7, y=Y+205+2*13, height=45, width=180)
            labelTheta = tk.Label(raiz, text = '\u03B8')
            labelTheta.place(x=X+70, y=Y+255+3*13)
            labelTheta.config(font=("Helvetica", 25))
            textoTheta = tk.Entry(raiz, font=("Helvetica",30))
            textoTheta.place(x=X-7, y=Y+290+3*13, height=45, width=180)
            labelAuxIn = tk.Label(raiz, text = 'Aux')
            labelAuxIn.place(x=X+55, y=Y+340+4*13)
            labelAuxIn.config(font=("Helvetica", 25))
            textoAuxIn = tk.Entry(raiz, font=("Helvetica",30))
            textoAuxIn.place(x=X-7, y=Y+375+4*13, height=45, width=180)
            labelCocienteXConAuxIn = tk.Label(raiz, text = 'X/Aux')
            labelCocienteXConAuxIn.place(x=X+35, y=Y+425+5*13)
            labelCocienteXConAuxIn.config(font=("Helvetica", 25))
            textoCocienteXConAuxIn = tk.Entry(raiz, font=("Helvetica",30))
            textoCocienteXConAuxIn.place(x=X-7, y=Y+460+5*13, height=45, width=180)
            labelCocienteRConAuxIn = tk.Label(raiz, text = 'R/Aux')
            labelCocienteRConAuxIn.place(x=X+35, y=Y+510+6*13)
            labelCocienteRConAuxIn.config(font=("Helvetica", 25))
            textoCocienteRConAuxIn = tk.Entry(raiz, font=("Helvetica",30))
            textoCocienteRConAuxIn.place(x=X-7, y=Y+545+6*13, height=45, width=180)
            labelFrecuencia = tk.Label(raiz, text = 'f')
            labelFrecuencia.place(x=X+70, y=Y+595+7*13)
            labelFrecuencia.config(font=("Helvetica", 25))
            textoFrecuencia = tk.Entry(raiz, font=("Helvetica",30))
            textoFrecuencia.place(x=X-7, y=Y+630+7*13, height=45, width=180)
            def IniciarMedicion():
                global t
                t = th.Thread(target=MedicionManual)
                t.do_run = True
                t.start()
            def MedicionManual():
                while t.do_run == True:
                    time.sleep(self.experimento.lockin.TiempoDeIntegracionTotal)
                    vectorDeStringsDeDatos = self.experimento.ArmarVectorDeDatos()
                    textoX.delete(0, tk.END)
                    textoX.insert(tk.END, str('{:.6f}'.format(round(float(vectorDeStringsDeDatos[0]), 6))))
                    textoY.delete(0, tk.END)
                    textoY.insert(tk.END, str('{:.6f}'.format(round(float(vectorDeStringsDeDatos[1]), 6))))
                    textoR.delete(0, tk.END)
                    textoR.insert(tk.END, str('{:.6f}'.format(round(float(vectorDeStringsDeDatos[2]), 6))))
                    textoTheta.delete(0, tk.END)
                    textoTheta.insert(tk.END, str(round(float(vectorDeStringsDeDatos[3]), 6)))
                    textoAuxIn.delete(0, tk.END)
                    textoAuxIn.insert(tk.END, str('{:.6f}'.format(round(float(vectorDeStringsDeDatos[4]), 6))))
                    textoFrecuencia.delete(0, tk.END)
                    textoFrecuencia.insert(tk.END, str(round(float(vectorDeStringsDeDatos[5]), 6)))
                    cocienteXConAux = 0
                    cocienteRConAux = 0
                    if float(vectorDeStringsDeDatos[4]) != 0:
                        cocienteXConAux = round(float(vectorDeStringsDeDatos[0])/float(vectorDeStringsDeDatos[4]), 6)
                        cocienteRConAux = round(float(vectorDeStringsDeDatos[2])/float(vectorDeStringsDeDatos[4]), 6)
                    else:
                        cocienteXConAux = float('inf')
                        cocienteRConAux = float('inf')
                    textoCocienteXConAuxIn.delete(0, tk.END)
                    textoCocienteXConAuxIn.insert(tk.END, str('{:.6f}'.format(cocienteXConAux)))
                    textoCocienteRConAuxIn.delete(0, tk.END)
                    textoCocienteRConAuxIn.insert(tk.END, str('{:.6f}'.format(cocienteRConAux))) 
            def FrenarMedicion():
                t.do_run = False
            botonIniciarMedicion = tk.Button(raiz, text="Iniciar", command=IniciarMedicion,font=(fuente, 20))
            botonIniciarMedicion.place(x=X, y=Y+780, height=40, width=166)
            botonFrenarMedicion = tk.Button(raiz, text="Frenar", command=FrenarMedicion,font=(fuente, 20))
            botonFrenarMedicion.place(x=X, y=Y+820, height=40, width=166)
    
    # Desde este panel se setea el número de constantes de tiempo del LockIn. Al hacerlo también se lee la
    # constante de integración y se guarda en el programa. 
    class PanelSeteoNumeroDeConstantesDeTiempo():
       
        def __init__(self, raiz, posicion, experimento, programa, numeroDeConstantesDeTiempoDefault):
            self.experimento = experimento
            self.programa = programa
            X = posicion[0]
            Y = posicion[1]
            labelTitulo = tk.Label(raiz, text = 'Lock-In ',font=(fuente, 20))
            labelTitulo.place(x=X+15, y=Y+5)
                       
            def Ayuda():
                Advertencia('Información', 'La constante de tiempo se maneja desde el Lock-In manualmente. \n Desde acá se setea cuántas de esas constantes de tiempo\n se debe esperar.  El default de 1 es para esperar el tiempo dado por\n la constante de tiempo. Si se modifica manualmente la constante\n entonces se debe tocar Ok para que quede guardada.')
            botonAyuda = tk.Button(raiz, text="?", command=Ayuda, font=(fuente,15))
            botonAyuda.place(x=X+190, y=Y+10, height=30, width=30)
            
            labelNumeroDeConstantesDeTiempo = tk.Label(raiz, text = '# de ctes: ',font=(fuente, 20))
            labelNumeroDeConstantesDeTiempo.place(x=X+15, y=Y+45)
            textoNumeroDeConstantesDeTiempo = tk.Entry(raiz, font=(fuente,20))
            textoNumeroDeConstantesDeTiempo.place(x=X+20, y=Y+90, height=30, width=70)
            textoNumeroDeConstantesDeTiempo.delete(0, tk.END)
            textoNumeroDeConstantesDeTiempo.insert(0, numeroDeConstantesDeTiempoDefault)
            def SetearNumeroDeConstantesDeTiempo():
                try:
                    numeroDeConstantesDeTiempo = int(textoNumeroDeConstantesDeTiempo.get())
                except ValueError:
                    Advertencia('El valor ingresado debe ser un número entero.')
                self.experimento.lockin.SetearNumeroDeConstantesDeIntegracion(numeroDeConstantesDeTiempo)
                self.programa.GrabarDataNumeroDeConstantesDeTiempo(numeroDeConstantesDeTiempo)
            botonSetearNumeroDeConstantesDeTiempo = tk.Button(raiz, text="Setear", command=SetearNumeroDeConstantesDeTiempo, font=(fuente, 15))
            botonSetearNumeroDeConstantesDeTiempo.place(x=X+120, y=Y+85, height=40, width=100)
    
    class PanelJoggingPlataforma():
        
        def __init__(self, raiz, posicion, experimento):
            self.experimento = experimento
            X = posicion[0]
            Y = posicion[1]
            labelTitulo = tk.Label(raiz, text = 'Plataforma de retardo', font=(fuente,20))
            labelTitulo.place(x=X, y=Y-35)
            def Ayuda():
                Advertencia('Información', 'La plataforma de retardo tiene un rango desde 0 hasta 25 mm y una \n resolución de 0.0001 mm.')
            botonAyuda = tk.Button(raiz, text="?", command=Ayuda, font=(fuente,15))
            botonAyuda.place(x=X+345, y=Y-35, height=30, width=30)
            
            labelPosicionSMC = tk.Label(raiz, text = 'Posicion: ', font=(fuente,20))
            labelPosicionSMC.place(x=X, y=Y+5)
            labelPasoSMC = tk.Label(raiz, text = 'Paso: ', font=(fuente,20))
            labelPasoSMC.place(x=X, y=Y+50)
            self.textoPosicionSMC = tk.Entry(raiz, font=(fuente,20))
            self.textoPosicionSMC.place(x=X+170, y=Y+7, height=35, width=100)
            textoPasoSMC = tk.Entry(raiz, width=5, font=(fuente,20))
            textoPasoSMC.place(x=X+170, y=Y+50, height=35, width=100)
            self.textoPosicionSMC.delete(0, tk.END)
            self.textoPosicionSMC.insert(0, str(self.experimento.smc.posicion))
            textoPasoSMC.delete(0, tk.END)
            textoPasoSMC.insert(0, '1')
            def IrALaPosicionSMC():
                comando = float(self.textoPosicionSMC.get())
                self.experimento.smc.Mover(comando)
            def MoverHaciaAdelante():
                comando = round(float(textoPasoSMC.get()),6)
                comandoMultiploDeLaResolucion = round(self.experimento.smc.resolucion*int(comando/self.experimento.smc.resolucion), 6)
                textoPasoSMC.delete(0, tk.END)
                textoPasoSMC.insert(0, str(comandoMultiploDeLaResolucion)) 
                self.experimento.smc.Mover(comandoMultiploDeLaResolucion+self.experimento.smc.posicion)
                self.Actualizar()
            def MoverHaciaAtras():
                comando = round(float(textoPasoSMC.get()),6)
                comandoMultiploDeLaResolucion = round(self.experimento.smc.resolucion*int(comando/self.experimento.smc.resolucion), 6)
                textoPasoSMC.delete(0, tk.END)
                textoPasoSMC.insert(0, str(comandoMultiploDeLaResolucion)) 
                self.experimento.smc.Mover((-1)*comandoMultiploDeLaResolucion+self.experimento.smc.posicion)
                self.Actualizar()
            botonIrALaPosicionSMC = tk.Button(raiz, text="Mover", command=IrALaPosicionSMC, font=(fuente,15))
            botonIrALaPosicionSMC.place(x=X+285, y=Y, height=40, width=90)
            botonMoverHaciaDelante = tk.Button(raiz, text="+", command=MoverHaciaAdelante, font=(fuente,15))
            botonMoverHaciaDelante.place(x=X+285, y=Y+45, height=40, width=45)
            botonMoverHaciaAtras = tk.Button(raiz, text="-", command=MoverHaciaAtras, font=(fuente,15))
            botonMoverHaciaAtras.place(x=X+330, y=Y+45, height=40, width=45)
    
        def Actualizar(self):
            self.textoPosicionSMC.delete(0, tk.END)
            self.textoPosicionSMC.insert(0, str(self.experimento.smc.posicion))
    
    class PanelJoggingRedDeDifraccion():
        
        def __init__(self, raiz, posicion, experimento):
            self.experimento = experimento
            X = posicion[0]
            Y = posicion[1]
            labelTitulo = tk.Label(raiz, text = 'Red de difracción', font=(fuente,20))
            labelTitulo.place(x=X, y=Y-35)
            def Ayuda():
                Advertencia('Información', 'La red de difracción tiene un rango desde 0 hasta 1200 nm y una \n resolución de 0.3125 nm. La dispersión depende \n fuertemente de la red usada. ')
            botonAyuda = tk.Button(raiz, text="?", command=Ayuda, font=(fuente,15))
            botonAyuda.place(x=X+285, y=Y-35, height=30, width=30)
            
            labelPosicionMonocromador = tk.Label(raiz, text = '\u03BB:', font=(fuente,20))
            labelPosicionMonocromador.place(x=X, y=Y+5)
            labelPasoMonocromador = tk.Label(raiz, text = 'Paso: ', font=(fuente,20))
            labelPasoMonocromador.place(x=X, y=Y+50)
            self.textoPosicionMonocromador = tk.Entry(raiz, width=5, font=(fuente,20))
            self.textoPosicionMonocromador.place(x=X+110, y=Y+7, height=35, width=100)
            textoPasoMonocromador = tk.Entry(raiz, width=5, font=(fuente,20))
            textoPasoMonocromador.place(x=X+110, y=Y+50, height=35, width=100)
            self.textoPosicionMonocromador.delete(0, tk.END)
            self.textoPosicionMonocromador.insert(0, str(self.experimento.mono.posicion))
            textoPasoMonocromador.delete(0, tk.END)
            textoPasoMonocromador.insert(0, '0.9375')
            def IrALaPosicionMonocromador():
                comando = float(self.textoPosicionMonocromador.get())
                self.experimento.mono.Mover(comando)
            def MoverHaciaAdelante():
                comando = float(textoPasoMonocromador.get())
                comandoMultiploDeLaResolucion = self.experimento.mono.resolucion*int(comando/self.experimento.mono.resolucion)
                textoPasoMonocromador.delete(0, tk.END)
                textoPasoMonocromador.insert(0, str(comandoMultiploDeLaResolucion)) 
                self.experimento.mono.Mover(comandoMultiploDeLaResolucion+self.experimento.mono.posicion)
                self.Actualizar()
            def MoverHaciaAtras():
                comando = float(textoPasoMonocromador.get())
                comandoMultiploDeLaResolucion = self.experimento.mono.resolucion*int(comando/self.experimento.mono.resolucion)
                textoPasoMonocromador.delete(0, tk.END)
                textoPasoMonocromador.insert(0, str(comandoMultiploDeLaResolucion)) 
                self.experimento.mono.Mover((-1)*comandoMultiploDeLaResolucion+self.experimento.mono.posicion)
                self.Actualizar()
            botonIrALaPosicionMonocromador = tk.Button(raiz, text="Mover", command=IrALaPosicionMonocromador, font=(fuente,15))
            botonIrALaPosicionMonocromador.place(x=X+225, y=Y, height=40, width=90)
            botonMoverHaciaDelante = tk.Button(raiz, text="+", command=MoverHaciaAdelante, font=(fuente,15))
            botonMoverHaciaDelante.place(x=X+225, y=Y+45, height=40, width=45)
            botonMoverHaciaAtras = tk.Button(raiz, text="-", command=MoverHaciaAtras, font=(fuente,15))
            botonMoverHaciaAtras.place(x=X+270, y=Y+45, height=40, width=45)   
        
        def Actualizar(self):
            self.textoPosicionMonocromador.delete(0, tk.END)
            self.textoPosicionMonocromador.insert(0, str(self.experimento.mono.posicion))
    
    class PanelBarridoEnDistancia():
    
        def __init__(self, raiz, posicion, experimento):
            self.experimento = experimento
            X = posicion[0] #950
            Y = posicion[1]#140
            labelTituloInicial = tk.Label(raiz, text="Barrido en distancia", font=(fuente,20))
            labelTituloInicial.place(x=X, y=Y)        
        
            labelNumeroDeSubintervalos = tk.Label(raiz, text="Secciones: ", font=(fuente,15))
            labelNumeroDeSubintervalos.place(x=X, y=Y+50)
            textoNumeroDeSubintervalos = tk.Entry(raiz, font=(fuente,15))
            textoNumeroDeSubintervalos.place(x=X+130, y=Y+45, height=35, width=40)
            textoNumeroDeSubintervalos.delete(0, tk.END)
            textoNumeroDeSubintervalos.insert(0, '5')        
        
            labelTituloInicial = tk.Label(raiz, text="Pos. Inicial", font=(fuente,10))
            labelTituloInicial.place(x=X, y=Y+100)
            labelTituloFinal = tk.Label(raiz, text="Pos. Final", font=(fuente,10))
            labelTituloFinal.place(x=X+125, y=Y+100)
            labelTituloPaso = tk.Label(raiz, text="Paso", font=(fuente,10))
            labelTituloPaso.place(x=X+250, y=Y+100)
            
            self.textosPosicionInicial = list()
            self.textosPosicionFinal = list()
            self.textosPaso = list()
            
            def ObtenerSecciones():
                for i in range(0,len(self.textosPosicionInicial)):
                    self.textosPosicionInicial[i].destroy()
                    self.textosPosicionFinal[i].destroy()
                    self.textosPaso[i].destroy()
                self.textosPosicionInicial.clear()
                self.textosPosicionFinal.clear()
                self.textosPaso.clear()
                self.numeroDeSubintervalos = int(textoNumeroDeSubintervalos.get())
                for i in range(0,self.numeroDeSubintervalos):
                    self.textosPosicionInicial.append(tk.Entry(raiz, font=(fuente,15)))
                    self.textosPosicionFinal.append(tk.Entry(raiz, font=(fuente,15)))
                    self.textosPaso.append(tk.Entry(raiz, font=(fuente,15)))
                    self.textosPosicionInicial[i].place(x=X, y=Y+130+i*30, height=30, width=115)
                    self.textosPosicionFinal[i].place(x=X+125, y=Y+130+i*30, height=30, width=115)
                    self.textosPaso[i].place(x=X+250, y=Y+130+i*30, height=30, width=115)
                
            ObtenerSecciones()    
            botonSiguiente = tk.Button(raiz, text="Ok", command=ObtenerSecciones, font=(fuente,15))
            botonSiguiente.place(x=X+180, y=Y+40, height=40, width=40)
        
        def ChequearResolucionDeLosValores(self):
            for i in range(0,len(self.textosPaso)):
                if self.textosPaso[i].get() != '':
                    valor = Decimal(self.textosPaso[i].get())
                    resto = valor%Decimal(str(self.experimento.smc.resolucion))
                    if resto != 0:
                        if resto < (self.experimento.smc.resolucion/2):
                            valorMultiploDeLaResolucion = round(self.experimento.smc.resolucion*int(round(valor/Decimal(str(self.experimento.smc.resolucion)), 6)), 6)
                        if resto > (self.experimento.smc.resolucion/2):
                            valorMultiploDeLaResolucion = round(self.experimento.smc.resolucion*int(round(valor/Decimal(str(self.experimento.smc.resolucion)), 6)), 6) + self.experimento.smc.resolucion
                        if valorMultiploDeLaResolucion == 0:
                            valorMultiploDeLaResolucion = self.experimento.smc.resolucion
                        self.textosPaso[i].delete(0, tk.END)
                        self.textosPaso[i].insert(0, str(valorMultiploDeLaResolucion))
    
        def ObtenerValores(self):
            self.ChequearResolucionDeLosValores()
            VectorPosicionInicialSMC_mm = list()
            VectorPosicionFinalSMC_mm = list()
            VectorPasoSMC_mm = list()
            for i in range(0,self.numeroDeSubintervalos):
                if self.textosPosicionInicial[i].get() != '' and self.textosPosicionFinal[i].get() != '' and self.textosPaso[i].get() != '':
                    VectorPosicionInicialSMC_mm.append(float(self.textosPosicionInicial[i].get()))
                    VectorPosicionFinalSMC_mm.append(float(self.textosPosicionFinal[i].get()))
                    VectorPasoSMC_mm.append(float(self.textosPaso[i].get()))            
            return (VectorPosicionInicialSMC_mm, VectorPosicionFinalSMC_mm, VectorPasoSMC_mm)
    
    class PanelBarridoEnLongitudesDeOnda():
        
        def __init__(self, raiz, posicion, experimento):
            self.experimento = experimento
            X = posicion[0]
            Y = posicion[1]
            
            labelTituloBarridoLongitudDeOnda = tk.Label(raiz, text="Barrido en \u03BB", font=(fuente,20))
            labelTituloBarridoLongitudDeOnda.place(x=X, y=Y)
            labelNumeroDeSubintervalosLongitudDeOnda = tk.Label(raiz, text="Secciones: ", font=(fuente,15))
            labelNumeroDeSubintervalosLongitudDeOnda.place(x=X, y=Y+50)
            textoNumeroDeSubintervalosLongitudDeOnda = tk.Entry(raiz, font=(fuente,15))
            textoNumeroDeSubintervalosLongitudDeOnda.place(x=X+130, y=Y+45, height=35, width=40)
            textoNumeroDeSubintervalosLongitudDeOnda.delete(0, tk.END)
            textoNumeroDeSubintervalosLongitudDeOnda.insert(0, '5')        

            labelTituloLongitudDeOndaInicial = tk.Label(raiz, text="\u03BB Inicial", font=(fuente,10))
            labelTituloLongitudDeOndaInicial.place(x=X, y=Y+100)
            labelTituloLongitudDeOndaFinal = tk.Label(raiz, text="\u03BB Final", font=(fuente,10))
            labelTituloLongitudDeOndaFinal.place(x=X+125, y=Y+100)
            labelTituloPasoLongitudDeOnda = tk.Label(raiz, text="Paso", font=(fuente,10))
            labelTituloPasoLongitudDeOnda.place(x=X+250, y=Y+100)
   
            self.textosLongitudDeOndaInicial = list()
            self.textosLongitudDeOndaFinal = list()
            self.textosPasoLongitudDeOnda = list()
        
            def ObtenerSeccionesBarridoEnLongitudDeOnda():
                for i in range(0,len(self.textosLongitudDeOndaInicial)):
                    self.textosLongitudDeOndaInicial[i].destroy()
                    self.textosLongitudDeOndaFinal[i].destroy()
                    self.textosPasoLongitudDeOnda[i].destroy()
                self.textosLongitudDeOndaInicial.clear()
                self.textosLongitudDeOndaFinal.clear()
                self.textosPasoLongitudDeOnda.clear()
                self.numeroDeSubintervalosLongitudDeOnda = int(textoNumeroDeSubintervalosLongitudDeOnda.get())
                for i in range(0,self.numeroDeSubintervalosLongitudDeOnda):
                    self.textosLongitudDeOndaInicial.append(tk.Entry(raiz,width=15, font=(fuente,15)))
                    self.textosLongitudDeOndaFinal.append(tk.Entry(raiz,width=15, font=(fuente,15)))
                    self.textosPasoLongitudDeOnda.append(tk.Entry(raiz,width=15, font=(fuente,15)))
                    self.textosLongitudDeOndaInicial[i].place(x=X, y=Y+130+i*30, height=30, width=115)
                    self.textosLongitudDeOndaFinal[i].place(x=X+125, y=Y+130+i*30, height=30, width=115)
                    self.textosPasoLongitudDeOnda[i].place(x=X+250, y=Y+130+i*30, height=30, width=115)
            botonSeccionesLongitudDeOnda = tk.Button(raiz, text="Ok", command=ObtenerSeccionesBarridoEnLongitudDeOnda, font=(fuente,15))
            botonSeccionesLongitudDeOnda.place(x=X+180, y=Y+40, height=40, width=40)
            ObtenerSeccionesBarridoEnLongitudDeOnda()
        
        def ChequearResolucionDeLosValores(self):
            for i in range(0,len(self.textosPasoLongitudDeOnda)):
                if self.textosPasoLongitudDeOnda[i].get() != '':
                    valor = Decimal(self.textosPasoLongitudDeOnda[i].get())
                    resto = valor%Decimal(str(self.experimento.mono.resolucion))
                    if resto != 0:
                        if resto < (self.experimento.mono.resolucion/2):
                            valorMultiploDeLaResolucion = round(self.experimento.mono.resolucion*int(round(valor/Decimal(str(self.experimento.mono.resolucion)), 6)), 6)
                        if resto > (self.experimento.mono.resolucion/2):
                            valorMultiploDeLaResolucion = round(self.experimento.mono.resolucion*int(round(valor/Decimal(str(self.experimento.mono.resolucion)), 6)), 6) + self.experimento.mono.resolucion
                        if valorMultiploDeLaResolucion == 0:
                            valorMultiploDeLaResolucion = self.experimento.mono.resolucion
                        self.textosPasoLongitudDeOnda[i].delete(0, tk.END)
                        self.textosPasoLongitudDeOnda[i].insert(0, str(valorMultiploDeLaResolucion))
    
        def ObtenerValores(self):
            self.ChequearResolucionDeLosValores()
            VectorLongitudDeOndaInicial_nm = list()
            VectorLongitudDeOndaFinal_nm = list()
            VectorPasoMono_nm = list()
            for i in range(0,self.numeroDeSubintervalosLongitudDeOnda):
                if self.textosLongitudDeOndaInicial[i].get() != '' and self.textosLongitudDeOndaFinal[i].get() != '' and self.textosPasoLongitudDeOnda[i].get() != '':
                    VectorLongitudDeOndaInicial_nm.append(float(self.textosLongitudDeOndaInicial[i].get()))
                    VectorLongitudDeOndaFinal_nm.append(float(self.textosLongitudDeOndaFinal[i].get()))
                    VectorPasoMono_nm.append(float(self.textosPasoLongitudDeOnda[i].get()))
            return (VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm)

    def PantallaPrincipal(self):
        self.raiz = tk.Tk()
        self.raiz.title('Pump and Probe Software')
        ws, hs = self.raiz.winfo_screenwidth(), self.raiz.winfo_screenheight()
        self.raiz.geometry('%dx%d+0+0' % (ws, hs))#'1450x825' Notebook #'1920x1080' Mi compu de escritorio #'' Laboratorio
        self.raiz.state('zoomed')   
        #raiz.config(background='grey')

        # GRAFICO #
        self.grafico = Grafico()
        canvasRecuadros = Canvas(self.raiz, width=ws, height=hs)
        canvasRecuadros.create_line(10, 8, 400, 8, 400, 135, 10, 135, 10, 8)
        canvasRecuadros.create_line(405, 8, 735, 8, 735, 135, 405, 135, 405, 8)
        canvasRecuadros.create_line(740, 8, 1075, 8, 1075, 135, 740, 135, 740, 8)
        canvasRecuadros.create_line(1080, 8, 1305, 8, 1305, 135, 1080, 135, 1080, 8)
        
        canvasRecuadros.create_line(1310, 350, 1710, 350, dash=(5,5)) 
        canvasRecuadros.create_line(1310, 693, 1710, 693, dash=(5,5)) 
        canvasRecuadros.create_line(1310, 738, 1710, 738, dash=(5,5)) 
        canvasRecuadros.create_line(1710, 8, 1710, 300)
        canvasRecuadros.create_rectangle(1310, 8, 1710, 1005) #fill="#fb0"
        canvasRecuadros.create_rectangle(1720, 115, 1915, 1005)
        canvasRecuadros.pack(fill=BOTH)

        canvas = FigureCanvasTkAgg(self.grafico.fig, master=self.raiz)
        canvas.get_tk_widget().place(x=10,y=142)
        canvas.draw()
        
        # PANEL JOGGING DE LA PLATAFORMA #
        self.panelJoggingPlataforma = self.PanelJoggingPlataforma(self.raiz, (15, 45), self.experimento)
        
        # PANEL JOGGING DE LA RED DE DIFRACCION #
        self.panelJoggingRedDeDifraccion = self.PanelJoggingRedDeDifraccion(self.raiz, (410, 45), self.experimento)
        
        # PANEL CONVERSOR #
        self.panelConversor = self.PanelConversor(self.raiz, (625,73))
               
        # PANEL SETEO DE NUMERO DE CONSTANTES DE TIEMPO DEL LOCK IN #        
        self.panelSeteoNumeroDeConstantesDeTiempo = self.PanelSeteoNumeroDeConstantesDeTiempo(self.raiz, (1070, 5), self.experimento, self, self.LeerDataNumeroDeConstantesDeTiempo())
        
        # BOTON CONFIGURACION #
        botonConfiguracion = tk.Button(self.raiz, text="Configuración", command=self.configuracion.AbrirVentana, font=(fuente,15))
        botonConfiguracion.place(x=1730, y=5, width=180, heigh=50)
        
        # BOTON SALIR #
        botonSalir = tk.Button(self.raiz, text="Salir", command=self.Salir, font=(fuente,15))
        botonSalir.place(x=1730, y=55, width=180, heigh=50)
        
        # PANEL MEDICION MANUAL #
        self.panelMedicionManual = self.PanelMedicionManual(self.raiz, (1735, 130), self.experimento)
        
        # BARRIDO EN POSICIONES DEL SMC #
        self.panelBarridoEnDistancia = self.PanelBarridoEnDistancia(self.raiz, (1330,10), self.experimento)

        # Esta función es llamada al hacer un barrido en posiciones.
        def MedirALambdaFija():
            VectorPosicionInicialSMC_mm, VectorPosicionFinalSMC_mm, VectorPasoSMC_mm = self.panelBarridoEnDistancia.ObtenerValores()
            self.raiz.update()
            medicion = Medicion()
            tiempoDeMedicion = int(self.CalcularTiempoDeMedicionALambdaFija(VectorPosicionInicialSMC_mm,VectorPosicionFinalSMC_mm,VectorPasoSMC_mm))                
            medicion.IniciarVentana(self, tiempoDeMedicion, 0, self.experimento, VectorPosicionInicialSMC_mm, VectorPosicionFinalSMC_mm, VectorPasoSMC_mm)
        botonMedirALambdaFija = tk.Button(self.raiz, text="Barrer", command=MedirALambdaFija, font=(fuente,15))
        botonMedirALambdaFija.place(x=1580, y=300, height=40, width=115)
    
        #BARRIDO EN LONGITUDES DE ONDA#
        self.panelBarridoEnLongitudesDeOnda = self.PanelBarridoEnLongitudesDeOnda(self.raiz, (1330,360), self.experimento)
        
        # Esta función es llamada al hacer un barrido en longitudes de onda.
        def MedirAPosicionFija():
            VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm = self.panelBarridoEnLongitudesDeOnda.ObtenerValores()
            self.raiz.update()            
            medicion = Medicion()
            tiempoDeMedicion = int(self.CalcularTiempoDeMedicionAPosicionFijaSMC(VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm))
            medicion.IniciarVentana(self, tiempoDeMedicion, 1, self.experimento, VectorLongitudDeOndaInicial_nm=VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm=VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm=VectorPasoMono_nm)
        botonMedirAPosicionFija = tk.Button(self.raiz, text="Barrer", command=MedirAPosicionFija, font=(fuente,15))
        botonMedirAPosicionFija.place(x=1580, y=650, height=40, width=115)
                
        # DOBLE BARRIDO #
        def MedirCompletamente():
            VectorPosicionInicialSMC_mm, VectorPosicionFinalSMC_mm, VectorPasoSMC_mm = self.panelBarridoEnDistancia.ObtenerValores()
            VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm = self.panelBarridoEnLongitudesDeOnda.ObtenerValores()
            self.raiz.update()
            medicion = Medicion()
            tiempoDeMedicion = int(self.CalcularTiempoDeMedicionCompleta(VectorPosicionInicialSMC_mm, VectorPosicionFinalSMC_mm, VectorPasoSMC_mm, VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm))
            medicion.IniciarVentana(self, tiempoDeMedicion, 2, self.experimento, VectorPosicionInicialSMC_mm, VectorPosicionFinalSMC_mm, VectorPasoSMC_mm, VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm)
        botonMedirCompletamente = tk.Button(self.raiz, text="Barrido doble", command=MedirCompletamente, font=(fuente,15))
        botonMedirCompletamente.place(x=1455, y=695, height=40, width=240)
 
        # Lectura de los .txt para configuración de gráfico.
        ejeX, boolXDefault, boolYDefault, boolRDefault, boolTitaDefault, boolXAuxDefault, boolRAuxDefault, segundosAPromediarAuxDefault, boolPromedioAuxDefault, cantidadDeMedicionesARealizarDefault, boolPromedioRepeticionesDefault = self.LeerDataGraficos()  
        
        # PANEL VALORES A GRAFICAR #
        self.panelValoresAGraficar = self.PanelValoresAGraficar(self.raiz, (1320,750), boolXDefault, boolYDefault, boolRDefault, boolTitaDefault, boolXAuxDefault, boolRAuxDefault)

        # PANEL EJE X: TIEMPO O DISTANCIA#
        self.panelEjeX = self.PanelEjeX(self.raiz, (1320,820), ejeX)

        # PANEL NOMBRE ARCHIVO #
        self.panelNombreArchivo = self.PanelNombreArchivo(self.raiz, (1320, 870))
        
        # PANEL PROMEDIAR AUX #
        self.panelPromedioAux = self.PanelPromedioAux(self.raiz, (1320, 915), segundosAPromediarAuxDefault, boolPromedioAuxDefault)

        # PANEL CANTIDAD DE MEDICIONES A REALIZAR #
        self.panelCantidadDeMedicionesARealizar = self.PanelCantidadDeMedicionesARealizar(self.raiz, (1320, 960), cantidadDeMedicionesARealizarDefault)

        # PANEL PROMEDIO DE REPETICIONES #
        self.panelPromedioRepeticiones = self.PanelPromedioRepeticiones(self.raiz, (1600, 960), boolPromedioRepeticionesDefault)


        # PROTOCOLO AL CERRAR PROGRAMA #        

        self.raiz.protocol("WM_DELETE_WINDOW", self.Salir)

        self.raiz.mainloop()
        
    def Salir(self):
        self.experimento.smc.address.close()
        self.experimento.mono.address.close()
        self.raiz.destroy()
    
    def GrabarDataPuertos(self, puertoSMC, puertoSMS, puertoLockIn):
        linea = str(puertoSMC) + ',' + str(puertoSMS) + ',' + str(puertoLockIn)
        with open(RutaEnCarpetaDelCodigo('dataPuertos.txt'), 'w') as f:
            f.write(linea)
        
    def GrabarDataGraficos(self, ejeX, valoresAGraficar, segundosPromedioAux, booleanoPromedioAux, cantidadDeMedicionesARealizar, booleanoPromedioRepeticiones):
        boolX = valoresAGraficar[0]
        boolY = valoresAGraficar[1]
        boolR = valoresAGraficar[2]
        boolTita = valoresAGraficar[3]
        boolXAux = valoresAGraficar[4]
        boolRAux = valoresAGraficar[5]
        linea = str(ejeX) + ',' + str(boolX) + ',' + str(boolY) + ',' + str(boolR) + ',' + str(boolTita) + ',' + str(boolXAux) + ',' + str(boolRAux) + ',' + str(segundosPromedioAux) + ',' + str(booleanoPromedioAux) + ',' + str(cantidadDeMedicionesARealizar) + ',' + str(booleanoPromedioRepeticiones)
        with open(RutaEnCarpetaDelCodigo('dataGraficos.txt'), 'w') as f:
            f.write(linea)
    
    def GrabarDataNumeroDeConstantesDeTiempo(self, numeroDeConstantesDeTiempo):
        linea = str(numeroDeConstantesDeTiempo)
        with open(RutaEnCarpetaDelCodigo('dataNumeroDeConstantesDeTiempo.txt'), 'w') as f:
            f.write(linea)

    def LeerDataPuertos(self):
        with open(RutaEnCarpetaDelCodigo('dataPuertos.txt'), 'r') as f:
            linea = f.readline().strip()
        puertos = linea.split(',')
        if len(puertos) >= 3:
            puertoSMC = puertos[0]
            puertoSMS = puertos[1]
            puertoLockIn = puertos[2]
        elif len(puertos) == 2:
            puertoSMC = ''
            puertoSMS = puertos[0]
            puertoLockIn = puertos[1]
        else:
            puertoSMC = ''
            puertoSMS = ''
            puertoLockIn = ''
        return puertoSMC, puertoSMS, puertoLockIn
    
    def LeerDataGraficos(self):
        with open(RutaEnCarpetaDelCodigo('dataGraficos.txt'), 'r') as f:
            linea = f.readline()
        ejeX = str(linea.split(',')[0])
        boolX = bool(int(linea.split(',')[1]))
        boolY = bool(int(linea.split(',')[2]))
        boolR = bool(int(linea.split(',')[3]))
        boolTita = bool(int(linea.split(',')[4]))
        boolXAux = bool(int(linea.split(',')[5]))
        boolRAux = bool(int(linea.split(',')[6]))
        segundosPromedioAux = str(linea.split(',')[7])
        boolPromedioAux = bool(int(linea.split(',')[8]))
        cantidadDeMedicionesARealizar = str(linea.split(',')[9])
        if len(linea.split(',')) > 10:
            boolPromedioRepeticiones = bool(int(linea.split(',')[10]))
        else:
            boolPromedioRepeticiones = True
        return ejeX, boolX, boolY, boolR, boolTita, boolXAux, boolRAux, segundosPromedioAux, boolPromedioAux, cantidadDeMedicionesARealizar, boolPromedioRepeticiones
    
    def LeerDataNumeroDeConstantesDeTiempo(self):
        with open(RutaEnCarpetaDelCodigo('dataNumeroDeConstantesDeTiempo.txt'), 'r') as f:
            linea = f.readline()
        return linea

    def CalcularTiempoDeMedicionALambdaFija(self,
                                            VectorPosicionInicialSMC_mm,
                                            VectorPosicionFinalSMC_mm,
                                            VectorPasoSMC_mm):
        TiempoDeMedicion = 0
        CantidadDeMedicionesTotal = 0
        TiempoDeDesplazamientoTotal = 0
        TiempoDeDesplazamientoPorPaso = 0
        TiempoMuerto = 0
        TiempoMuerto = abs(VectorPosicionInicialSMC_mm[0]-self.experimento.smc.posicion)/self.experimento.smc.velocidadMmPorSegundo + tiempoAgregadoPlataforma
        for i in range(0, len(VectorPosicionInicialSMC_mm)):
            if i>0 and VectorPosicionInicialSMC_mm[i] != VectorPosicionFinalSMC_mm[i-1]:
                TiempoMuerto = TiempoMuerto + abs(VectorPosicionInicialSMC_mm[i]-VectorPosicionFinalSMC_mm[i-1])/self.experimento.smc.velocidadMmPorSegundo + tiempoAgregadoPlataforma
            CantidadDeMediciones = 0
            CantidadDeMediciones = abs(VectorPosicionFinalSMC_mm[i]-VectorPosicionInicialSMC_mm[i])/VectorPasoSMC_mm[i]
            TiempoDeDesplazamientoPorPaso = VectorPasoSMC_mm[i]/self.experimento.smc.velocidadMmPorSegundo + tiempoAgregadoPlataforma
            TiempoDeDesplazamientoTotal = TiempoDeDesplazamientoTotal + CantidadDeMediciones*TiempoDeDesplazamientoPorPaso
            CantidadDeMedicionesTotal = CantidadDeMedicionesTotal + CantidadDeMediciones
        TiempoDeMedicion = CantidadDeMedicionesTotal*(self.experimento.lockin.TiempoDeIntegracionTotal) + TiempoDeDesplazamientoTotal + TiempoMuerto
        if self.panelPromedioAux.ObtenerPromedioAuxBool():
            TiempoDeMedicion = TiempoDeMedicion + self.panelPromedioAux.ObtenerSegundosAPromediar()
        return TiempoDeMedicion    
    
    def CalcularTiempoDeMedicionAPosicionFijaSMC(self, 
                                                 VectorLongitudDeOndaInicial_nm,
                                                 VectorLongitudDeOndaFinal_nm,
                                                 VectorPasoMono_nm):
        TiempoDeMedicion = 0
        CantidadDeMedicionesTotal = 0
        TiempoDeDesplazamientoTotal = 0
        TiempoDeDesplazamientoPorPaso = 0
        TiempoMuerto = 0
        TiempoMuerto = abs(VectorLongitudDeOndaInicial_nm[0]-self.experimento.mono.posicion)/self.experimento.mono.velocidadNmPorSegundo + tiempoAgregadoMonocromador
        for i in range(0, len(VectorLongitudDeOndaInicial_nm)):
            if i>0 and VectorLongitudDeOndaInicial_nm[i] != VectorLongitudDeOndaFinal_nm[i-1]:
                TiempoMuerto = TiempoMuerto + abs(VectorLongitudDeOndaInicial_nm[i]-VectorLongitudDeOndaFinal_nm[i-1])/self.experimento.mono.velocidadNmPorSegundo + tiempoAgregadoMonocromador
            CantidadDeMediciones = 0
            CantidadDeMediciones = abs(VectorLongitudDeOndaFinal_nm[i]-VectorLongitudDeOndaInicial_nm[i])/VectorPasoMono_nm[i]
            TiempoDeDesplazamientoPorPaso = VectorPasoMono_nm[i]/self.experimento.mono.velocidadNmPorSegundo + tiempoAgregadoMonocromador
            TiempoDeDesplazamientoTotal = TiempoDeDesplazamientoTotal + CantidadDeMediciones*TiempoDeDesplazamientoPorPaso
        TiempoDeMedicion = CantidadDeMedicionesTotal*(self.experimento.lockin.TiempoDeIntegracionTotal) + TiempoDeDesplazamientoTotal + TiempoMuerto
        if self.panelPromedioAux.ObtenerPromedioAuxBool():
            TiempoDeMedicion = TiempoDeMedicion + self.panelPromedioAux.ObtenerSegundosAPromediar()
        return TiempoDeMedicion    
    
    def CalcularTiempoDeMedicionCompleta(self, 
                                         VectorPosicionInicialSMC_mm,
                                         VectorPosicionFinalSMC_mm,
                                         VectorPasoSMC_mm,
                                         VectorLongitudDeOndaInicial_nm,
                                         VectorLongitudDeOndaFinal_nm,
                                         VectorPasoMono_nm):
        CantidadDeMovimientosSMCTotal = 0
        TiempoDeDesplazamientoSMC = 0
        TiempoDeDesplazamientoPorPaso = 0
        TiempoDeDesplazamientoMono = 0
        TiempoMuertoSMC = 0
        TiempoMuertoMono = 0
        CantidadDeMovimientosMonoTotal = 0
        largoVectorSMC = len(VectorPosicionInicialSMC_mm)
        TiempoSMCInicial = abs(VectorPosicionInicialSMC_mm[0]-self.experimento.smc.posicion)/self.experimento.smc.velocidadMmPorSegundo + tiempoAgregadoPlataforma
        TiempoDeRetornoSMC = abs(VectorPosicionFinalSMC_mm[largoVectorSMC-1]-VectorPosicionInicialSMC_mm[0])/self.experimento.smc.velocidadMmPorSegundo + tiempoAgregadoPlataforma
        TiempoMonocromadorInicial = abs(VectorLongitudDeOndaInicial_nm[0]-self.experimento.mono.posicion)/self.experimento.mono.velocidadNmPorSegundo + tiempoAgregadoMonocromador
        for i in range(0, len(VectorPosicionInicialSMC_mm)):
            if i>0 and VectorPosicionInicialSMC_mm[i] != VectorPosicionFinalSMC_mm[i-1]:
                TiempoMuertoSMC = TiempoMuertoSMC + (VectorPosicionInicialSMC_mm[i]-VectorPosicionFinalSMC_mm[i-1])/self.experimento.smc.velocidadMmPorSegundo + tiempoAgregadoPlataforma
            CantidadDeMovimientosSMC = 0
            CantidadDeMovimientosSMC = abs(VectorPosicionFinalSMC_mm[i]-VectorPosicionInicialSMC_mm[i])/VectorPasoSMC_mm[i]
            TiempoDeDesplazamientoPorPaso = VectorPasoSMC_mm[i]/self.experimento.smc.velocidadMmPorSegundo + tiempoAgregadoPlataforma
            TiempoDeDesplazamientoSMC = TiempoDeDesplazamientoSMC + CantidadDeMovimientosSMC*TiempoDeDesplazamientoPorPaso        
        TiempoSMC = TiempoDeDesplazamientoSMC + TiempoSMCInicial + TiempoMuertoSMC + TiempoDeRetornoSMC        
        for j in range(0, len(VectorLongitudDeOndaInicial_nm)):
            if j>0 and VectorLongitudDeOndaInicial_nm[i] != VectorLongitudDeOndaFinal_nm[i-1]:
                TiempoMuertoMono = TiempoMuertoMono + abs(VectorLongitudDeOndaInicial_nm[j]-VectorLongitudDeOndaFinal_nm[j-1])/self.experimento.mono.velocidadNmPorSegundo + tiempoAgregadoMonocromador
            CantidadDeMovimientosMono = 0
            CantidadDeMovimientosMono = abs(VectorLongitudDeOndaFinal_nm[j]-VectorLongitudDeOndaInicial_nm[j])/VectorPasoMono_nm[j]
            CantidadDeMovimientosMonoTotal = CantidadDeMovimientosMonoTotal + CantidadDeMovimientosMono
            TiempoDeDesplazamientoPorPaso = VectorPasoMono_nm[j]/self.experimento.mono.velocidadNmPorSegundo + tiempoAgregadoMonocromador
            TiempoDeDesplazamientoMono = TiempoDeDesplazamientoMono + CantidadDeMovimientosMono*TiempoDeDesplazamientoPorPaso
        TiempoMonocromador = TiempoDeDesplazamientoMono + TiempoMonocromadorInicial + TiempoMuertoMono
        TiempoSMCTotal = TiempoSMC*CantidadDeMovimientosMonoTotal
        TiempoLockIn = CantidadDeMovimientosSMCTotal*CantidadDeMovimientosMonoTotal*(self.experimento.lockin.TiempoDeIntegracionTotal)       
        TiempoTotal = TiempoMonocromador + TiempoSMCTotal + TiempoLockIn        
        if self.panelPromedioAux.ObtenerPromedioAuxBool():
            TiempoTotal = TiempoTotal + self.panelPromedioAux.ObtenerSegundosAPromediar()
        return TiempoTotal
    
    
# Todo el código que está por encima de esta línea son clases. No hay instancias creadas de las clases, solo 
# sus definiciones. El programa se ejecuta cuando se llama a la línea "programa = Programa()" de aquí abajo.
# Ahí se crea un objeto de la clase Programa que posee en su interior a un objeto de la clase Configuración, un 
# objeto de la clase Experimento y un objeto de la clase Grafico. El objeto de la clase Medicion se crea en cada
# medición y lo mismo pasa con las Advertencias: se crean en cada Advertencia. Dentro del objeto experimento 
# que se encuentra dentro del objeto programa, hay un objeto de la clase SMC, otro de la clase SMS y otro de la 
# clase LockIn. Además el objeto experimento posee un puntero de referencia al mismo objeto grafico creado en el 
# objeto programa.

# Este protocolo no sé si tiene sentido...
if __name__ == "__main__":
    programa = Programa()
