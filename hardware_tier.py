# PAQUETES IMPORTADOS Y USADOS EN EL CÓDIGO: 
# Pyserial es para la comunicación serial con el BBD y el SMS
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
import pyvisa
import time
from decimal import Decimal
import os # os_exit(00) restartea el núcleo.
import sys
import clr
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter
from mpl_toolkits.axes_grid1 import make_axes_locatable
import csv
from datetime import date
import datetime

from decimal import Decimal
import tkinter as tk
import tkinter.font as font
from tkinter import Canvas, BOTH
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import threading as th
from datetime import date
import datetime





#Import classes ddl references
clr.AddReference("C:\\Program Files\\Thorlabs\\Kinesis\\Thorlabs.MotionControl.DeviceManagerCLI.dll")
clr.AddReference("C:\\Program Files\\Thorlabs\\Kinesis\\Thorlabs.MotionControl.GenericMotorCLI.dll")
clr.AddReference("C:\\Program Files\\Thorlabs\\Kinesis\\ThorLabs.MotionControl.Benchtop.BrushlessMotorCLI.dll")
from Thorlabs.MotionControl.DeviceManagerCLI import DeviceManagerCLI
from Thorlabs.MotionControl.GenericMotorCLI import *
from Thorlabs.MotionControl.Benchtop.BrushlessMotorCLI import BenchtopBrushlessMotor
from System import Decimal  # necessary for real world units


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
global posicionExtremaBBD
posicionExtremaBBD = 220 # Es una variable global que es 0 o 25 dependiendo si se quiere que un extremo del 
                        # recorrido sea la posición cero, o si se quiere que el otro extremo del recorrido
                        # sea la posición cero. Es para invertir el recorrido de la plataforma.
global velocidadBBD_mmPorSegundo # Es la que tiene seteada el BBD. Se puede leer y modificar. Falta probar el código.
velocidadBBD_mmPorSegundo = 100
global velocidadSMS_nmPorSegundo # Calculada a mano con un cronómetro. Se podría leer y modificar. Falta probar el 
velocidadSMS_nmPorSegundo = 9    # código. La variable que se puede modificar es un valor inverso de la velocidad.
global resolucionBBD
resolucionBBD_mm = 0.0001 # En mm. Es decir, una resolución de 0.1 micrómetro. Esta resolución es inmodificable.
global resolucionSMS
resolucionSMS_nm = 0.3125 # en nm. Es para la red de 1200. OBS: De acuerdo al manual la resolución debería ser de
global offsetSMS          # 0.03125 (la inversa de 32, que es el multiplicador). Sin embargo, en la hoja de internet
                          # del fabricante dice que la resolución es de 0.3125. Creo que el motor no funciona dando
                          # los pasos mínimos. Quizás sí, y la resolución es de 0.03125. Se puede probar..
offsetSMS = -87.0 # Es el 9913 que muestra el visor al calibrar el monocromador
global fuente
fuente = "Helvetica"
        
# OBS: En el código se usa BBD y plataforma para referirse a lo mismo. Lo mismo pasa con el SMS y el monocromador.


# El BBD301 es el controlador de la plataforma de retardo (la plataforma la mueve un tornillo micrométrico llamado
# TRAPPD25). El controlador está conectado a la PC por un USB que simula un puerto
# serie RS-232. Hay un driver (que se instala automáticamente) que hace que se vea directamente el puerto serie
# sin ver el USB. En la clase de aquí abajo se abre este puerto serie (no se maneja el USB, digamos).



#%%%
        
# El SMS LambdaScan es el controlador del Monocromador (o espectrómetro). Está conectado a la PC via un cable USB
# que simula un puerto serie RS-232. Al controlador le falta un circuito integrado que se quemó (el del motor 1).
# Hablar con Maxi si ocurre alguna falla eléctrica, pero viene funcionando joya.
# Hay dos redes de difracción, una de 1200 ranuras por mm y otra creemos de 600 ranuras por mm. La calibración fue 
# hecha a "mano", sin una alineación muy fina, así que puede estar pifiada hasta por 5 nm masomenos.     

