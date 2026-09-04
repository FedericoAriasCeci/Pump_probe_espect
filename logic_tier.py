from hardware_tier import* 
from acquisition_utils import AcquisitionDataManager, add_suffix_to_filename


CARPETA_CODIGO = os.path.dirname(os.path.abspath(__file__))


def RutaEnCarpetaDelCodigo(nombre):
    return os.path.join(CARPETA_CODIGO, nombre)


def VerificarDataManagerActualizado(data_manager):
    metodos_necesarios = [
        "begin_memory_run",
        "finish_run",
        "save_runs",
        "calculate_average",
        "save_average",
        "append_row",
    ]
    faltantes = list()
    for metodo in metodos_necesarios:
        if not hasattr(data_manager, metodo):
            faltantes.append(metodo)
    if len(faltantes) > 0:
        raise RuntimeError(
            "acquisition_utils.py esta desactualizado. "
            + "Copiar tambien el acquisition_utils.py nuevo a la misma carpeta que gui_tomas.py. "
            + "Metodos faltantes: "
            + ", ".join(faltantes)
        )

#%%%

# Esta clase hace las iteraciones para los barridos: manda las órdenes para mover la plataforma, la red y adquiere
# del LockIn. También desarma el string del Lock In para devolver un vector de strings.
# Posee adentro una instancia de la clase BBD, una de SMS, una de LockIn y una de Grafico. Es el corazón de la medi-
# ción. Se encarga de llamar a la clase Grafico e ir armando los gráficos, como también ir grabando el CSV.

