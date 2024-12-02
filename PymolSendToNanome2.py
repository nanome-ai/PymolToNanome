# Avoid importing "expensive" modules here (e.g. scipy), since this code is
# executed on PyMOL's startup. Only import such modules inside functions.

import os
from pymol.Qt import QtCore
from pymol import cmd
import json
import shutil
from math import floor

loading_gif_url = "https://upload.wikimedia.org/wikipedia/commons/b/b1/Loading_icon.gif"
nanome_logo_url = "https://pbs.twimg.com/profile_images/988544354162651137/HQ7nVOtg_400x400.jpg"


def __init_plugin__(app=None):
    '''
    Add an entry to the PyMOL "Plugin" menu
    '''
    from pymol.plugins import addmenuitemqt
    addmenuitemqt('View in Nanome 2', run_plugin_gui)


# global reference to avoid garbage collection of our dialog
dialog = None
login_dialog = None
workspace_api = None
nanome_logo_path = None
sending_thread = None
sending_worker = None


def run_plugin_gui():
    global dialog
    global login_dialog

    dialog = make_dialog()

    if login_dialog is None:
        login_dialog = make_login_dialog()

    if login_dialog is None:
        return

    if workspace_api is None or workspace_api.token is None:
        login_dialog.show()
    else:
        dialog.show()


def make_login_dialog():
    from pymol.Qt import QtWidgets, QtGui

    names = cmd.get_object_list()
    if len(names) < 1:
        msg = "First load a molecular object"
        QtWidgets.QMessageBox.warning(None, "Warning", msg)
        return

    login_dialog = QtWidgets.QDialog()
    login_dialog.setWindowTitle("Nanome Login Credentials")
    login_dialog.setFixedWidth(350)
    login_dialog.setWindowIcon(QtGui.QIcon(nanome_logo_path))

    textName = QtWidgets.QLineEdit(login_dialog)
    textName.setPlaceholderText("Login or email address")
    textPass = QtWidgets.QLineEdit(login_dialog)
    textPass.setPlaceholderText("Password")
    textPass.setEchoMode(QtWidgets.QLineEdit.Password)

    def handle_login():
        global workspace_api
        if len(textPass.text()) == 0 or len(textName.text()) == 0:
            msg = "Please enter your Nanome credentials"
            QtWidgets.QMessageBox.warning(None, "Warning", msg)
            return

        # Get Nanome credential token here !
        workspace_api = WorkspaceAPI(textName.text(), textPass.text())
        reason = workspace_api.get_nanome_token()

        if reason is not None:
            msg = "Failed to login: " + reason
            QtWidgets.QMessageBox.warning(None, "Error", msg)
            return

        dialog.show()
        login_dialog.close()

    buttonLogin = QtWidgets.QPushButton('Login', login_dialog)
    buttonLogin.clicked.connect(handle_login)
    layout = QtWidgets.QVBoxLayout(login_dialog)
    layout.addWidget(textName)
    layout.addWidget(textPass)
    layout.addWidget(buttonLogin)
    return login_dialog


def make_dialog():
    # entry point to PyMOL's API
    import tempfile
    import requests
    from pymol.Qt import QtGui, QtWidgets
    global nanome_logo_path

    loading_gif = requests.get(loading_gif_url)
    gif_temp = tempfile.NamedTemporaryFile(suffix=".gif", delete=False)
    with open(gif_temp.name, "wb") as f:
        f.write(loading_gif.content)

    nanome_jpg = requests.get(nanome_logo_url)
    local_nanome_logo = tempfile.NamedTemporaryFile(
        suffix=".jpg", delete=False)
    nanome_logo_path = local_nanome_logo.name
    with open(nanome_logo_path, "wb") as f:
        f.write(nanome_jpg.content)

    # create a new Window
    dialog = QtWidgets.QDialog()

    dialog.setWindowIcon(QtGui.QIcon(nanome_logo_path))
    dialog.setWindowTitle("Send session to Nanome")
    dialog.setWindowModality(False)
    dialog.setFixedSize(305, 200)
    dialog.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)

    layout = QtWidgets.QVBoxLayout(dialog)

    label = QtWidgets.QLabel()
    gif = QtGui.QMovie(gif_temp.name)
    gif.setScaledSize(QtCore.QSize(305, 200))
    label.setMovie(gif)
    label.hide()

    label_logo = QtWidgets.QLabel()
    pixmap = QtGui.QPixmap(nanome_logo_path).scaled(
        325, 325, QtCore.Qt.KeepAspectRatio, transformMode=QtCore.Qt.SmoothTransformation)
    label_logo.setPixmap(pixmap)
    label_logo.show()

    def close_dialog():
        dialog.close()
        gif.stop()

    def send_to_nanome():
        import tempfile
        global sending_thread, sending_worker
        gif.start()
        label.show()
        label_logo.hide()

        try:
            pse_file = tempfile.NamedTemporaryFile(
                delete=False, suffix=".pse", prefix="Pymol_").name
            cmd.save(pse_file)
            temp_session = PymolToMolz(pse_file).export_to_molz()
            os.remove(pse_file)
        except Exception as e:
            print(f"Could not convert current session to molz file: {e}")
            return

        print("Sending current session file to Nanome")
        gif.start()

        sending_thread = QtCore.QThread()
        sending_worker = Worker()
        sending_worker.session_path = temp_session
        sending_worker.moveToThread(sending_thread)
        sending_thread.started.connect(sending_worker.run)
        sending_worker.finished.connect(sending_thread.quit)
        sending_worker.finished.connect(sending_worker.deleteLater)
        sending_thread.finished.connect(sending_thread.deleteLater)
        sending_thread.finished.connect(close_dialog)
        sending_thread.start()

    buttonSend = QtWidgets.QPushButton('Send session to Nanome', dialog)
    buttonSend.clicked.connect(send_to_nanome)
    layout.addWidget(label)
    layout.addWidget(label_logo)
    layout.addStretch()
    layout.addWidget(buttonSend)

    return dialog


