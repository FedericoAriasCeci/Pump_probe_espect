from logic_tier import * 

from decimal import Decimal

try:
    from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk
except ImportError:
    from matplotlib.backends.backend_tkagg import NavigationToolbar2TkAgg as NavigationToolbar2Tk


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

COLOR_FONDO = "#e8f5f1"
COLOR_PANEL = "#fffdf7"
COLOR_PANEL_SUAVE = "#d7eee8"
COLOR_TEXTO = "#20242a"
COLOR_TEXTO_SUAVE = "#5f6b75"
COLOR_BORDE = "#8fc4bb"
COLOR_ACENTO = "#008f7a"
COLOR_ACENTO_OSCURO = "#06655e"
COLOR_OK = "#238b57"
COLOR_ADVERTENCIA = "#cf8a18"
COLOR_ERROR = "#b64b4b"
COLOR_BOTON_SECUNDARIO = "#dceee9"


def AplicarTema(raiz):
    try:
        raiz.configure(bg=COLOR_FONDO)
    except Exception:
        pass
    opciones = {
        "*Font": fuente + " 11",
        "*Label.Background": COLOR_FONDO,
        "*Label.Foreground": COLOR_TEXTO,
        "*Button.Font": fuente + " 11",
        "*Button.Relief": "flat",
        "*Button.BorderWidth": "0",
        "*Button.Background": COLOR_BOTON_SECUNDARIO,
        "*Button.Foreground": COLOR_TEXTO,
        "*Button.ActiveBackground": COLOR_ACENTO,
        "*Button.ActiveForeground": "#ffffff",
        "*Entry.Background": "#ffffff",
        "*Entry.Foreground": COLOR_TEXTO,
        "*Entry.Relief": "flat",
        "*Entry.BorderWidth": "1",
        "*Checkbutton.Background": COLOR_FONDO,
        "*Checkbutton.Foreground": COLOR_TEXTO,
        "*Checkbutton.ActiveBackground": COLOR_FONDO,
        "*Checkbutton.SelectColor": COLOR_PANEL,
    }
    for clave in opciones:
        try:
            raiz.option_add(clave, opciones[clave])
        except Exception:
            pass


def EstilizarBoton(boton, tipo):
    colores = {
        "primario": (COLOR_ACENTO, "#ffffff", COLOR_ACENTO_OSCURO),
        "ok": (COLOR_OK, "#ffffff", "#257f51"),
        "peligro": (COLOR_ERROR, "#ffffff", "#933c3c"),
        "secundario": (COLOR_BOTON_SECUNDARIO, COLOR_TEXTO, "#d8e1e7"),
        "advertencia": (COLOR_ADVERTENCIA, "#ffffff", "#a96d13"),
    }
    if tipo not in colores:
        tipo = "secundario"
    fondo, texto, activo = colores[tipo]
    try:
        boton.configure(
            bg=fondo,
            fg=texto,
            activebackground=activo,
            activeforeground=texto,
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            cursor="hand2",
        )
    except Exception:
        pass


def EstilizarHijos(widget):
    for hijo in widget.winfo_children():
        if isinstance(hijo, tk.Button):
            texto = ""
            try:
                texto = hijo.cget("text")
            except Exception:
                texto = ""
            if texto in ("Salir", "Cancelar", "Frenar"):
                EstilizarBoton(hijo, "peligro")
            elif texto in ("Conectar", "Inicializar", "Iniciar", "Barrer", "Barrido doble", "Continuar"):
                EstilizarBoton(hijo, "primario")
            elif texto == "Guardar":
                EstilizarBoton(hijo, "ok")
            elif texto in ("Ok", "Setear", "Cambiar", "Mover"):
                EstilizarBoton(hijo, "secundario")
            elif texto == "?":
                EstilizarBoton(hijo, "advertencia")
            else:
                EstilizarBoton(hijo, "secundario")
        elif isinstance(hijo, tk.Label):
            try:
                texto_label = hijo.cget("text")
                color_texto = COLOR_TEXTO
                if texto_label in ("Conectado", "Reconocido", "Inicializado", "Homed"):
                    color_texto = COLOR_OK
                if texto_label in ("No reconocido", "Error"):
                    color_texto = COLOR_ERROR
                hijo.configure(bg=COLOR_FONDO, fg=color_texto)
            except Exception:
                pass
        elif isinstance(hijo, tk.Entry):
            try:
                hijo.configure(bg="#ffffff", fg=COLOR_TEXTO, relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_BORDE)
            except Exception:
                pass
        elif isinstance(hijo, tk.Checkbutton):
            try:
                hijo.configure(bg=COLOR_FONDO, fg=COLOR_TEXTO, activebackground=COLOR_FONDO, selectcolor=COLOR_PANEL)
            except Exception:
                pass
        elif isinstance(hijo, tk.Canvas):
            try:
                hijo.configure(bg=COLOR_FONDO, highlightthickness=0)
            except Exception:
                pass
        EstilizarHijos(hijo)


def CrearSeparador(canvas, x1, y1, x2, y2):
    canvas.create_line(x1, y1, x2, y2, fill=COLOR_BORDE)

class Advertencia(): # Es simplemente una ventanita que tiene un título y un texto, con un botón para cerrarla.

    def __init__(self, titulo, texto):
        advertencia = tk.Tk()
        AplicarTema(advertencia)
        advertencia.title(titulo)
        ws, hs = advertencia.winfo_screenwidth(), advertencia.winfo_screenheight()
        advertencia.geometry('%dx%d+%d+%d' % (500, 200, ws/3, hs/3))
        labelExplicacion = tk.Label(advertencia, text = texto, font=(fuente,12))
        labelExplicacion.place(x=0, y=0)
        def Cerrar():
            advertencia.destroy()
        botonCerrar = tk.Button(advertencia, text = 'Ok', command = Cerrar, font=(fuente,15))
        botonCerrar.place(x=360, y = 140, height=30, width=40)
        EstilizarHijos(advertencia)
        advertencia.mainloop()

