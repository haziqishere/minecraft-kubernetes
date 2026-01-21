import json
from pathlib import Path
from typing import Union

def get_json_config(config_file_path: Union[str, Path]):
    """Returns content of json config file"""

    with open(config_file_path, "r") as config_file:
        return json.load(config_file)