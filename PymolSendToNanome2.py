# Avoid importing "expensive" modules here (e.g. scipy), since this code is
# executed on PyMOL's startup. Only import such modules inside functions.

import os
from pymol.Qt import QtCore

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
    from pymol import cmd
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
    from pymol import cmd
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

        temp_session = tempfile.NamedTemporaryFile(suffix=".pse", delete=False)
        cmd.save(temp_session.name)
        print("Saved session file to", temp_session.name)

        print("Sending current session file to Nanome")
        gif.start()

        sending_thread = QtCore.QThread()
        sending_worker = Worker()
        sending_worker.session_path = temp_session.name
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

class WorkspaceAPI():
    def __init__(self, username, passw):
        self.token = None
        self.username = username
        self.password = passw
        self.login_url = "https://api.nanome.ai/user/login"
        self.load_url = "/load/workspace"

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
        from datetime import datetime
        import requests
        import pymol2molz
        
        if self.token is None:
            r_token = self.get_nanome_token()
        
        if self.token == 0:
            self.token = None
            return r_token
        
        try:
            molz_file = pymol2molz.export_to_molz()
        except Exception as e:
            print(f"Error during conversion to .molz file: {e}")
        
        formData = {'load-in-headset': 'true', 'file': molz_file, 'format': 'molz'}
        headers = {'Authorization': f'Bearer {self.token}'}
        result = requests.post(self.load_url, headers=headers, json=formData)
        if not result.ok:
            print(f"Could not send the session file to Nanome: {result.reason}")
            return
        print("Successfully sent the current session to Nanome !")
        
