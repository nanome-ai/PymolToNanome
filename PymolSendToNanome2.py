# Avoid importing "expensive" modules here (e.g. scipy), since this code is
# executed on PyMOL's startup. Only import such modules inside functions.

import os
from pymol.Qt import QtCore
from pymol import cmd
import json
import shutil

loading_gif_url = "https://upload.wikimedia.org/wikipedia/commons/b/b1/Loading_icon.gif"
nanome_logo_url = "https://pbs.twimg.com/profile_images/988544354162651137/HQ7nVOtg_400x400.jpg"

def __init_plugin__(app=None):
    '''
    Add an entry to the PyMOL "Plugin" menu
    '''
    from pymol.plugins import addmenuitemqt
    addmenuitemqt('View in Nanome XR', run_plugin_gui)


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
    textName.setPlaceholderText("Email Address")
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
    local_nanome_logo = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
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
    pixmap = QtGui.QPixmap(nanome_logo_path).scaled(325, 325, QtCore.Qt.KeepAspectRatio, transformMode=QtCore.Qt.SmoothTransformation)
    label_logo.setPixmap(pixmap)
    label_logo.show()
    
    def close_dialog():
        dialog.close()
        gif.stop()

    def send_to_nanome():
        global sending_thread, sending_worker
        gif.start()
        label.show()
        label_logo.hide()

        temp_session = PymolToMolz().export_to_molz()

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
        #Send
        workspace_api.send_file(self.session_path)
        self.finished.emit()

class PymolToMolz():
    
    def int2reps(self, rep):
        reps = []
        if rep == 0:
            return reps
        if rep & 1:
            reps.append("ball-and-stick")
        if rep & 2:
            reps.append("sphere")
        if rep & 4:
            reps.append("surface")
        if rep & 8:
            reps.append("label")
        if rep & 16:
            reps.append("sphere")
        if rep & 32:
            reps.append("cartoon")
        if rep & 128:
            reps.append("line")
        return reps


    def color_to_rgb(self, id):
        from math import floor
        c = cmd.get_color_tuple(id)
        return [floor(color * 255) for color in c] + [255]


    def prepare_molz_directories(self):
        import tempfile
        main_dir = tempfile.TemporaryDirectory(prefix="workspaceJson_").name
        assets_dir = os.path.join(main_dir, "assets")
        os.makedirs(assets_dir)
        return main_dir, assets_dir


    def save_structures(self, assets_dir):
        import tempfile
        structures = []
        name_map = {}
        for mol_name in cmd.get_names('objects'):
            output_cif = tempfile.NamedTemporaryFile(
                prefix=mol_name.replace(' ', '_')+"_",
                suffix=".cif", delete=False, dir=assets_dir).name
            cmd.save(output_cif, mol_name)
            basename = os.path.basename(output_cif)
            name_map[mol_name] = basename
            structures.append({"Name": mol_name, "Extension": "cif",
                            "Identifier": name_map[mol_name]})
        return structures, name_map


    def get_representations_per_structure(self, mol_name, name_map):
        components = []
        representations = []
        colors = []
        cmd.iterate("model " + mol_name + " and enabled",
                    "representations.append(reps); colors.append(color)")

        rep_types = set(representations)
        rep_types_s = set([j for i in rep_types for j in self.int2reps(i)])

        data_per_rep = {}
        for r in rep_types_s:
            data_per_rep[r] = []

        for i, r in enumerate(representations):
            for rs in self.int2reps(r):
                data_per_rep[rs].append(i)

        for i in data_per_rep:
            cols = [colors[c] for c in data_per_rep[i]]
            color_set = list(set(cols))

            rep = {
                "Kind": i,
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
            component = {
                "Structure": name_map[mol_name],
                "Name": i[0].upper() + i[1:].lower(),
                "Model": 0,
                "Selection": data_per_rep[i],
                "Representations": [rep]
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


    def export_to_molz(self):
        # Remove atoms that are added by Pymol for missing residues
        cmd.remove("not present")

        main_dir, assets_dir = self.prepare_molz_directories()
        structures, name_map = self.save_structures(assets_dir)

        # Get the representation per structure
        components = []

        for mol_name in cmd.get_names('objects'):
            components.extend(
                self.get_representations_per_structure(mol_name, name_map))

        self.create_state_file(main_dir, structures, components)
        molz_path = self.create_molz_archive(main_dir)
        print(f"Created molz workspace file: {molz_path}")
        return molz_path

class WorkspaceAPI():
    def __init__(self, username, passw):
        self.token = None
        self.username = username
        self.password = passw
        self.login_url = "https://api.nanome.ai/user/login"
        self.load_url = "https://nanome-service.dev.nanome.ai/load/workspace"

    def get_nanome_token(self):
        import requests
        token_request_dict = {"login": self.username, "pass": self.password, "source": "api:pymol-plugin"}
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
        
        formData = {'load-in-headset': 'true', 'file': filepath, 'format': 'molz'}
        headers = {'Authorization': f'Bearer {self.token}'}
        result = requests.post(self.load_url, headers=headers, json=formData)
        if not result.ok:
            print(f"Could not send the session file to Nanome: {result.reason}")
            return
        print("Successfully sent the current session to Nanome !")
        
