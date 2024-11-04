from pymol import cmd
import math
import os
import json
import shutil
import tempfile


def int2reps(rep):
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


def color_to_rgb(id):
    c = cmd.get_color_tuple(id)
    return [math.floor(color * 255) for color in c] + [255]


def prepare_molz_directories():
    main_dir = tempfile.TemporaryDirectory(prefix="workspaceJson_").name
    assets_dir = os.path.join(main_dir, "assets")
    os.makedirs(assets_dir)
    return main_dir, assets_dir


def save_structures(assets_dir):
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


def get_representations_per_structure(mol_name, name_map):
    components = []
    representations = []
    colors = []
    cmd.iterate("model " + mol_name + " and enabled",
                "representations.append(reps); colors.append(color)")

    rep_types = set(representations)
    rep_types_s = set([j for i in rep_types for j in int2reps(i)])

    data_per_rep = {}
    for r in rep_types_s:
        data_per_rep[r] = []

    for i, r in enumerate(representations):
        for rs in int2reps(r):
            data_per_rep[rs].append(i)

    for i in data_per_rep:
        cols = [colors[c] for c in data_per_rep[i]]
        color_set = list(set(cols))

        rep = {
            "Kind": i,
            "ColorScheme": {
                "Library": [color_to_rgb(c) for c in color_set],
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


def create_state_file(main_dir, structures, components):
    state = {"Version": "0.0.1",
             "Structures": structures,
             "Components": components
             }
    with open(os.path.join(main_dir, "state.json"), "w") as f:
        json.dump(state, f)


def create_molz_archive(main_dir):
    final_path = main_dir + ".molz"
    shutil.make_archive(main_dir, "zip", main_dir)
    shutil.rmtree(main_dir)
    os.rename(main_dir + ".zip", final_path)
    return final_path


def export_to_molz():
    # Remove atoms that are added by Pymol for missing residues
    cmd.remove("not present")

    main_dir, assets_dir = prepare_molz_directories()
    structures, name_map = save_structures(assets_dir)

    # Get the representation per structure
    components = []

    for mol_name in cmd.get_names('objects'):
        components.extend(
            get_representations_per_structure(mol_name, name_map))

    create_state_file(main_dir, structures, components)
    molz_path = create_molz_archive(main_dir)
    print(f"Created molz workspace file: {molz_path}")


if __name__ == "__main__":
    export_to_molz()
