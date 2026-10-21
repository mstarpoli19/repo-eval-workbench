"""Negative controls: no targets for the four deliberately narrow rules."""

import json
import subprocess


def remember(value, history=None):
    history = [] if history is None else list(history)
    history.append(value)
    return history


def parse_settings(text):
    return json.loads(text)


def preview(arguments):
    return subprocess.run(arguments, shell=False, check=True)


def get_total(items):
    try:
        return sum(items)
    except TypeError:
        return 0
