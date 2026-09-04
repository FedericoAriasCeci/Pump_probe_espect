import datetime
import json
import os


CARPETA_CODIGO = os.path.dirname(os.path.abspath(__file__))


class SessionPaths:
    def __init__(self, root_path):
        self.root_path = root_path
        self.raw_csv = os.path.join(root_path, "raw.csv")
        self.average_csv = os.path.join(root_path, "promedio.csv")
        self.metadata_json = os.path.join(root_path, "metadata.json")
        self.notes_txt = os.path.join(root_path, "notes.txt")
        self.log_txt = os.path.join(root_path, "log.txt")
        self.plots_path = os.path.join(root_path, "plots")


class SessionManager:
    def __init__(self, base_dir=None):
        if base_dir is None:
            base_dir = os.path.join(CARPETA_CODIGO, "Mediciones")
        self.base_dir = base_dir

    def ensure_base_dir(self):
        if not os.path.isdir(self.base_dir):
            os.makedirs(self.base_dir)

    def next_session_path(self, date_value=None):
        if date_value is None:
            date_value = datetime.date.today()
        self.ensure_base_dir()
        prefix = date_value.strftime("%Y-%m-%d")
        index = 1
        while True:
            name = prefix + "_" + str(index).zfill(3)
            path = os.path.join(self.base_dir, name)
            if not os.path.exists(path):
                return path
            index = index + 1

    def create_session(self, preferred_path=None):
        self.ensure_base_dir()
        if preferred_path is None:
            path = self.next_session_path()
        else:
            path = preferred_path
            if os.path.exists(path):
                path = self.next_session_path()
        if not os.path.isdir(path):
            os.makedirs(path)
        paths = SessionPaths(path)
        if not os.path.isdir(paths.plots_path):
            os.makedirs(paths.plots_path)
        return paths

    def write_metadata(self, paths, metadata):
        with open(paths.metadata_json, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2, sort_keys=True)

    def write_notes(self, paths, notes):
        with open(paths.notes_txt, "w", encoding="utf-8") as handle:
            handle.write(notes or "")

    def write_log(self, paths, log_lines):
        with open(paths.log_txt, "w", encoding="utf-8") as handle:
            for line in log_lines or []:
                handle.write(str(line) + "\n")

    def write_session_files(self, paths, metadata, notes, log_lines):
        self.write_metadata(paths, metadata)
        self.write_notes(paths, notes)
        self.write_log(paths, log_lines)
