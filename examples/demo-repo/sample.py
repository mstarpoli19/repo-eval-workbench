"""Synthetic risk-pattern examples. Audit this file; do not run it."""

import subprocess


def remember(value, history=[]):
    history.append(value)
    return history


def parse_settings(text):
    return eval(text)


def preview(command):
    return subprocess.run(command, shell=True)


def get_total(items):
    try:
        return sum(items)
    except:
        return 0
