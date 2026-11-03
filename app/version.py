"""Public identity combines upstream baseline and the independent fork counter."""
VERSION = '0.18.4'  # Stable machine/update contract.
UPSTREAM_VERSION = '1.4.2'
CUSTOM_VERSION = VERSION.removeprefix('0.')
DISPLAY_VERSION = UPSTREAM_VERSION + '.' + CUSTOM_VERSION

def material_compatibility(value):
    return UPSTREAM_VERSION if value == VERSION else value
