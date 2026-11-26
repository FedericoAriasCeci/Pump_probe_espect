"""Doble del servicio ICL (WebSocket JSON) para pruebas sin equipo ni licencia.

Basado en el FakeICL del software de calibración del iHR320: responde los
comandos de la API 300 que usa este programa y simula homing, movimiento de λ
y de rendijas con algunas consultas de mono_isBusy en estado ocupado.
"""
import json


class FakeICL:
    def __init__(self):
        self.commands = []
        self.position, self.grating = 532., 0
        self.busy, self.initialized = False, True
        self.error, self.offset, self.closed = None, 0, False
        self.pending = None
        self.initializing = False
        self.init_busy_polls = 1
        self.move_busy_polls = 0
        self.move_pending = None
        self.slits = {1: .1, 4: .1}
        self.ports = [dict(locationId=1, slitType=2), dict(locationId=4, slitType=2)]
        self.slit_pending = None
        self.slit_busy_polls = 1
        self.mirrors = {0: 0, 1: 1}
        self.gratings = [dict(positionIndex=i, grooveDensity=d, blaze=0) for i, d in enumerate((1200, 600, 300))]
        self.api_version = 300
        self.on_command = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def send(self, payload):
        self.pending = json.loads(payload)
        self.commands.append(self.pending)
        if self.on_command is not None:
            self.on_command(self.pending)

    def names(self):
        return [c["command"] for c in self.commands]

    def recv(self):
        cmd = self.pending["command"]
        params = self.pending.get("parameters") or {}
        if cmd == "mono_init":
            self.initializing, self.busy, self.initialized = True, True, False
        if cmd == "mono_isBusy" and self.initializing:
            self.busy = self.init_busy_polls > 0
            self.init_busy_polls -= 1
            if not self.busy:
                self.initializing = False
                self.initialized = True
        if cmd == "mono_moveToPosition" and not self.error:
            self.move_pending = params["wavelength"], self.move_busy_polls
            self.busy = self.move_busy_polls > 0
            if not self.busy:
                self.position = params["wavelength"]
                self.move_pending = None
        if cmd == "mono_isBusy" and self.move_pending:
            target, remaining = self.move_pending
            self.busy = remaining > 0
            if self.busy:
                self.move_pending = target, remaining - 1
            else:
                self.position = target
                self.move_pending = None
        if cmd == "mono_moveSlitMM" and not self.error:
            self.slit_pending = params["locationId"], params["position"], self.slit_busy_polls
        if cmd == "mono_isBusy" and self.slit_pending:
            location, target, remaining = self.slit_pending
            self.busy = remaining > 0
            if self.busy:
                self.slit_pending = location, target, remaining - 1
            else:
                # ICL informa float32, como el equipo real.
                self.slits[location] = float(json.loads(json.dumps(target)))
                self.slit_pending = None
        results = {
            "icl_info": {"nodeApiVersion": self.api_version, "nodeVersion": "test"},
            "mono_discover": {"count": 1},
            "mono_list": {"devices": [{"index": 0, "deviceType": "iHR320", "serialNumber": "TEST-IHR320"}]},
            "mono_isBusy": {"busy": self.busy},
            "mono_isInitialized": {"initialized": self.initialized},
            "mono_getPosition": {"wavelength": self.position + self.offset},
            "mono_getGratingPosition": {"position": self.grating},
            "mono_getConfig": {"configuration": {"model": "iHR320", "ports": self.ports, "gratings": self.gratings}},
            "mono_getSlitPositionInMM": {"position": self.slits.get(params.get("locationId"))},
            "mono_getMirrorPosition": {"position": self.mirrors.get(params.get("locationId"))},
        }.get(cmd, {})
        return json.dumps(dict(id=self.pending["id"], command=cmd, results=results,
                               errors=[self.error] if self.error else []))

    def close(self):
        self.closed = True


def fake_factory(fake):
    """controller_factory para HoribaMonochromator que usa el doble ``fake``."""
    from horiba_icl import ICLMonochromator

    def factory(settings):
        return ICLMonochromator(settings, socket_factory=lambda *args, **kwargs: fake)
    return factory