class Worker(QtCore.QObject):
    finished = QtCore.pyqtSignal()
    session_path = ""

    def run(self):
        global workspace_api
        # Send
        workspace_api.send_file(self.session_path)
        self.finished.emit()


class PymolToMolz():
    def __init__(self, pse_path):
        import pickle

        self._pse_path = pse_path
        self._basedir = os.path.dirname(pse_path)
        self._sdf_max_size = 150  # atoms
        
        # Remove atoms that are added by Pymol for missing residues
        cmd.remove("not present and name CA and elem C")

        modified_pse_path = os.path.join(self._basedir, "modified_session.pse")
        cmd.save(modified_pse_path)

        with open(modified_pse_path, "rb") as f:
            self._pse_data = pickle.loads(f.read())


        self._custom_colors = {}
        for i in self._pse_data.get("colors", []):
            self._custom_colors[i[1]] = i[2]

        self._unique_settings = {}
        for i in self._pse_data["unique_settings"]:
            self._unique_settings[i[0]] = i[1]

        self._workspace_settings_colors = {
            'surface': None,
            'mesh': None,
            'cartoon': None,
            'ribbon': None,
            'line': None,
            'sphere': None,
            'ball-and-stick': None,
            'stick': None,
            'label': None,
        }

        for setting in self._pse_data["settings"]:
            if setting[0] == 144 and setting[2] >= 0:
                self._workspace_settings_colors["surface"] = setting[2]
            elif setting[0] == 236 and setting[2] >= 0:
                self._workspace_settings_colors["cartoon"] = setting[2]
            elif setting[0] == 235 and setting[2] >= 0:
                self._workspace_settings_colors["ribbon"] = setting[2]
            elif setting[0] == 526 and setting[2] >= 0:
                self._workspace_settings_colors["line"] = setting[2]
            elif setting[0] == 146 and setting[2] >= 0:
                self._workspace_settings_colors["mesh"] = setting[2]
            elif setting[0] == 173 and setting[2] >= 0:
                self._workspace_settings_colors["sphere"] = setting[2]
            elif setting[0] == 376 and setting[2] >= 0:
                self._workspace_settings_colors["ball-and-stick"] = setting[2]

        self._pse_molecules = {}
        for d in self._pse_data["names"][1:]:
            if d[4] == 1:
                self._pse_molecules[d[0]] = d

    def int2reps(self, rep):
        reps = set()
        if rep == 0:
            return reps
        show_stick = rep & 1 != 0
        show_sphere = rep & 2 != 0
        nb_sphere = rep & 16 != 0
        ignore_nb_sphere = False
        if show_stick and show_sphere:
            reps.add("ball-and-stick")
            ignore_nb_sphere = True
        elif show_stick and not show_sphere:
            ignore_nb_sphere = True
            reps.add("stick")
        elif not show_stick and show_sphere:
            ignore_nb_sphere = True
            reps.add("sphere")
        if rep & 4:
            reps.add("surface")
        if rep & 8:
            reps.add("label")
        if nb_sphere and not ignore_nb_sphere:
            reps.add("sphere")
        if rep & 32:
            reps.add("cartoon")
        if rep & 128:
            reps.add("line")
        return list(reps)

    def color_to_rgb(self, id):
        if id in self._custom_colors:
            return [floor(color * 255) for color in self._custom_colors[id]] + [255]
        c = cmd.get_color_tuple(id)
        return [floor(color * 255) for color in c] + [255]

    def save_structures(self, assets_dir):
        structures = []
        name_map = {}
        for mol_name in cmd.get_names_of_type('object:molecule'):
            if cmd.count_atoms(mol_name + " and present") < self._sdf_max_size:
                output_sdf = os.path.join(
                    assets_dir, mol_name.replace(' ', '_') + ".sdf")
                cmd.save(output_sdf, mol_name, state=0)
                basename = os.path.basename(output_sdf)
                name_map[mol_name] = basename
                structures.append({
                    "Name": mol_name,
                    "Extension": "sdf",
                    "Identifier": name_map[mol_name]
                })
            else:
                output_cif = os.path.join(
                    assets_dir, mol_name.replace(' ', '_') + ".cif")
                cmd.save(output_cif, mol_name, state=0)
                basename = os.path.basename(output_cif)
                name_map[mol_name] = basename
                structures.append({
                    "Name": mol_name,
                    "Extension": "cif",
                    "Identifier": name_map[mol_name]
                })
        return structures, name_map

    def get_setting_color(self, settings, rep_name):
        # https://github.com/schrodinger/pymol-open-source/blob/abd9579a97b9864c6a40ba7b91dd330ef64d14a5/layer1/SettingInfo.h
        for s in settings:
            if s[0] == 236 and rep_name == "cartoon":
                return s[2]
            if s[0] == 235 and rep_name == "ribbon":
                return s[2]
            if s[0] == 526 and rep_name == "line":
                return s[2]
            if s[0] == 144 and rep_name == "surface":
                return s[2]
            if s[0] == 146 and rep_name == "mesh":
                return s[2]
            if s[0] == 173 and rep_name == "ball-and-stick":
                return s[2]
            # stick color in bond
            if s[0] == 376 and "stick" in rep_name:
                return s[2]

    def get_representations(self, mol_name, name_map):
        if not mol_name in self._pse_molecules:
            return []
        pse_data = self._pse_molecules[mol_name]
        enabled = pse_data[2] == 1
        atom_data = pse_data[5][7]
        bond_data = pse_data[5][6]
        flags = pse_data[3]
        # Not used for now
        if flags:
            show_stick = flags[0] == 1 or flags[4] == 1
            show_sphere = flags[1] == 1
            show_surface = flags[2] == 1
            show_label = flags[3] == 1
            show_nbSphere = flags[4] == 1
            show_ribbon = flags[5] == 1
            show_line = flags[7] == 1

        complex_settings = pse_data[5][0][8]
        complex_custom_colors = {
            'surface': None,
            'mesh': None,
            'cartoon': None,
            'ribbon': None,
            'line': None,
            'sphere': None,
            'ball-and-stick': None,
            'stick': None,
            'label': None,
        }
        if complex_settings:
            for setting in complex_settings:
                # if setting[0] == 138 and setting[2] >= 0:
                # complex_custom_colors["surface_transparency"] = setting[2]
                if setting[0] == 144 and setting[2] >= 0:
                    complex_custom_colors["surface"] = setting[2]
                elif setting[0] == 236 and setting[2] >= 0:
                    complex_custom_colors["cartoon"] = setting[2]
                elif setting[0] == 235 and setting[2] >= 0:
                    complex_custom_colors["ribbon"] = setting[2]
                elif setting[0] == 526 and setting[2] >= 0:
                    complex_custom_colors["line"] = setting[2]
                elif setting[0] == 146 and setting[2] >= 0:
                    complex_custom_colors["mesh"] = setting[2]
                elif setting[0] == 173 and setting[2] >= 0:
                    complex_custom_colors["sphere"] = setting[2]
                elif setting[0] == 376 and setting[2] >= 0:
                    complex_custom_colors["ball-and-stick"] = setting[2]

        states = set([i[34] for i in atom_data])
        components = []

        custom_bonds = {}
        for b in bond_data:
            if b[6] == 1:
                custom_bonds[b[0]] = b[5]
                custom_bonds[b[1]] = b[5]

        for state in states:
            colors = []
            unique_setting_id = []
            ribbon_mode = []
            representations = []
            for a in atom_data:
                if a[34] == state:
                    ribbon_mode.append(a[23])
                    colors.append(a[21])
                    unique_setting_id.append(a[32] if a[40] != 0 else -1)
                    representations.append(a[20])

            rep_types = set(representations)
            rep_types_s = set([j for i in rep_types for j in self.int2reps(i)])
            data_per_rep = {}
            for r in rep_types_s:
                data_per_rep[r] = []

            for i, r in enumerate(representations):
                for rs in self.int2reps(r):
                    data_per_rep[rs].append(i)

            for rep_name in data_per_rep:
                cols = [colors[c] for c in data_per_rep[rep_name]]

                # Use unique settings
                for i, aId in enumerate(data_per_rep[rep_name]):
                    has_custom_color = False
                    if unique_setting_id[aId] >= 0:
                        settings = self._unique_settings.get(
                            unique_setting_id[aId], [])
                        custom_col = self.get_setting_color(settings, rep_name)
                        if custom_col is not None and custom_col >= 0:
                            cols[i] = custom_col
                            has_custom_color = True

                    # Look for bond unique colors
                    if not has_custom_color and aId in custom_bonds:
                        usetting_id = custom_bonds[aId]
                        settings = self._unique_settings.get(usetting_id, [])
                        custom_col = self.get_setting_color(settings, rep_name)
                        if custom_col is not None and custom_col >= 0:
                            cols[i] = custom_col
                            has_custom_color = True

                    # Try to use complex setting
                    if not has_custom_color and rep_name in complex_custom_colors and complex_custom_colors[rep_name]:
                        cols[i] = complex_custom_colors[rep_name]
                        has_custom_color = True

                    # Try to use workspace setting
                    if not has_custom_color and self._workspace_settings_colors[rep_name]:
                        cols[i] = self._workspace_settings_colors[rep_name]

                color_set = list(set(cols))
                rep = {
                    "Kind": rep_name.replace("sphere", "spacefill"),
                    "ColorScheme": {
                        "Library": [self.color_to_rgb(c) for c in color_set],
                        "Colors": [color_set.index(c) for c in cols],
                    },
                    "SizeScheme": {
                        "Kind": "uniform",
                        "Scale": 1.0,
                        "BFactorFactor": 0.0
                    },
                    "Parameters": {}
                }
                state_id = state - 1 if len(states) != 1 else 0
                component = {
                    "Structure": name_map[mol_name],
                    "Name": rep_name[0].upper() + rep_name[1:].lower(),
                    "Model": state_id,
                    "Selection": data_per_rep[rep_name],
                    "Representations": [rep],
                    "Hidden": not enabled
                }
                components.append(component)
        return components

    def create_state_file(self, main_dir, structures, components):
        state = {"Version": "0.0.1",
                 "Structures": structures,
                 "Components": components
                 }
        with open(os.path.join(main_dir, "state.json"), "w") as f:
            json.dump(state, f)

    def create_molz_archive(self, main_dir):
        final_path = main_dir + ".molz"
        shutil.make_archive(main_dir, "zip", main_dir)
        shutil.rmtree(main_dir)
        os.rename(main_dir + ".zip", final_path)
        return final_path

    def prepare_molz_directories(self):
        main_dir = os.path.splitext(os.path.basename(self._pse_path))[0]
        assets_dir = os.path.join(main_dir, "assets")
        os.makedirs(assets_dir)
        return main_dir, assets_dir

    def export_to_molz(self):
        main_dir, assets_dir = self.prepare_molz_directories()
        structures, name_map = self.save_structures(assets_dir)

        # Get the representation per structure
        components = []

        for mol_name in name_map:
            components.extend(
                self.get_representations(mol_name, name_map))

        self.create_state_file(main_dir, structures, components)
        molz_path = self.create_molz_archive(main_dir)
        cmd.load(self._pse_path)
        return molz_path