class Medicion():

    def IniciarVentana(self, programa, tiempoDeMedicion, tipoDeMedicion, experimento, VectorPosicionInicialBBD_mm=0, VectorPosicionFinalBBD_mm=0, VectorPasoBBD_mm=0, VectorLongitudDeOndaInicial_nm=0, VectorLongitudDeOndaFinal_nm=0, VectorPasoMono_nm=0):
        experimento.IniciarMedicion()
        self.programaGuardado = programa
        self.midiendo = tk.Tk()
        experimento.SetearActualizadorInterfaz(self.midiendo.update)
        AplicarTema(self.midiendo)
        self.midiendo.title('Midiendo')
        ws, hs = self.midiendo.winfo_screenwidth(), self.midiendo.winfo_screenheight()
        self.midiendo.geometry('%dx%d+%d+%d' % (760, 320, ws/3 , hs/70))
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
            experimento.CancelarMedicion()
            botonCancelar["state"]="disabled"
            self.CambiarEstadoGuardado("Cancelando: se detendra al terminar la instruccion actual.")
            programa.ActualizarEstado("cancelando medicion")
        botonCancelar = tk.Button(self.midiendo, text = 'Cancelar', command = Cancelar, font=(fuente,12))
        botonCancelar.place(x=105, y = 270, height=35, width=95)
        def Finalizar(): # Es un botón para cerrar la ventana una vez que finalizó completamente la medición.
            experimento.SetearActualizadorInterfaz(None)
            self.midiendo.destroy()
        self.botonFinalizar = tk.Button(self.midiendo, text = 'Finalizar', command = Finalizar, font=(fuente,12))
        self.botonFinalizar.place(x=305, y = 270, height=35, width=95)
        def Guardar():
            self.GuardarMedicionPendiente()
        self.botonGuardar = tk.Button(self.midiendo, text = 'Guardar', command = Guardar, font=(fuente,12))
        self.botonGuardar.place(x=505, y = 270, height=35, width=95)
        EstilizarHijos(self.midiendo)
        self.botonFinalizar["state"]="disabled" # Empieza deshabilitado. Se habilita al terminar la medición.
        self.botonGuardar["state"]="disabled"
        self.runsPendientes = list()
        self.nombreArchivoPromedioPendiente = ""
        self.resultadoPromedioPendiente = None
        self.metadataPendiente = dict()
        self.nombreArchivoCrudoPendiente = ""
        self.nombreGraficoPendiente = ""
        self.promedioPendiente = False
        self.guardoMedicion = False
        self.varsGraficosAGuardar = list()
        self.widgetsGraficosAGuardar = list()
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
            metadataBase = self.ArmarMetadataBase(programa, tipoDeMedicion, ejeX, valoresAGraficar, cantidadDeMedicionesARealizar, VectorPosicionInicialBBD_mm, VectorPosicionFinalBBD_mm, VectorPasoBBD_mm, VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm)
            runs = list()
            medicionCancelada = False
            resultadoPromedio = None
            
            for i in range(0,int(cantidadDeMedicionesARealizar)):
                if experimento.MedicionCancelada():
                    medicionCancelada = True
                    programa.ActualizarEstado("medicion cancelada")
                    break
                if int(cantidadDeMedicionesARealizar) > 1:
                    nombreArchivoDeLaMedicion_i = add_suffix_to_filename(nombreArchivo, i+1) 
                else:
                    nombreArchivoDeLaMedicion_i = nombreArchivo
                programa.ActualizarEstado("midiendo repeticion " + str(i+1) + " de " + str(cantidadDeMedicionesARealizar))
                # Los próximos tres if son para generar el gráfico correspondiente a la medición. Configurar
                # es como resetear el objeto grafico.
                if tipoDeMedicion == 0 and i == 0:
                    programa.grafico.Configurar(valoresAGraficar, promedioAux, programa.panelPromedioAux.ObtenerPromedioAuxBool(), 0, ejeX, longitudDeOndaFija_nm=experimento.mono.posicion)
                if tipoDeMedicion == 1 and i == 0:
                    programa.grafico.Configurar(valoresAGraficar, promedioAux, programa.panelPromedioAux.ObtenerPromedioAuxBool(), 1, 0, posicionFijaBBD_mm = experimento.bbd.posicion)
                if tipoDeMedicion == 2:
                    programa.grafico.Configurar(valoresAGraficar, promedioAux, programa.panelPromedioAux.ObtenerPromedioAuxBool(), 2, ejeX, VectorPosicionInicialBBD_mm, VectorPosicionFinalBBD_mm, VectorPasoBBD_mm, VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm)            
                if i == 0:
                    self.CrearOpcionesGraficosAGuardar(programa.grafico)
                experimento.grafico = programa.grafico # Se le asigna el mismo gráfico al objeto experimento.
                experimento.grafico.IniciarRepeticion(i+1, cantidadDeMedicionesARealizar)
                metadataMedicion = dict(metadataBase)
                metadataMedicion["repeticion"] = i+1
                experimento.PrepararGuardadoCSV(nombreArchivoDeLaMedicion_i, metadataMedicion, i+1)
           
                # Estos tres if son para realizar la medición. Dentro de estas líneas ocurren literalmente todas 
                # las mediciones.
                if tipoDeMedicion == 0:
                   experimento.MedicionALambdaFija(nombreArchivoDeLaMedicion_i,VectorPosicionInicialBBD_mm,VectorPosicionFinalBBD_mm,VectorPasoBBD_mm)
                if tipoDeMedicion == 1:
                    experimento.MedicionAPosicionFijaBBD(nombreArchivoDeLaMedicion_i,VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm)
                if tipoDeMedicion == 2:
                    experimento.MedicionCompleta(nombreArchivoDeLaMedicion_i, VectorPosicionInicialBBD_mm,VectorPosicionFinalBBD_mm,VectorPasoBBD_mm, VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm)
                runs.append(experimento.FinalizarGuardadoCSV())
                programa.panelJoggingPlataforma.Actualizar()  
                programa.panelJoggingRedDeDifraccion.Actualizar()
                self.CambiarEstadoAFinalizado(nombreArchivo, cantidadDeMedicionesARealizar, i)
                if experimento.MedicionCancelada():
                    medicionCancelada = True
                    programa.ActualizarEstado("medicion cancelada")
                    break
            if not medicionCancelada and promediarRepeticiones and cantidadDeMedicionesARealizar > 1:
                nombreArchivoPromedio = add_suffix_to_filename(nombreArchivo, "promedio")
                resultadoPromedio = experimento.CalcularPromedioRepeticiones(runs)
                if resultadoPromedio["ok"]:
                    if tipoDeMedicion != 2:
                        experimento.grafico.GraficarPromedio(resultadoPromedio["rows"])
                    self.CambiarEstadoPromedio("Promedio calculado. Use Guardar para escribir los archivos.")
                    programa.ActualizarEstado("medicion finalizada, pendiente de guardar")
                else:
                    self.CambiarEstadoPromedio("No se calculo promedio: " + resultadoPromedio["message"])
                    programa.ActualizarEstado("promedio no calculado")
            self.runsPendientes = runs
            self.nombreArchivoCrudoPendiente = nombreArchivo
            self.nombreArchivoPromedioPendiente = add_suffix_to_filename(nombreArchivo, "promedio")
            self.resultadoPromedioPendiente = None
            if promediarRepeticiones and cantidadDeMedicionesARealizar > 1:
                self.resultadoPromedioPendiente = resultadoPromedio
            self.metadataPendiente = metadataBase
            self.promedioPendiente = promediarRepeticiones and cantidadDeMedicionesARealizar > 1
            self.nombreGraficoPendiente = os.path.splitext(os.path.basename(nombreArchivo))[0]
            if len(runs) > 0:
                self.botonGuardar["state"]="normal"
            self.HabilitarBotonFinalizar()
            experimento.SetearActualizadorInterfaz(None)
            if medicionCancelada:
                if len(runs) > 0:
                    self.CambiarEstadoPromedio("Medicion cancelada. Puede guardar los datos parciales.")
                    programa.ActualizarEstado("medicion cancelada, pendiente de guardar")
                else:
                    self.CambiarEstadoPromedio("Medicion cancelada sin datos guardables.")
                    programa.ActualizarEstado("medicion cancelada")
            elif not promediarRepeticiones or cantidadDeMedicionesARealizar <= 1:
                programa.ActualizarEstado("medicion finalizada, pendiente de guardar")
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
            self.labelEstadoFinalizado = tk.Label(self.midiendo, text="Medicion finalizada. Guardar escribe archivos.\nFinalizar cierra sin guardar. Nombre: " + nombreArchivo, font=(fuente,12))
        else:
            self.labelEstadoFinalizado = tk.Label(self.midiendo, text="Medicion " + str(numeroDeMedicion+1) + " finalizada. Guardar escribe archivos.\nFinalizar cierra sin guardar. Nombre: " + nombreArchivo, font=(fuente,12))
        self.labelEstadoFinalizado.place(x=0, y=80)  
        EstilizarHijos(self.midiendo)

    def CambiarEstadoPromedio(self, texto):
        self.labelEstadoPromedio = tk.Label(self.midiendo, text=texto, font=(fuente,10))
        self.labelEstadoPromedio.place(x=0, y=138)
        EstilizarHijos(self.midiendo)

    def CambiarEstadoGuardado(self, texto):
        self.labelEstadoGuardado = tk.Label(self.midiendo, text=texto, font=(fuente,10))
        self.labelEstadoGuardado.place(x=0, y=225)
        EstilizarHijos(self.midiendo)

    def CrearOpcionesGraficosAGuardar(self, grafico):
        for widget in self.widgetsGraficosAGuardar:
            try:
                widget.destroy()
            except Exception:
                pass
        self.widgetsGraficosAGuardar = list()
        self.varsGraficosAGuardar = list()
        label = tk.Label(self.midiendo, text="PNG a guardar:", font=(fuente,10))
        label.place(x=0, y=168)
        self.widgetsGraficosAGuardar.append(label)
        x0 = 115
        y0 = 188
        for i in range(0, len(grafico.listaDeKeysDelDiccionario)):
            var = tk.IntVar()
            var.set(1)
            texto = grafico.listaDeKeysDelDiccionario[i]
            check = tk.Checkbutton(self.midiendo, text=texto, variable=var, font=(fuente,10))
            check.place(x=x0 + 100*i, y=y0)
            self.varsGraficosAGuardar.append(var)
            self.widgetsGraficosAGuardar.append(check)
        EstilizarHijos(self.midiendo)

    def ObtenerGraficosAGuardar(self):
        indices = list()
        for i in range(0, len(self.varsGraficosAGuardar)):
            if self.varsGraficosAGuardar[i].get():
                indices.append(i)
        return indices

    def GuardarMedicionPendiente(self):
        if self.guardoMedicion:
            return
        if len(self.runsPendientes) == 0:
            self.CambiarEstadoGuardado("No hay datos pendientes para guardar.")
            return
        experimento = self.programaGuardado.experimento
        rutas = experimento.GuardarCorridasCSV(self.runsPendientes, self.nombreArchivoCrudoPendiente, self.metadataPendiente)
        rutaPromedio = None
        filasPromedio = None
        if self.promedioPendiente and self.resultadoPromedioPendiente is not None:
            if self.resultadoPromedioPendiente["ok"]:
                resultadoGuardadoPromedio = experimento.GuardarPromedioCSV(self.nombreArchivoPromedioPendiente, self.runsPendientes, self.metadataPendiente)
                rutaPromedio = resultadoGuardadoPromedio["path"]
                filasPromedio = self.resultadoPromedioPendiente["rows"]
        rutasGraficos = list()
        if self.nombreGraficoPendiente != "":
            rutasGraficos = experimento.grafico.GuardarGraficosSeleccionados(
                self.nombreGraficoPendiente,
                self.ObtenerGraficosAGuardar(),
                self.runsPendientes,
                filasPromedio,
            )
        self.guardoMedicion = True
        self.botonGuardar["state"]="disabled"
        textoGuardado = "Guardado: 1 CSV crudo"
        if rutaPromedio is not None:
            textoGuardado = textoGuardado + " + promedio"
        textoGuardado = textoGuardado + " + " + str(len(rutasGraficos)) + " PNG."
        self.CambiarEstadoGuardado(textoGuardado)
        self.programaGuardado.ActualizarEstado("datos guardados")

    def ArmarMetadataBase(self, programa, tipoDeMedicion, ejeX, valoresAGraficar, cantidadDeMedicionesARealizar, VectorPosicionInicialBBD_mm, VectorPosicionFinalBBD_mm, VectorPasoBBD_mm, VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm):
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
            "bbd_conectado": getattr(programa.experimento.bbd, "connected", ""),
            "bbd_homed": getattr(programa.experimento.bbd, "homed", ""),
            "puerto_sms": getattr(programa.experimento.mono, "puerto", ""),
            "puerto_lockin": getattr(programa.experimento.lockin, "puerto", ""),
            "bbd_inicio_mm": VectorPosicionInicialBBD_mm,
            "bbd_fin_mm": VectorPosicionFinalBBD_mm,
            "bbd_paso_mm": VectorPasoBBD_mm,
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
        AplicarTema(raizConfiguracion)
        raizConfiguracion.title('Pump and Probe Software - Configuración')
        ws, hs = raizConfiguracion.winfo_screenwidth(), raizConfiguracion.winfo_screenheight()
        raizConfiguracion.geometry('%dx%d+%d+%d' % (1360, 280,ws/6 ,hs/4 ))#'1450x825' Notebook #'1920x1080' Mi compu de escritorio #'' Laboratorio
        
        puertoSMSDefault, puertoLockInDefault = self.programa.LeerDataPuertos()

        # Esta parte es para armar las líneas que arman el cuadro de Configuracion.
        canvasRecuadros = Canvas(raizConfiguracion, width=ws, height=hs, bg=COLOR_FONDO, highlightthickness=0)
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

        # BBD - PLATAFORMA DE RETARDO #
        # Esta función se llama al tocar el botón Setear.
  
        # Esta función se llama al tocar le botón Inicializar.
        def ConectarBBD():
        
            self.experimento.bbd.Conectar()
            self.experimento.bbd.Home()
            labelBBDInicializado.config(text = 'Inicializado', font=(fuente,12))
            #botonCalibrarBBD['state'] = 'normal'
            botonCambiarVelocidadBBD["state"]="normal"
            textoVelocidadBBD["state"]="normal"
            textoVelocidadBBD.config(text=str(self.experimento.bbd.velocidadMmPorSegundo))

        def CambiarVelocidadBBD():
            self.experimento.bbd.CambiarVelocidad(float(textoVelocidadBBD.get()))
        labelBBD = tk.Label(raizConfiguracion, text = 'Plataforma de retardo(BBD)', font=(fuente,15))
        labelBBD.place(x=5, y=45)
        
        
        textoVelocidadBBD = tk.Entry(raizConfiguracion, font=(fuente,15))
        textoVelocidadBBD.place(x=860, y=45, height=30, width=50)
       
        """
        botonCalibrarBBD = tk.Button(raizConfiguracion, text = 'Home', command = HomeBBD, font=(fuente,12))
        botonCalibrarBBD.place(x=740, y=45)
        """
        
        botonInicializarBBD = tk.Button(raizConfiguracion, text = 'Conectar', command = ConectarBBD, font=(fuente,12))
        botonInicializarBBD.place(x=500,y=45)
        
        botonCambiarVelocidadBBD = tk.Button(raizConfiguracion, text = 'Cambiar', command = CambiarVelocidadBBD, font=(fuente,12))
        botonCambiarVelocidadBBD.place(x=930, y=45)
        # Estos if y else son para que al reabrir la ventana configuración esté todo como tiene que estar.
        # Esto podría pasarse a objetos de una forma más normal...
        
        if (self.experimento.bbd.connected and self.experimento.bbd.homed):
            labelBBDReconocido = tk.Label(raizConfiguracion, text = 'Conectado', font=(fuente,12))
            labelBBDInicializado = tk.Label(raizConfiguracion, text = 'Inicializado', font=(fuente,12))
            botonInicializarBBD["state"] = "disabled"
            botonCambiarVelocidadBBD["state"]="normal"
            textoVelocidadBBD["state"]="normal"
            textoVelocidadBBD.config(text=str(self.experimento.BBD.velocidadMmPorSegundo))
        else:
            labelBBDInicializado = tk.Label(raizConfiguracion)
            labelBBDReconocido = tk.Label(raizConfiguracion)
            botonInicializarBBD["state"] = "normal"             
            botonCambiarVelocidadBBD["state"]="disabled"
            textoVelocidadBBD["state"]="disabled"
        labelBBDReconocido.place(x=380, y=50)
        
        """
        if self.experimento.bbd.homed:
            labelBBDInicializado = tk.Label(raizConfiguracion, text = 'Homed', font=(fuente,12))
            #botonCalibrarBBD["state"] = "normal"    
            botonCambiarVelocidadBBD["state"]="normal"
            textoVelocidadBBD["state"]="normal"
            textoVelocidadBBD.config(text=str(self.experimento.BBD.velocidadMmPorSegundo))
        else:
            labelBBDInicializado = tk.Label(raizConfiguracion)
            #botonCalibrarBBD["state"] = "disabled"   
            botonCambiarVelocidadBBD["state"]="disabled"
            textoVelocidadBBD["state"]="disabled"
        labelBBDInicializado.place(x=640, y=50)
        """
        
        
        # SMS - MONOCROMADOR #
        def SetearPuertoSMS():
            try:
                puertoSMS = int(textoMono.get())
            except ValueError:
                Advertencia('Atención','El valor ingresado debe ser un número entero.')
                return
            try:
                self.experimento.mono.AsignarPuerto('COM' + str(puertoSMS))
            except:
                Advertencia('Atención','No se ha podido abrir el puerto serie.')
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
            self.programa.GrabarDataPuertos(textoMono.get(), textoLockIn.get())
            raizConfiguracion.destroy()
            # Acá se llama a la Pantalla Principal y se corre casi todo el código de la clase Programa.
            self.programa.PantallaPrincipal()
        def Salir():
            raizConfiguracion.destroy()  
            if self.experimento.bbd.connected:
                self.experimento.bbd.Cerrar()                  
        if self.primeraVez:
            botonMenuPrincipal = tk.Button(raizConfiguracion, text = 'Continuar', command = MenuPrincipal, font=(fuente,15))
            botonMenuPrincipal.place(x=200, y=200)
            botonSalir = tk.Button(raizConfiguracion, text = 'Salir', command = Salir, font=(fuente,15))
            botonSalir.place(x=100, y=200)
            self.primeraVez = False
        else:
            botonSalir = tk.Button(raizConfiguracion, text = 'Volver', command = Salir, font=(fuente,15))
            botonSalir.place(x=100, y=200)            
        EstilizarHijos(raizConfiguracion)
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
            
            labelPosicionBBD = tk.Label(raiz, text = 'Posicion: ', font=(fuente,20))
            labelPosicionBBD.place(x=X, y=Y+5)
            labelPasoBBD = tk.Label(raiz, text = 'Paso: ', font=(fuente,20))
            labelPasoBBD.place(x=X, y=Y+50)
            self.textoPosicionBBD = tk.Entry(raiz, font=(fuente,20))
            self.textoPosicionBBD.place(x=X+170, y=Y+7, height=35, width=100)
            textoPasoBBD = tk.Entry(raiz, width=5, font=(fuente,20))
            textoPasoBBD.place(x=X+170, y=Y+50, height=35, width=100)
            self.textoPosicionBBD.delete(0, tk.END)
            self.textoPosicionBBD.insert(0, str(self.experimento.bbd.posicion))
            textoPasoBBD.delete(0, tk.END)
            textoPasoBBD.insert(0, '1')
            def IrALaPosicionBBD():
                comando = float(self.textoPosicionBBD.get())
                self.experimento.bbd.Mover(comando)
            def MoverHaciaAdelante():
                comando = round(float(textoPasoBBD.get()),6)
                comandoMultiploDeLaResolucion = round(self.experimento.bbd.resolucion*int(comando/self.experimento.bbd.resolucion), 6)
                textoPasoBBD.delete(0, tk.END)
                textoPasoBBD.insert(0, str(comandoMultiploDeLaResolucion)) 
                self.experimento.bbd.Mover(comandoMultiploDeLaResolucion+self.experimento.bbd.posicion)
                self.Actualizar()
            def MoverHaciaAtras():
                comando = round(float(textoPasoBBD.get()),6)
                comandoMultiploDeLaResolucion = round(self.experimento.bbd.resolucion*int(comando/self.experimento.bbd.resolucion), 6)
                textoPasoBBD.delete(0, tk.END)
                textoPasoBBD.insert(0, str(comandoMultiploDeLaResolucion)) 
                self.experimento.bbd.Mover((-1)*comandoMultiploDeLaResolucion+self.experimento.bbd.posicion)
                self.Actualizar()
            botonIrALaPosicionBBD = tk.Button(raiz, text="Mover", command=IrALaPosicionBBD, font=(fuente,15))
            botonIrALaPosicionBBD.place(x=X+285, y=Y, height=40, width=90)
            botonMoverHaciaDelante = tk.Button(raiz, text="+", command=MoverHaciaAdelante, font=(fuente,15))
            botonMoverHaciaDelante.place(x=X+285, y=Y+45, height=40, width=45)
            botonMoverHaciaAtras = tk.Button(raiz, text="-", command=MoverHaciaAtras, font=(fuente,15))
            botonMoverHaciaAtras.place(x=X+330, y=Y+45, height=40, width=45)
    
        def Actualizar(self):
            self.textoPosicionBBD.delete(0, tk.END)
            self.textoPosicionBBD.insert(0, str(self.experimento.bbd.posicion))
    
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
                   
                    resto = valor%Decimal(str(self.experimento.bbd.resolucion))
                    
                    print("Resto",resto)
                    if resto != 0:
                        if resto < (self.experimento.bbd.resolucion/2):
                            valorMultiploDeLaResolucion = round(self.experimento.bbd.resolucion*int(round(valor/Decimal(str(self.experimento.bbd.resolucion)), 6)), 6)
                        if resto > (self.experimento.bbd.resolucion/2):
                            valorMultiploDeLaResolucion = round(self.experimento.bbd.resolucion*int(round(valor/Decimal(str(self.experimento.bbd.resolucion)), 6)), 6) + self.experimento.bbd.resolucion
                        if valorMultiploDeLaResolucion == 0:
                            valorMultiploDeLaResolucion = self.experimento.bbd.resolucion
                        self.textosPaso[i].delete(0, tk.END)
                        self.textosPaso[i].insert(0, str(valorMultiploDeLaResolucion))
    
        def ObtenerValores(self):
            self.ChequearResolucionDeLosValores()
            VectorPosicionInicialBBD_mm = list()
            VectorPosicionFinalBBD_mm = list()
            VectorPasoBBD_mm = list()
            for i in range(0,self.numeroDeSubintervalos):
                if self.textosPosicionInicial[i].get() != '' and self.textosPosicionFinal[i].get() != '' and self.textosPaso[i].get() != '':
                    VectorPosicionInicialBBD_mm.append(float(self.textosPosicionInicial[i].get()))
                    VectorPosicionFinalBBD_mm.append(float(self.textosPosicionFinal[i].get()))
                    VectorPasoBBD_mm.append(float(self.textosPaso[i].get()))            
            return (VectorPosicionInicialBBD_mm, VectorPosicionFinalBBD_mm, VectorPasoBBD_mm)
    
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
            print("Entro a la funcion")
            self.ChequearResolucionDeLosValores()
            print("Chequee los valores")
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
        AplicarTema(self.raiz)
        self.raiz.title('Pump and Probe Software')
        ws, hs = self.raiz.winfo_screenwidth(), self.raiz.winfo_screenheight()
        self.raiz.geometry('%dx%d+0+0' % (ws, hs))#'1450x825' Notebook #'1920x1080' Mi compu de escritorio #'' Laboratorio
        self.raiz.state('zoomed')   
        self.raiz.config(background=COLOR_FONDO)

        # GRAFICO #
        self.grafico = Grafico()
        canvasRecuadros = Canvas(self.raiz, width=ws, height=hs, bg=COLOR_FONDO, highlightthickness=0)
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
        canvas.get_tk_widget().place(x=10,y=180)
        try:
            canvas.get_tk_widget().configure(bg=COLOR_PANEL, highlightthickness=1, highlightbackground=COLOR_BORDE)
        except Exception:
            pass
        canvas.draw()
        toolbarY = 140
        frameToolbar = tk.Frame(self.raiz, bg=COLOR_PANEL, bd=1, relief="flat")
        frameToolbar.place(x=10, y=toolbarY, width=1290, height=38)
        try:
            self.toolbarGrafico = NavigationToolbar2Tk(canvas, frameToolbar, pack_toolbar=False)
            self.toolbarGrafico.update()
            self.toolbarGrafico.pack(side=tk.LEFT, fill=tk.X)
        except TypeError:
            self.toolbarGrafico = NavigationToolbar2Tk(canvas, frameToolbar)
            self.toolbarGrafico.update()
        labelToolbar = tk.Label(frameToolbar, text="Herramientas del grafico: pan / zoom por subplot / guardar vista", font=(fuente,9), bg=COLOR_PANEL, fg=COLOR_TEXTO_SUAVE)
        labelToolbar.pack(side=tk.RIGHT, padx=8)
        frameToolbar.lift()
        EstilizarHijos(frameToolbar)
        estadoY = min(1052, hs-28)
        self.labelEstadoGeneral = tk.Label(self.raiz, text="Estado: listo", anchor="w", font=(fuente,10), bg=COLOR_ACENTO_OSCURO, fg="#ffffff")
        self.labelEstadoGeneral.place(x=10, y=estadoY, width=1290, height=24)
        
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
        
        # BARRIDO EN POSICIONES DEL BBD #
        self.panelBarridoEnDistancia = self.PanelBarridoEnDistancia(self.raiz, (1330,10), self.experimento)

        # Esta función es llamada al hacer un barrido en posiciones.
        def MedirALambdaFija():
            VectorPosicionInicialBBD_mm, VectorPosicionFinalBBD_mm, VectorPasoBBD_mm = self.panelBarridoEnDistancia.ObtenerValores()
            self.raiz.update()
            medicion = Medicion()
            tiempoDeMedicion = int(self.CalcularTiempoDeMedicionALambdaFija(VectorPosicionInicialBBD_mm,VectorPosicionFinalBBD_mm,VectorPasoBBD_mm))                
            medicion.IniciarVentana(self, tiempoDeMedicion, 0, self.experimento, VectorPosicionInicialBBD_mm, VectorPosicionFinalBBD_mm, VectorPasoBBD_mm)
        botonMedirALambdaFija = tk.Button(self.raiz, text="Barrer", command=MedirALambdaFija, font=(fuente,15))
        botonMedirALambdaFija.place(x=1580, y=300, height=40, width=115)
    
        #BARRIDO EN LONGITUDES DE ONDA#
        self.panelBarridoEnLongitudesDeOnda = self.PanelBarridoEnLongitudesDeOnda(self.raiz, (1330,360), self.experimento)
        
        # Esta función es llamada al hacer un barrido en longitudes de onda.
        def MedirAPosicionFija():
            VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm = self.panelBarridoEnLongitudesDeOnda.ObtenerValores()
            self.raiz.update()            
            medicion = Medicion()
            tiempoDeMedicion = int(self.CalcularTiempoDeMedicionAPosicionFijaBBD(VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm))
            medicion.IniciarVentana(self, tiempoDeMedicion, 1, self.experimento, VectorLongitudDeOndaInicial_nm=VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm=VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm=VectorPasoMono_nm)
        botonMedirAPosicionFija = tk.Button(self.raiz, text="Barrer", command=MedirAPosicionFija, font=(fuente,15))
        botonMedirAPosicionFija.place(x=1580, y=650, height=40, width=115)
                
        # DOBLE BARRIDO #
        def MedirCompletamente():
            VectorPosicionInicialBBD_mm, VectorPosicionFinalBBD_mm, VectorPasoBBD_mm = self.panelBarridoEnDistancia.ObtenerValores()
            VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm = self.panelBarridoEnLongitudesDeOnda.ObtenerValores()
            self.raiz.update()
            medicion = Medicion()
            tiempoDeMedicion = int(self.CalcularTiempoDeMedicionCompleta(VectorPosicionInicialBBD_mm, VectorPosicionFinalBBD_mm, VectorPasoBBD_mm, VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm))
            medicion.IniciarVentana(self, tiempoDeMedicion, 2, self.experimento, VectorPosicionInicialBBD_mm, VectorPosicionFinalBBD_mm, VectorPasoBBD_mm, VectorLongitudDeOndaInicial_nm, VectorLongitudDeOndaFinal_nm, VectorPasoMono_nm)
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

        EstilizarHijos(self.raiz)
        try:
            frameToolbar.configure(bg=COLOR_PANEL, highlightbackground=COLOR_BORDE)
            labelToolbar.configure(bg=COLOR_PANEL, fg=COLOR_TEXTO_SUAVE)
            frameToolbar.lift()
            self.toolbarGrafico.update()
        except Exception:
            pass
        self.raiz.protocol("WM_DELETE_WINDOW", self.Salir)

        self.raiz.mainloop()
        
    def Salir(self):
        if self.experimento.bbd.connected:
            self.experimento.bbd.Cerrar()
            print("BBD301 Desconectado")
        self.experimento.mono.address.close()
        self.raiz.destroy()

    def ActualizarEstado(self, texto):
        if hasattr(self, "labelEstadoGeneral"):
            self.labelEstadoGeneral.config(text="Estado: " + str(texto))
            self.raiz.update_idletasks()
    
    def GrabarDataPuertos(self, puertoSMS, puertoLockIn):
        linea =  str(puertoSMS) + ',' + str(puertoLockIn)
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
            linea = f.readline()
        puertoSMS = linea.split(',')[0]
        puertoLockIn = linea.split(',')[1]
        return puertoSMS, puertoLockIn
    
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
                                            VectorPosicionInicialBBD_mm,
                                            VectorPosicionFinalBBD_mm,
                                            VectorPasoBBD_mm):
        TiempoDeMedicion = 0
        CantidadDeMedicionesTotal = 0
        TiempoDeDesplazamientoTotal = 0
        TiempoDeDesplazamientoPorPaso = 0
        TiempoMuerto = 0
        TiempoMuerto = abs(VectorPosicionInicialBBD_mm[0]-self.experimento.bbd.posicion)/self.experimento.bbd.velocidadMmPorSegundo + tiempoAgregadoPlataforma
        for i in range(0, len(VectorPosicionInicialBBD_mm)):
            if i>0 and VectorPosicionInicialBBD_mm[i] != VectorPosicionFinalBBD_mm[i-1]:
                TiempoMuerto = TiempoMuerto + abs(VectorPosicionInicialBBD_mm[i]-VectorPosicionFinalBBD_mm[i-1])/self.experimento.bbd.velocidadMmPorSegundo + tiempoAgregadoPlataforma
            CantidadDeMediciones = 0
            CantidadDeMediciones = abs(VectorPosicionFinalBBD_mm[i]-VectorPosicionInicialBBD_mm[i])/VectorPasoBBD_mm[i]
            TiempoDeDesplazamientoPorPaso = VectorPasoBBD_mm[i]/self.experimento.bbd.velocidadMmPorSegundo + tiempoAgregadoPlataforma
            TiempoDeDesplazamientoTotal = TiempoDeDesplazamientoTotal + CantidadDeMediciones*TiempoDeDesplazamientoPorPaso
            CantidadDeMedicionesTotal = CantidadDeMedicionesTotal + CantidadDeMediciones
        TiempoDeMedicion = CantidadDeMedicionesTotal*(self.experimento.lockin.TiempoDeIntegracionTotal) + TiempoDeDesplazamientoTotal + TiempoMuerto
        if self.panelPromedioAux.ObtenerPromedioAuxBool():
            TiempoDeMedicion = TiempoDeMedicion + self.panelPromedioAux.ObtenerSegundosAPromediar()
        return TiempoDeMedicion    
    
    def CalcularTiempoDeMedicionAPosicionFijaBBD(self, 
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
                                         VectorPosicionInicialBBD_mm,
                                         VectorPosicionFinalBBD_mm,
                                         VectorPasoBBD_mm,
                                         VectorLongitudDeOndaInicial_nm,
                                         VectorLongitudDeOndaFinal_nm,
                                         VectorPasoMono_nm):
        CantidadDeMovimientosBBDTotal = 0
        TiempoDeDesplazamientoBBD = 0
        TiempoDeDesplazamientoPorPaso = 0
        TiempoDeDesplazamientoMono = 0
        TiempoMuertoBBD = 0
        TiempoMuertoMono = 0
        CantidadDeMovimientosMonoTotal = 0
        largoVectorBBD = len(VectorPosicionInicialBBD_mm)
        TiempoBBDInicial = abs(VectorPosicionInicialBBD_mm[0]-self.experimento.bbd.posicion)/self.experimento.bbd.velocidadMmPorSegundo + tiempoAgregadoPlataforma
        TiempoDeRetornoBBD = abs(VectorPosicionFinalBBD_mm[largoVectorBBD-1]-VectorPosicionInicialBBD_mm[0])/self.experimento.bbd.velocidadMmPorSegundo + tiempoAgregadoPlataforma
        TiempoMonocromadorInicial = abs(VectorLongitudDeOndaInicial_nm[0]-self.experimento.mono.posicion)/self.experimento.mono.velocidadNmPorSegundo + tiempoAgregadoMonocromador
        for i in range(0, len(VectorPosicionInicialBBD_mm)):
            if i>0 and VectorPosicionInicialBBD_mm[i] != VectorPosicionFinalBBD_mm[i-1]:
                TiempoMuertoBBD = TiempoMuertoBBD + (VectorPosicionInicialBBD_mm[i]-VectorPosicionFinalBBD_mm[i-1])/self.experimento.bbd.velocidadMmPorSegundo + tiempoAgregadoPlataforma
            CantidadDeMovimientosBBD = 0
            CantidadDeMovimientosBBD = abs(VectorPosicionFinalBBD_mm[i]-VectorPosicionInicialBBD_mm[i])/VectorPasoBBD_mm[i]
            TiempoDeDesplazamientoPorPaso = VectorPasoBBD_mm[i]/self.experimento.bbd.velocidadMmPorSegundo + tiempoAgregadoPlataforma
            TiempoDeDesplazamientoBBD = TiempoDeDesplazamientoBBD + CantidadDeMovimientosBBD*TiempoDeDesplazamientoPorPaso        
        TiempoBBD = TiempoDeDesplazamientoBBD + TiempoBBDInicial + TiempoMuertoBBD + TiempoDeRetornoBBD        
        for j in range(0, len(VectorLongitudDeOndaInicial_nm)):
            if j>0 and VectorLongitudDeOndaInicial_nm[i] != VectorLongitudDeOndaFinal_nm[i-1]:
                TiempoMuertoMono = TiempoMuertoMono + abs(VectorLongitudDeOndaInicial_nm[j]-VectorLongitudDeOndaFinal_nm[j-1])/self.experimento.mono.velocidadNmPorSegundo + tiempoAgregadoMonocromador
            CantidadDeMovimientosMono = 0
            CantidadDeMovimientosMono = abs(VectorLongitudDeOndaFinal_nm[j]-VectorLongitudDeOndaInicial_nm[j])/VectorPasoMono_nm[j]
            CantidadDeMovimientosMonoTotal = CantidadDeMovimientosMonoTotal + CantidadDeMovimientosMono
            TiempoDeDesplazamientoPorPaso = VectorPasoMono_nm[j]/self.experimento.mono.velocidadNmPorSegundo + tiempoAgregadoMonocromador
            TiempoDeDesplazamientoMono = TiempoDeDesplazamientoMono + CantidadDeMovimientosMono*TiempoDeDesplazamientoPorPaso
        TiempoMonocromador = TiempoDeDesplazamientoMono + TiempoMonocromadorInicial + TiempoMuertoMono
        TiempoBBDTotal = TiempoBBD*CantidadDeMovimientosMonoTotal
        TiempoLockIn = CantidadDeMovimientosBBDTotal*CantidadDeMovimientosMonoTotal*(self.experimento.lockin.TiempoDeIntegracionTotal)       
        TiempoTotal = TiempoMonocromador + TiempoBBDTotal + TiempoLockIn        
        if self.panelPromedioAux.ObtenerPromedioAuxBool():
            TiempoTotal = TiempoTotal + self.panelPromedioAux.ObtenerSegundosAPromediar()
        return TiempoTotal
    
    
# Todo el código que está por encima de esta línea son clases. No hay instancias creadas de las clases, solo 
# sus definiciones. El programa se ejecuta cuando se llama a la línea "programa = Programa()" de aquí abajo.
# Ahí se crea un objeto de la clase Programa que posee en su interior a un objeto de la clase Configuración, un 
# objeto de la clase Experimento y un objeto de la clase Grafico. El objeto de la clase Medicion se crea en cada
# medición y lo mismo pasa con las Advertencias: se crean en cada Advertencia. Dentro del objeto experimento 
# que se encuentra dentro del objeto programa, hay un objeto de la clase BBD, otro de la clase SMS y otro de la 
# clase LockIn. Además el objeto experimento posee un puntero de referencia al mismo objeto grafico creado en el 
# objeto programa.

# Este protocolo no sé si tiene sentido...
if __name__ == "__main__":
    programa = Programa()
