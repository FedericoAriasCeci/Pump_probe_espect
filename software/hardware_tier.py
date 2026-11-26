# PAQUETES IMPORTADOS Y USADOS EN EL CÓDIGO: 
# Kinesis (pythonnet/clr) es para el controlador BBD301 de la plataforma.
# Pyvisa es para la comunicación GPIB con el lock in.
# El espectrómetro HORIBA iHR320 se controla por ICL en horiba_monochromator.py.
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

import pyvisa
from sr830_timing import query_filter_settings, time_constant_seconds, settling_seconds
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
global resolucionBBD
resolucionBBD_mm = 0.0001 # En mm. Es decir, una resolución de 0.1 micrómetro. Esta resolución es inmodificable.
global fuente
fuente = "Helvetica"
        
# OBS: En el código se usa BBD y plataforma para referirse a lo mismo. ``SMS`` y ``mono`` se refieren al
# monocromador, hoy el HORIBA iHR320 (el nombre SMS se conserva en logic_tier.py).


# El BBD301 es el controlador de la plataforma de retardo (la plataforma la mueve un tornillo micrométrico llamado
# TRAPPD25). El controlador está conectado a la PC por un USB que simula un puerto
# serie RS-232. Hay un driver (que se instala automáticamente) que hace que se vea directamente el puerto serie
# sin ver el USB. En la clase de aquí abajo se abre este puerto serie (no se maneja el USB, digamos).



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
                self.posicion = float(str(self.channel.Position))
                self.homed = bool(self.channel.Status.IsHomed)
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
                 self.posicion = float(str(self.channel.Position))
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

    def CalcularTiempoSleep(self, PosicionPlat_mm):
        # MoveTo(..., timeout) already waits for completion. Keep only the
        # existing mechanical margin, without counting the travel time twice.
        return tiempoAgregadoPlataforma if PosicionPlat_mm != self.posicion else 0.0


    def Cerrar(self): 
        self.channel.StopPolling()
        self.bbd301.Disconnect()
        self.connected = False
        

# logic_tier.py instancia ``SMS()``: es el HORIBA iHR320 controlado por ICL (EzSpec-SDK).
from horiba_monochromator import HoribaMonochromator as SMS
        
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
        # Preserve the slope chosen on the SR830; acquisition queries OFSL?.
        self.address.write("SYNC0") #Synchronous Filter off=0 or on below 200hz=1
        time.sleep(0.2)
        self.address.write("OVRM1") #Setea Remote Control Override en on=1, off=0
        time.sleep(0.2)
        self.address.write("LOCL0") #Setea control en Local=0, Remote=1, Remote Lockout=2
        time.sleep(0.2)
        self.SetearNumeroDeConstantesDeIntegracion(1)

    def ConstanteDeIntegracion(self): # Le pregunta la constante de integración al Lock In.
        return time_constant_seconds(self.address.query("OFLT?"))

    def ConsultarFiltro(self):
        return query_filter_settings(self.address)

    def SetearNumeroDeConstantesDeIntegracion(self, numeroDeConstantesDeTiempo): # El número de constantes de tiempo
        # es un número por el que se multiplica la constate de tiempo del lock in para tener mayor libertad.
        self.numeroDeConstantesDeTiempo = numeroDeConstantesDeTiempo
        self.TiempoDeIntegracionTotal = self.CalcularTiempoDeIntegracion()

    def CalcularTiempoDeIntegracion(self): 
        constanteDeIntegracion = self.ConstanteDeIntegracion()
        TiempoDeIntegracionTotal = settling_seconds(self.numeroDeConstantesDeTiempo, constanteDeIntegracion)
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