class WorkspaceAPI():
    def __init__(self, username, passw):
        self.token = None
        self.username = username
        self.password = passw
        self.login_url = "https://api.nanome.ai/user/login"
        self.load_url = "https://workspace-service-api.nanome.ai/load/workspace"

    def get_nanome_token(self):
        import requests
        token_request_dict = {"login": self.username,
                              "pass": self.password, "source": "api:pymol-plugin"}
        self.username = None
        self.password = None
        r = requests.post(self.login_url, json=token_request_dict, timeout=5.0)
        if r.ok:
            response = r.json()
            result = response["results"]
            self.token = result["token"]["value"]
        else:
            self.token = 0
            print("Error getting Nanome login token:", r.reason)
            return r.reason

    def send_file(self, filepath):
        import requests

        if self.token is None:
            r_token = self.get_nanome_token()

        if self.token == 0:
            self.token = None
            return r_token

        formData = {'load-in-headset': True, 'format': 'molz'}
        with open(filepath, 'rb') as f:
            data = f.read()
        files = {os.path.splitext(os.path.basename(filepath))[0]: data}
        headers = {'Authorization': f'Bearer {self.token}'}
        result = requests.post(
            self.load_url, headers=headers, data=formData, files=files)
        if not result.ok:
            print(
                f"Could not send the session file to Nanome: {result.reason}")
        else:
            print("Successfully sent the current session to Nanome !")
        os.remove(filepath)