class Experimento(): 

    def __init__(self):
        self.bbd = BBD301()
        self.mono = SMS()
        self.lockin = LockIn()
        self.data_manager = AcquisitionDataManager(RutaEnCarpetaDelCodigo("CSVs"))
        self.cancelarMedicion = False
        self.actualizarInterfazDuranteEspera = None

    def IniciarMedicion(self):
        self.cancelarMedicion = False

    def CancelarMedicion(self):
        self.cancelarMedicion = True
        try:
            self.bbd.Detener()
        except Exception:
            pass

    def MedicionCancelada(self):
        return self.cancelarMedicion

    def SetearActualizadorInterfaz(self, callback):
        self.actualizarInterfazDuranteEspera = callback

    def ActualizarInterfazDuranteEspera(self):
        if self.actualizarInterfazDuranteEspera is not None:
            try:
                self.actualizarInterfazDuranteEspera()
            except Exception:
                pass

    def EsperarSiSigue(self, segundos):
        if segundos < 0:
            segundos = 0
        tiempoFinal = time.time() + segundos
        while time.time() < tiempoFinal:
            if self.MedicionCancelada():
                return False
            self.ActualizarInterfazDuranteEspera()
            restante = tiempoFinal - time.time()
            if restante > 0.1:
                time.sleep(0.1)
            elif restante > 0:
                time.sleep(restante)
        self.ActualizarInterfazDuranteEspera()
        return not self.MedicionCancelada()

    def MedicionALambdaFija(self,
                            nombreArchivo,
                            VectorPosicionInicialBBD_mm,
                            VectorPosicionFinalBBD_mm,
                            VectorPasoBBD_mm):
        self.nombreArchivo = nombreArchivo
        for i in range(0,len(VectorPosicionInicialBBD_mm)): # Este loop es sobre la cantidad de "Secciones": 1 a 5.
            if self.MedicionCancelada():
                return
            tiempoDeSleep = self.bbd.CalcularTiempoSleep(VectorPosicionInicialBBD_mm[i])
            self.bbd.Mover(VectorPosicionInicialBBD_mm[i])
            if not self.EsperarSiSigue(tiempoDeSleep):
                return
            if i==0: # Esto lo hace siempre. Es medir la primera posición de todo el barrido.
                self.AdquirirGraficarYGrabarCSV()
            if i>0 and VectorPosicionInicialBBD_mm[i] != VectorPosicionFinalBBD_mm[i-1]: # Esto es para evitar que
                # se mida dos veces si uno superpone los extremos de las secciones.
                self.AdquirirGraficarYGrabarCSV()
            numeroDePasos = abs(int(round((VectorPosicionFinalBBD_mm[i]-VectorPosicionInicialBBD_mm[i])/VectorPasoBBD_mm[i], 6)))
            print(numeroDePasos) # Es el número de pasos en cada Sección. Es para ver que no haya errores
            # de redondeo.
            for j in range(0,numeroDePasos): 
                if self.MedicionCancelada():
                    return
                tiempoDeSleep = self.bbd.CalcularTiempoSleep(VectorPasoBBD_mm[i]+self.bbd.posicion)
                self.bbd.Mover(VectorPasoBBD_mm[i]+self.bbd.posicion)
                if not self.EsperarSiSigue(tiempoDeSleep):
                    return
                self.AdquirirGraficarYGrabarCSV()

    def MedicionAPosicionFijaBBD(self,
                            nombreArchivo,
                            VectorLongitudDeOndaInicial_nm,
                            VectorLongitudDeOndaFinal_nm,
                            VectorPasoMono_nm):
        self.nombreArchivo = nombreArchivo
        for i in range(0,len(VectorLongitudDeOndaInicial_nm)): # Loop sobre la cantidad de "Secciones".
            if self.MedicionCancelada():
                return
            tiempoDeSleep = self.mono.CalcularTiempoSleep(VectorLongitudDeOndaInicial_nm[i])
            self.mono.Mover(VectorLongitudDeOndaInicial_nm[i])
            if not self.EsperarSiSigue(tiempoDeSleep):
                return
            if i==0: # Idem MediciónALambdaFija
                self.AdquirirGraficarYGrabarCSV()
            if i>0 and VectorLongitudDeOndaInicial_nm[i] != VectorLongitudDeOndaFinal_nm[i-1]:
                self.AdquirirGraficarYGrabarCSV()
            numeroDePasos = abs(int(round((VectorLongitudDeOndaFinal_nm[i]-VectorLongitudDeOndaInicial_nm[i])/VectorPasoMono_nm[i], 6)))
            for j in range(0,numeroDePasos):
                if self.MedicionCancelada():
                    return
                tiempoDeSleep = self.mono.CalcularTiempoSleep(round(VectorPasoMono_nm[i]+self.mono.posicion,4))
                self.mono.Mover(round(VectorPasoMono_nm[i]+self.mono.posicion,4))
                if not self.EsperarSiSigue(tiempoDeSleep):
                    return
                self.AdquirirGraficarYGrabarCSV()

    def MedicionCompleta(self, 
                         nombreArchivo,
                         VectorPosicionInicialBBD_mm,
                         VectorPosicionFinalBBD_mm,
                         VectorPasoBBD_mm,
                         VectorLongitudDeOndaInicial_nm,
                         VectorLongitudDeOndaFinal_nm,
                         VectorPasoMono_nm):
        self.nombreArchivo = nombreArchivo
        for i in range(0,len(VectorLongitudDeOndaInicial_nm)): # Loop sobre la cantidad de "Secciones" de lambdas.
            if self.MedicionCancelada():
                return
            tiempoDeSleep = self.mono.CalcularTiempoSleep(VectorLongitudDeOndaInicial_nm[i])
            self.mono.Mover(VectorLongitudDeOndaInicial_nm[i])
            if not self.EsperarSiSigue(tiempoDeSleep):
                return
            numeroDePasosMono = abs(int(round((VectorLongitudDeOndaFinal_nm[i]-VectorLongitudDeOndaInicial_nm[i])/VectorPasoMono_nm[i], 6)))
            for j in range(0,numeroDePasosMono+1): # Hace el barrido de cada sección del monocromador.
                if self.MedicionCancelada():
                    return
                for k in range(0,len(VectorPosicionInicialBBD_mm)): # Loop sobre la cantidad de "Secciones" de la plataforma.
                    if self.MedicionCancelada():
                        return
                    tiempoDeSleep = self.bbd.CalcularTiempoSleep(VectorPosicionInicialBBD_mm[k])
                    self.bbd.Mover(VectorPosicionInicialBBD_mm[k])
                    if not self.EsperarSiSigue(tiempoDeSleep):
                        return
                    if k==0:
                        self.AdquirirGraficarYGrabarCSV()
                    if k>0 and VectorPosicionInicialBBD_mm[k] != VectorPosicionFinalBBD_mm[k-1]:
                        self.AdquirirGraficarYGrabarCSV()
                    numeroDePasosBBD = abs(int(round((VectorPosicionFinalBBD_mm[k]-VectorPosicionInicialBBD_mm[k])/VectorPasoBBD_mm[k], 6)))
                    for l in range(0,numeroDePasosBBD): # Hace el barrido de cada sección de la plataforma.
                        if self.MedicionCancelada():
                            return
                        tiempoDeSleep = self.bbd.CalcularTiempoSleep(VectorPasoBBD_mm[k]+self.bbd.posicion)
                        self.bbd.Mover(VectorPasoBBD_mm[k]+self.bbd.posicion)
                        if not self.EsperarSiSigue(tiempoDeSleep):
                            return
                        self.AdquirirGraficarYGrabarCSV()
                if j<numeroDePasosMono: # Mueve el monocromador para seguir barriendo con la plataforma.
                    tiempoDeSleep = self.mono.CalcularTiempoSleep(VectorPasoMono_nm[i] + self.mono.posicion)
                    self.mono.Mover(VectorPasoMono_nm[i] + self.mono.posicion)
                    if not self.EsperarSiSigue(tiempoDeSleep):
                        return

    def AdquirirGraficarYGrabarCSV(self):
        if not self.EsperarSiSigue(self.lockin.TiempoDeIntegracionTotal):
            return
        if self.MedicionCancelada():
            return
        vectorDeStringsDeDatos = self.ArmarVectorDeDatos()
        if self.MedicionCancelada():
            return
        self.grafico.Graficar(vectorDeStringsDeDatos,self.bbd.posicion,self.mono.posicion)
        self.GrabarCSV(vectorDeStringsDeDatos)

    def PrepararGuardadoCSV(self, nombreArchivo, metadata, repeticion):
        self.nombreArchivo = nombreArchivo
        VerificarDataManagerActualizado(self.data_manager)
        self.data_manager.begin_memory_run(nombreArchivo, metadata, repeticion)

    def FinalizarGuardadoCSV(self):
        return self.data_manager.finish_run()

    def GuardarPromedioCSV(self, nombreArchivo, runs, metadata):
        return self.data_manager.save_average(nombreArchivo, runs, metadata)

    def CalcularPromedioRepeticiones(self, runs):
        return self.data_manager.calculate_average(runs)

    def GuardarCorridasCSV(self, runs, nombreArchivo=None, metadata=None):
        return self.data_manager.save_runs(runs, nombreArchivo, metadata)

    def GrabarCSV(self, vectorDeStringsDeDatos): # Crea un archivo y va appendeando filas.
        self.data_manager.append_row(vectorDeStringsDeDatos)

    def ArmarVectorDeDatos(self): # Transforma el string que devuelve el LockIn en un vector de strings y le agrega
        # la posición del BBD y del mono.
        a = self.lockin.Adquirir()
        a = a + ',' + str(self.bbd.posicion) + ',' + str(self.mono.posicion)
        b = a.split(',')
        return b

    def CalcularPromedioAux(self, segundosAPromediar): # Calcula un promedio del aux si se tildea la Box correspondiente.
        # Es para los gráficos que tienen el AUX diviendo.
        promedio = 0
        if segundosAPromediar == 0:
            return promedio
        sumaDeAuxs = 0
        numeroTotalDeAuxsAPromediar = segundosAPromediar*numeroDeAuxsPorSegundo
        cantidadDeAuxsMedidos = 0
        tiempoADormirEnCadaMedicion = 1/numeroDeAuxsPorSegundo/10 # Es arbitrario. Es para darle unos milisegundos
                                                                  # mas al lock in para responder.
        for i in range(0,numeroTotalDeAuxsAPromediar): 
            if self.MedicionCancelada():
                break
            medicion = self.ArmarVectorDeDatos()
            if not self.EsperarSiSigue(tiempoADormirEnCadaMedicion):
                break
            aux = float(medicion[4])
            sumaDeAuxs = sumaDeAuxs + aux
            cantidadDeAuxsMedidos = cantidadDeAuxsMedidos + 1
        if cantidadDeAuxsMedidos == 0:
            return 0
        promedio = sumaDeAuxs/cantidadDeAuxsMedidos
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
        self.fig = plt.figure(figsize=(12.9,8.7), linewidth=10, edgecolor="#04253a")
        self.coloresRepeticiones = plt.rcParams["axes.prop_cycle"].by_key()["color"]
        self.lineasActuales = list()

    def Configurar(self, valoresAGraficar, promedioAux, promedioAuxBool, TipoDeMedicion, ejeX, VectorPosicionInicialBBD_mm = 0, VectorPosicionFinalBBD_mm = 0, VectorPasoBBD_mm = 0, VectorLongitudDeOndaInicial_nm = 0, VectorLongitudDeOndaFinal_nm = 0, VectorPasoMono_nm = 0, longitudDeOndaFija_nm = 0, posicionFijaBBD_mm = 0):
        self.fig.clear() # Borra la figura.
        self.fig.canvas.draw()
        self.fig.canvas.flush_events() # Actualiza la figura en la interfaz gráfica.
        self.TipoDeMedicion = TipoDeMedicion # Guarda el tipo de medición a realizar: 0, 1 o 2. (posicion, lambda o completa)
        self.ValoresAGraficar = valoresAGraficar # Es un vector de dimensión 6 con los booleanos de las checkbox
                                                 # que dicen qué cantidades se van a graficar.
        self.cantidadDeValoresAGraficar = valoresAGraficar.count(1)
        self.longitudDeOndaFija_nm = longitudDeOndaFija_nm # Para el tipo de medición 0
        self.posicionFijaBBD_mm = posicionFijaBBD_mm # Para el tipo de medición 1
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
            self.VectorX_mm = np.array(VectorPosicionInicialBBD_mm[0])
            for i in range(0,len(VectorPosicionInicialBBD_mm)):
                if i>0 and VectorPosicionInicialBBD_mm[i] != VectorPosicionFinalBBD_mm[i-1]:
                    self.VectorX_mm = np.append(self.VectorX_mm, VectorPosicionInicialBBD_mm[i])
                numeroDePasos = int(round((VectorPosicionFinalBBD_mm[i]-VectorPosicionInicialBBD_mm[i])/VectorPasoBBD_mm[i], 3))
                for j in range(0,numeroDePasos):
                    self.VectorX_mm = np.append(self.VectorX_mm, round(VectorPosicionInicialBBD_mm[i]+(j+1)*VectorPasoBBD_mm[i],6))
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
                    self.listaDeGraficos[i].yaxis.set_major_formatter(FormatStrFormatter('%.6f')) #CAMBIO
        if TipoDeMedicion == 1:
            for i in range (0,self.cantidadDeValoresAGraficar):
                titulo = 'Posición = ' + str(self.posicionFijaBBD_mm) + ' mm'
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
        self.fig.patch.set_facecolor("#ffffff")
        for grafico in self.listaDeGraficos:
            grafico.set_facecolor("#ffffff")
            grafico.grid(self.graficarGrid, color="#d5dde3", alpha=0.65)
            grafico.tick_params(direction="in", colors="#20242a")
            grafico.title.set_color("#20242a")
            grafico.xaxis.label.set_color("#20242a")
            grafico.yaxis.label.set_color("#20242a")
            for spine in grafico.spines.values():
                spine.set_color("#aebbc5")

    def IniciarRepeticion(self, repeticion, totalRepeticiones):
        self.repeticionActual = repeticion
        self.totalRepeticiones = totalRepeticiones
        self.x = list()
        self.lineasActuales = list()
        if self.TipoDeMedicion == 0 or self.TipoDeMedicion == 1:
            self.listaDeEjesY = list()
            for i in range(0, self.cantidadDeValoresAGraficar):
                self.listaDeEjesY.append(list())
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
                markersize=3.5,
                linewidth=1.8,
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
            return round(float(VectorAGraficar[indiceValor]), 7)
        aux = self.promedioAux
        if not self.promedioAuxBool:
            aux = float(VectorAGraficar[4])
        if aux == 0:
            return float("inf")
        if indiceValor == 4:
            return round(float(VectorAGraficar[0])/aux, 7)
        return round(float(VectorAGraficar[2])/aux, 7)

    # Los trés métodos que siguen se llaman cada vez que se hace una obtención de datos del Lock In en los barridos.

    def GraficarALambdaFija(self, VectorAGraficar, posicionBBD, posicionMono):
        if self.ejeX == 'Distancia':
            self.x.append(posicionBBD)
        else:
            self.x.append((posicionBBD)*(2/3)*10) # en picosegundos  
        # Este loop itera sobre cada gráfico de la figura. Se diferencia el 4 y el 5 porque son los X/Aux y R/Aux
        # que hay que dividirlos por Aux y por lo tanto darles un tratamiento especial debido a la posibilidad
        # de que esté promediado el Aux.
        for i in range(0, self.cantidadDeValoresAGraficar):
            if self.listaDeValoresAGraficar[i] != 4 and self.listaDeValoresAGraficar[i] != 5:
                self.listaDeEjesY[i].append(round(float(VectorAGraficar[self.listaDeValoresAGraficar[i]]), 7))
            else:
                if self.listaDeValoresAGraficar[i] == 4:
                    if self.promedioAuxBool:
                        self.listaDeEjesY[i].append(round(float(VectorAGraficar[0])/self.promedioAux, 7))
                    else:
                        self.listaDeEjesY[i].append(round(float(VectorAGraficar[0])/float(VectorAGraficar[4]), 7))
                elif self.listaDeValoresAGraficar[i] == 5:
                    if self.promedioAuxBool:
                        self.listaDeEjesY[i].append(round(float(VectorAGraficar[2])/self.promedioAux, 7))
                    else:
                        self.listaDeEjesY[i].append(round(float(VectorAGraficar[2])/float(VectorAGraficar[4]), 7))
            linea = self.ObtenerLineaActual(i)
            linea.set_data(self.x, self.listaDeEjesY[i])
            self.ActualizarLimitesDeGrafico(i)
        self.ActualizarFiguraEnInterfaz()

    def GraficarAPosicionFija(self, VectorAGraficar, posicionBBD, posicionMono):
        self.x.append(posicionMono)
        for i in range(0,self.cantidadDeValoresAGraficar):
            if self.listaDeValoresAGraficar[i] != 4 and self.listaDeValoresAGraficar[i] != 5:
                self.listaDeEjesY[i].append(round(float(VectorAGraficar[self.listaDeValoresAGraficar[i]]), 7))
            else:
                if self.listaDeValoresAGraficar[i] == 4:
                    if self.promedioAuxBool:
                        self.listaDeEjesY[i].append(round(float(VectorAGraficar[0])/self.promedioAux, 7))
                    else:
                        self.listaDeEjesY[i].append(round(float(VectorAGraficar[0])/float(VectorAGraficar[4]), 7))
                elif self.listaDeValoresAGraficar[i] == 5:
                    if self.promedioAuxBool:
                        self.listaDeEjesY[i].append(round(float(VectorAGraficar[2])/self.promedioAux, 7))
                    else:
                        self.listaDeEjesY[i].append(round(float(VectorAGraficar[2])/float(VectorAGraficar[4]), 7))
            linea = self.ObtenerLineaActual(i)
            linea.set_data(self.x, self.listaDeEjesY[i])
            self.ActualizarLimitesDeGrafico(i)
        self.ActualizarFiguraEnInterfaz()

    def GraficarCompletamente(self, VectorAGraficar, posicionBBD, posicionMono):
        posicionX = np.where(self.VectorX_mm == posicionBBD) # Este método recibe las posiciones actuales del BBD y
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
                        self.listaDeMatrices[i][posicionY[0][0],posicionX[0][0]] = float(VectorAGraficar[0])/self.promedioAux
                    else:
                        self.listaDeMatrices[i][posicionY[0][0],posicionX[0][0]] = float(VectorAGraficar[0])/float(VectorAGraficar[4])
                elif self.listaDeValoresAGraficar[i] == 5:
                    if self.promedioAuxBool:
                        self.listaDeMatrices[i][posicionY[0][0],posicionX[0][0]] = float(VectorAGraficar[2])/self.promedioAux
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
        yPromedio = list()
        for i in range(0, self.cantidadDeValoresAGraficar):
            yPromedio.append(list())
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
                linewidth=2.8,
                label="Promedio",
            )
            self.listaDeGraficos[i].legend(loc="best", fontsize=9)
            self.ActualizarLimitesDeGrafico(i)
        self.ActualizarFiguraEnInterfaz()

    def GuardarGrafico(self, nombreArchivo):
        carpetaPlots = RutaEnCarpetaDelCodigo("Plots")
        if not os.path.isdir(carpetaPlots):
            os.makedirs(carpetaPlots)
        if os.path.splitext(nombreArchivo)[1] == "":
            nombreArchivo = nombreArchivo + ".png"
        self.fig.savefig(os.path.join(carpetaPlots, nombreArchivo), dpi=200)

    def GuardarGraficosSeleccionados(self, nombreArchivo, indicesGraficos, runs=None, filasPromedio=None):
        rutas = list()
        if indicesGraficos is None or len(indicesGraficos) == 0:
            return rutas
        carpetaPlots = RutaEnCarpetaDelCodigo("Plots")
        if not os.path.isdir(carpetaPlots):
            os.makedirs(carpetaPlots)
        nombreBase = os.path.splitext(os.path.basename(nombreArchivo))[0]
        for indiceGrafico in indicesGraficos:
            if indiceGrafico < 0 or indiceGrafico >= len(self.listaDeValoresAGraficar):
                continue
            if self.TipoDeMedicion == 2:
                ruta = self.GuardarColorplotIndividual(carpetaPlots, nombreBase, indiceGrafico)
            else:
                ruta = self.GuardarCurvaIndividual(carpetaPlots, nombreBase, indiceGrafico, runs, filasPromedio)
            rutas.append(ruta)
        return rutas

    def GuardarCurvaIndividual(self, carpetaPlots, nombreBase, indiceGrafico, runs, filasPromedio):
        indiceValor = self.listaDeValoresAGraficar[indiceGrafico]
        nombreCanal = self.NombreSeguroCanal(indiceValor)
        if filasPromedio is not None:
            nombrePNG = nombreBase + "_promedio_" + nombreCanal + ".png"
        else:
            nombrePNG = nombreBase + "_" + nombreCanal + ".png"
        ruta = os.path.join(carpetaPlots, nombrePNG)
        figura = plt.figure(figsize=(7.5, 5.0))
        eje = figura.add_subplot(111)
        runs = runs or list()
        colorCrudo = "#c9d0d4"
        for run in runs:
            xRun, yRun = self.CalcularXYDesdeFilas(run.get("rows", []), indiceValor)
            if len(runs) == 1 and filasPromedio is None:
                eje.plot(xRun, yRun, marker="o", markersize=3.0, linewidth=1.8, color="#008f7a", label="Medicion")
            else:
                eje.plot(xRun, yRun, marker="o", markersize=2.2, linewidth=1.0, color=colorCrudo, alpha=0.75)
        if filasPromedio is not None:
            xPromedio, yPromedio = self.CalcularXYDesdeFilas(filasPromedio, indiceValor)
            eje.plot(xPromedio, yPromedio, "k-", linewidth=2.8, label="Promedio")
            eje.legend(loc="best", fontsize=9)
        elif len(runs) > 1:
            eje.plot([], [], color=colorCrudo, linewidth=1.5, label="Repeticiones")
            eje.legend(loc="best", fontsize=9)
        eje.set_title(self.listaDeGraficos[indiceGrafico].get_title())
        eje.set_xlabel(self.listaDeGraficos[indiceGrafico].get_xlabel())
        eje.set_ylabel(self.listaDeKeysDelDiccionario[indiceGrafico])
        eje.grid(True, color="#d5dde3", alpha=0.65)
        eje.tick_params(direction="in", colors="#20242a")
        figura.tight_layout()
        figura.savefig(ruta, dpi=220)
        plt.close(figura)
        return ruta

    def GuardarColorplotIndividual(self, carpetaPlots, nombreBase, indiceGrafico):
        indiceValor = self.listaDeValoresAGraficar[indiceGrafico]
        nombreCanal = self.NombreSeguroCanal(indiceValor)
        nombrePNG = nombreBase + "_" + nombreCanal + ".png"
        ruta = os.path.join(carpetaPlots, nombrePNG)
        figura = plt.figure(figsize=(7.5, 5.0))
        eje = figura.add_subplot(111)
        if self.ejeX == 'Distancia':
            x = self.VectorX_mm
        else:
            x = self.VectorX_ps
        contour = eje.contourf(x, self.VectorY, self.listaDeMatrices[indiceGrafico], 20, cmap='RdGy')
        figura.colorbar(contour, ax=eje)
        eje.set_title(self.listaDeGraficos[indiceGrafico].get_title())
        eje.set_xlabel(self.listaDeGraficos[indiceGrafico].get_xlabel())
        eje.set_ylabel('Longitud de onda (nm)')
        figura.tight_layout()
        figura.savefig(ruta, dpi=220)
        plt.close(figura)
        return ruta

    def CalcularXYDesdeFilas(self, filas, indiceValor):
        x = list()
        y = list()
        for fila in filas:
            if self.TipoDeMedicion == 0:
                if self.ejeX == 'Distancia':
                    x.append(fila[6])
                else:
                    x.append((fila[6])*(2/3)*10)
            if self.TipoDeMedicion == 1:
                x.append(fila[7])
            y.append(self.CalcularValorYGraficable(fila, indiceValor))
        return x, y

    def NombreSeguroCanal(self, indiceValor):
        nombres = {
            0: "X",
            1: "Y",
            2: "R",
            3: "theta",
            4: "X_AUX",
            5: "R_AUX",
        }
        return nombres.get(indiceValor, "canal")

    def Graficar(self, VectorAGraficar, posicionBBD, posicionMono): # Elije a qué método llamar.
        if self.TipoDeMedicion == 0:
            self.GraficarALambdaFija(VectorAGraficar, posicionBBD, posicionMono)
        if self.TipoDeMedicion == 1:
            self.GraficarAPosicionFija(VectorAGraficar, posicionBBD, posicionMono)
        if self.TipoDeMedicion == 2:
            self.GraficarCompletamente(VectorAGraficar, posicionBBD, posicionMono)

