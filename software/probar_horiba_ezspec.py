"""Prueba manual independiente del iHR320. Sin argumentos: consulta de estado.

Ejemplos (opciones comunes antes del subcomando):
    python probar_horiba_ezspec.py discover
    python probar_horiba_ezspec.py --device-id 0 status
    python probar_horiba_ezspec.py --device-id 0 init
    python probar_horiba_ezspec.py --device-id 0 move 532
    python probar_horiba_ezspec.py --device-id 0 --initialize scan 500 510 2

No importa ni modifica el codigo de medicion. ICL debe estar en ejecucion.
"""

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal
import json
import math
from pathlib import Path
import sys
import time

from horiba_ezspec import HoribaError, HoribaEzSpec


def _number(text):
    try:
        value = float(text)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("Se esperaba un numero.") from exc
    if not math.isfinite(value):
        raise argparse.ArgumentTypeError("El numero debe ser finito.")
    return value


def _nonnegative(text):
    value = _number(text)
    if value < 0:
        raise argparse.ArgumentTypeError("El numero debe ser >= 0.")
    return value


def _positive(text):
    value = _number(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("El numero debe ser > 0.")
    return value


def scan_points(start, stop, step):
    """Puntos sin sobrepasar el extremo, ascendentes o descendentes."""
    start, stop, step = (Decimal(str(value)) for value in (start, stop, step))
    if not all(value.is_finite() for value in (start, stop, step)):
        raise ValueError("El barrido requiere numeros finitos.")
    if start < 0 or stop < 0 or step == 0 or (stop - start) * step < 0:
        raise ValueError("Revise extremos y signo del paso; el paso no puede ser cero.")
    count = int((stop - start) / step) + 1
    if count > 100000:
        raise ValueError("El barrido supera 100000 puntos.")
    return [float(start + i * step) for i in range(count)]


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1", help="Direccion del servicio ICL.")
    parser.add_argument("--port", type=int, default=25010)
    parser.add_argument("--device-id", type=int, help="ID numerico de discover; no es un puerto COM ni Mono1.")
    parser.add_argument("--connection-timeout", type=_positive, default=60.0, metavar="S")
    parser.add_argument("--motion-timeout", type=_positive, default=180.0, metavar="S")
    parser.add_argument("--poll-interval", type=_positive, default=0.1, metavar="S")
    parser.add_argument("--tolerance-nm", type=_positive, default=0.05)
    parser.add_argument("--limits-nm", nargs=2, type=_nonnegative, metavar=("MIN", "MAX"),
                        help="Limites experimentales de lambda, dependientes de la red instalada.")
    parser.add_argument("--initialize", action="store_true", help="Inicializar si hace falta antes de un comando de control.")
    parser.add_argument("--report", type=Path, help="Guardar diagnostico JSON; exige un archivo nuevo.")
    parser.add_argument("--debug", action="store_true", help="Habilitar registro detallado del SDK.")
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("discover", help="Listar IDs, modelos y configuraciones sin homing.")
    sub.add_parser("status", help="Consultar estado sin mover (opcion predeterminada).")
    sub.add_parser("config", help="Mostrar configuracion y accesorios instalados.")
    init = sub.add_parser("init", help="Inicializar si hace falta y esperar reposo.")
    init.add_argument("--force", action="store_true", help="Repetir el homing aunque ya este inicializado.")
    move = sub.add_parser("move", help="Mover a una longitud de onda y verificar la lectura.")
    move.add_argument("wavelength_nm", type=_nonnegative)
    scan = sub.add_parser("scan", help="Barrido de posiciones; CSV sin lecturas de intensidad.")
    scan.add_argument("start_nm", type=_nonnegative)
    scan.add_argument("stop_nm", type=_nonnegative)
    scan.add_argument("step_nm", type=_number)
    scan.add_argument("--settle-s", type=_nonnegative, default=0.0, help="Espera adicional por punto.")
    scan.add_argument("--output-csv", type=Path, help="Archivo nuevo para posiciones comandadas y leidas.")
    grating = sub.add_parser("grating", help="Seleccionar red y verificar; numeros de usuario 1 a 3.")
    grating.add_argument("number", type=int, choices=(1, 2, 3))
    slit = sub.add_parser("slit", help="Ajustar una rendija motorizada (ancho en mm).")
    slit.add_argument("slit", type=str.upper, choices=("A", "B", "C", "D"))
    slit.add_argument("width_mm", type=_nonnegative)
    mirror = sub.add_parser("mirror", help="Seleccionar puerto axial o lateral.")
    mirror.add_argument("mirror", choices=("entrance", "exit"))
    mirror.add_argument("position", choices=("axial", "lateral"))
    shutter = sub.add_parser("shutter", help="Abrir o cerrar el obturador instalado.")
    shutter.add_argument("position", choices=("open", "closed"))
    return parser


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _scan(mono, args, points, report):
    path = args.output_csv or Path("horiba_scan_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv")
    report["csv"] = str(path.resolve())
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("commanded_nm", "reported_nm", "elapsed_s", "utc"))
        writer.writeheader()
        stream.flush()
        started = time.monotonic()
        for point in points:
            actual = mono.move_to(point)
            if args.settle_s:
                time.sleep(args.settle_s)
            row = {"commanded_nm": point, "reported_nm": actual,
                   "elapsed_s": round(time.monotonic() - started, 6), "utc": _utc()}
            writer.writerow(row)
            stream.flush()  # Conservar puntos completados ante Ctrl+C o fallo posterior.
            report["points_completed"] = report.get("points_completed", 0) + 1
            print(str(point) + " nm -> " + str(actual) + " nm", flush=True)
    print("CSV: " + str(path.resolve()))


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    action = args.action or "status"
    if args.initialize and action in ("discover", "status", "config"):
        parser.error("--initialize solo se admite para comandos de control. Use init para hacer homing.")
    try:
        mono = HoribaEzSpec(
            device_id=args.device_id, host=args.host, port=args.port,
            connection_timeout_s=args.connection_timeout, motion_timeout_s=args.motion_timeout,
            poll_interval_s=args.poll_interval, wavelength_tolerance_nm=args.tolerance_nm,
            wavelength_limits_nm=args.limits_nm, enable_logging=args.debug,
        )
        points = scan_points(args.start_nm, args.stop_nm, args.step_nm) if action == "scan" else []
        # Validar todo el recorrido antes de enviar el primer movimiento.
        for point in points:
            mono.validate_wavelength(point)
        if action == "move":
            mono.validate_wavelength(args.wavelength_nm)
        if action == "scan" and args.output_csv and args.output_csv.exists():
            raise ValueError("El CSV ya existe: " + str(args.output_csv))
        if args.report and action == "scan" and args.output_csv and args.report.resolve() == args.output_csv.resolve():
            raise ValueError("El informe JSON y el CSV requieren archivos distintos.")
    except (ValueError, TypeError) as exc:
        parser.error(str(exc))

    report = {"started_utc": _utc(), "action": action, "host": args.host, "port": args.port, "ok": False}
    report_stream = None
    try:
        # Reservar el informe antes de tocar hardware; nunca sobrescribir resultados.
        if args.report:
            report_stream = args.report.open("x", encoding="utf-8")
        if action == "discover":
            report["devices"] = HoribaEzSpec.discover(
                host=args.host, port=args.port, connection_timeout_s=args.connection_timeout,
                enable_logging=args.debug,
            )
            print(json.dumps(report["devices"], indent=2, ensure_ascii=False))
        else:
            with mono:
                report["status_before"] = mono.get_status()
                if action == "init":
                    report["wavelength_nm"] = mono.initialize(force=args.force)
                elif action == "config":
                    report["configuration"] = mono.get_configuration()
                elif action != "status":
                    if args.initialize:
                        mono.initialize()
                    if action == "move":
                        report["wavelength_nm"] = mono.move_to(args.wavelength_nm)
                    elif action == "scan":
                        _scan(mono, args, points, report)
                    elif action == "grating":
                        report["grating"] = mono.set_grating(args.number)
                    elif action == "slit":
                        report["slit_width_mm"] = mono.set_slit_width(args.slit, args.width_mm)
                    elif action == "mirror":
                        report["mirror_position"] = mono.set_mirror(args.mirror, args.position)
                    elif action == "shutter":
                        report["shutter_position"] = mono.set_shutter(args.position == "open")
                report["status_after"] = mono.get_status()
        report["ok"] = True
        if action != "discover":
            print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except KeyboardInterrupt:
        report["error"] = "Interrumpido por el usuario; el movimiento enviado puede continuar."
        print(report["error"], file=sys.stderr)
        return 130
    except (HoribaError, OSError, ValueError) as exc:
        report["error"] = str(exc)
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    finally:
        report["finished_utc"] = _utc()
        if report_stream is not None:
            with report_stream:
                json.dump(report, report_stream, indent=2, ensure_ascii=False)
                report_stream.write("\n")


if __name__ == "__main__":
    sys.exit(main())
