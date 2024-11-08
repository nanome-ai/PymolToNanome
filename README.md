# Pymol-to-Nanome

Pymol plugin to send the current session to Nanome 2

# How to install and use

- Open Pymol Plugin Manager → Install New Plugin tab → Install from PyMOLWiki or any URL → https://github.com/nanome-ai/PymolToNanome/blob/master/PymolSendToNanome2.py → Fetch

### Once installed, you can start the plugin

Plugin → View in Nanome 2

### Usage

- Login with your Nanome credentials
- Click on "Send session to Nanome" button
- If Nanome is not already opened, the next time you open Nanome it will load the Pymol session file
- If Nanome is opened, you should see the Pymol session file loaded

# Example

![alt text](https://i.postimg.cc/pyR9KhTP/Pymol-Example-quickdrop.jpg)

## Explanations

This scripts exports the current session to a PSE file, extracts molecules to PDB files or SDF files (<150 atoms), also extracts molecular representations.
Then it creates a .molz file and send it to Nanome 2 using a token retrieved via your credentials.