class BBD301:
    def __init__(self):
        self.acceleration = 1000
        self.homed = False
        self.connected = False
        self.resolucion = resolucionBBD_mm # Se le asigna la variable global.
        self.posicion = posicionExtremaBBD # Esto es 0 o 25 dependiendo si se quiere barrer en un sentido o 
                                       # en el otro. Al configurar se lee la posición.
        self.velocidadMmPorSegundo = velocidadBBD_mmPorSegundo # Es la variable global. Se puede descomentar y probar
                                                               # el código para leer y modificar la velocidad.

        
    def Conectar(self):
        try:
            DeviceManagerCLI.BuildDeviceList()
            
            # create new device
            serial_no = "103335944"  # Replace this line with your device's serial number
            
            # Connect and retrieve a channel
            self.bbd301 = BenchtopBrushlessMotor.CreateBenchtopBrushlessMotor(serial_no)
            
            if not self.bbd301==None:
                self.bbd301.Connect(serial_no)
                
                self.channel = self.bbd301.GetChannel(1)
                 
                # Ensure that the device settings have been initialized
                if not self.channel.IsSettingsInitialized():
                    self.channel.WaitForSettingsInitialized(10000)  # 10 second timeout
                    assert self.channel.IsSettingsInitialized() is True
                
                # Start polling and enable
                self.channel.StartPolling(250)  #250ms polling rate. Instructs K-Cube to send updates about position and motor status to the PC. 
                time.sleep(25) #Wait to allow the controller to update. 
                self.channel.EnableDevice() 
                time.sleep(0.25)  # Wait for device to enable
                
                # Get Device Information and display description
                device_info = self.channel.GetDeviceInfo()
                print(device_info.Description)
                
                # Load any configuration settings needed by the controller/stage
                   
                motor_config = self.channel.LoadMotorConfiguration(self.channel.DeviceID)  # Device ID is the serial no + channel
                print(self.channel.DeviceID)
                device_settings = self.channel.MotorDeviceSettings
                self.connected = True
                print(self.connected)
                #channel.UpdateConfiguration()
                                                                  
                #channel.SetSettings(device_settings)
        except Exception:
            print("El dispositivo no está listo para conectarse")
            
            
    def Home(self):
        # Get parameters related to homing/zeroing/other
        if self.connected: 
            home_params = self.channel.GetHomingParams()
            print('Homing Velocity: {0}\n'.format(home_params.Velocity),
                'Homing Direction: {0}'.format(home_params.Direction))
            
            self.channel.SetHomingParams(home_params)  # If changes are made

            try:
                 # Home or Zero the device (if a motor/piezo)
                 print("Homing Channel")
                 self.channel.Home(60000)  # 60 second timeout
                 print("Channel Homed")
                 self.homed = True
                 print(self.homed)
                 
            except Exception:  # You shouldn't use a bare except:
                self.Cerrar()
                print("El homing no pudo realizarse")
         
    
    def Mover(self, PosicionPlat_mm): 
        new_pos = Decimal(PosicionPlat_mm)  # in real units
        print('Moving to {0}'.format(new_pos))
        self.channel.MoveTo(new_pos, 60000)
        self.posicion = PosicionPlat_mm
        vel_params = self.channel.GetVelocityParams()
        print(vel_params.MaxVelocity)
        print(vel_params.Acceleration)
        
    def Detener(self):
        if not self.connected:
            return
        try:
            self.channel.StopImmediate()
            print("BBD301 detenido")
            return
        except Exception:
            pass
        try:
            self.channel.Stop(60000)
            print("BBD301 detenido")
        except Exception:
            print("No se pudo detener el BBD301 desde el codigo")
        
        
    def LeerVelocidad(self): # Devuelve una velocidad en mm por segundo.
        valor = -1
        while valor == -1:
            vel_params= self.channel.GetVelocityParams()
        return vel_params.MaxVelocity
    
    def CambiarVelocidad(self, velocidad): # En mm por segundo también.
        max_vel = 290
        if not velocidad>max_vel:
            self.channel.SetVelocityParams(Decimal(velocidad), Decimal(self.acceleration))
            self.velocidadMmPorSegundo = velocidad
        else: 
            print("La velocidad ingresada supera la máxima permitida.")

    def LeerPosicion(self): # Devuelve la posición en mm.
        valor = -1
        while valor == -1:
            self.channel.DevicePosition
            return 

    def CalcularTiempoSleep(self, PosicionPlat_mm): # El código deja de ejecutarse hasta que el SMC se mueva.
                                                   # Hay un tiempo agregado que podría reducirse/quitarse.
        TiempoBBD = 0
        if (PosicionPlat_mm-self.posicion) == 0:
            time.sleep(0.1)
        else:
            TiempoBBD = abs(PosicionPlat_mm-self.posicion)/self.velocidadMmPorSegundo + tiempoAgregadoPlataforma
        return TiempoBBD


    def Cerrar(self): 
        self.channel.StopPolling()
        self.bbd301.Disconnect()
        self.connected = False
        

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
        self.address.write("OFSL0") #Setea Low Pass Filter Slope en 0=6, 1=12, 2=18 y 3=24 DB/octava
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
        a = self.address.query("SNAP?1,2,3,4,5,9") # X,Y,R,THETA,AUX1,FREC
        a = a.replace('\n','')
        return a




